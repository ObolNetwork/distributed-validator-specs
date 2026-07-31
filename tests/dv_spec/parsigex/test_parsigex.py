"""Tests for parsigex message models and helpers."""

import pytest
from pydantic import ValidationError

from dv_spec.subspecs.parsigex import (
    PROTOCOL_ID,
    Duty,
    DutyType,
    ParSigExMsg,
    ParSignedData,
    ParSignedDataSet,
    count_shares,
    extract_pubkeys,
    is_duty_always_accepted,
    make_simple_gater,
    validate_exchange_peers,
    validate_share_indices,
    verify_peer_share_idx,
)


def test_duty_creation() -> None:
    """Test creating a Duty instance."""
    duty = Duty(slot=123, type=DutyType.ATTESTER)
    assert duty.slot == 123
    assert duty.type == DutyType.ATTESTER


def test_duty_validation() -> None:
    """Test Duty validation."""
    # Valid duty
    duty = Duty(slot=0, type=DutyType.PROPOSER)
    assert duty.slot >= 0

    # Invalid negative slot should raise validation error
    with pytest.raises(ValidationError):
        Duty(slot=-1, type=DutyType.ATTESTER)


def test_par_signed_data() -> None:
    """Test ParSignedData creation."""
    data = ParSignedData(
        data=b"some signed data",
        signature=b"x" * 96,  # 96-byte BLS signature
        share_idx=2,
    )
    assert data.share_idx == 2
    assert len(data.signature) == 96


def test_par_signed_data_set() -> None:
    """Test ParSignedDataSet creation and manipulation."""
    pubkey1 = "0x" + "a" * 96
    pubkey2 = "0x" + "b" * 96

    par_sig1 = ParSignedData(data=b"data1", signature=b"s" * 96, share_idx=1)
    par_sig2 = ParSignedData(data=b"data2", signature=b"t" * 96, share_idx=2)

    data_set = ParSignedDataSet(set={pubkey1: par_sig1, pubkey2: par_sig2})

    assert len(data_set.set) == 2
    assert data_set.set[pubkey1].share_idx == 1
    assert data_set.set[pubkey2].share_idx == 2


def test_par_signed_data_rejects_zero_share_idx() -> None:
    """Share indices are 1-based; index 0 is not a valid signer."""
    with pytest.raises(ValidationError):
        ParSignedData(data=b"x", signature=b"y" * 96, share_idx=0)


def test_parsigex_msg() -> None:
    """Test ParSigExMsg creation."""
    duty = Duty(slot=456, type=DutyType.RANDAO)
    data_set = ParSignedDataSet(
        set={"pubkey1": ParSignedData(data=b"x", signature=b"y" * 96, share_idx=1)}
    )

    msg = ParSigExMsg(duty=duty, data_set=data_set)

    assert msg.duty.slot == 456
    assert msg.duty.type == DutyType.RANDAO
    assert len(msg.data_set.set) == 1


def test_protocol_id() -> None:
    """Test protocol ID constant."""
    assert PROTOCOL_ID == "/charon/parsigex/2.0.0"


def test_is_duty_always_accepted() -> None:
    """Test duty acceptance logic."""
    exit_duty = Duty(slot=100, type=DutyType.EXIT)
    builder_duty = Duty(slot=100, type=DutyType.BUILDER_REGISTRATION)
    attester_duty = Duty(slot=100, type=DutyType.ATTESTER)

    assert is_duty_always_accepted(exit_duty) is True
    assert is_duty_always_accepted(builder_duty) is True
    assert is_duty_always_accepted(attester_duty) is False


def test_make_simple_gater() -> None:
    """Test gater function creation."""
    expected = {
        Duty(slot=10, type=DutyType.ATTESTER),
        Duty(slot=11, type=DutyType.PROPOSER),
    }

    gater = make_simple_gater(expected)

    # Expected duties should pass
    assert gater(Duty(slot=10, type=DutyType.ATTESTER)) is True
    assert gater(Duty(slot=11, type=DutyType.PROPOSER)) is True

    # Unexpected duty should fail
    assert gater(Duty(slot=12, type=DutyType.ATTESTER)) is False

    # Always-accepted duties should pass
    assert gater(Duty(slot=999, type=DutyType.EXIT)) is True


def test_extract_pubkeys() -> None:
    """Test extracting pubkeys from data set."""
    pubkeys = ["pk1", "pk2", "pk3"]
    data_set = ParSignedDataSet(
        set={
            pk: ParSignedData(data=b"x", signature=b"y" * 96, share_idx=i)
            for i, pk in enumerate(pubkeys, start=1)
        }
    )

    extracted = extract_pubkeys(data_set)
    assert set(extracted) == set(pubkeys)


def test_count_shares() -> None:
    """Test counting shares in data set."""
    data_set = ParSignedDataSet(
        set={
            f"pk{i}": ParSignedData(data=b"x", signature=b"y" * 96, share_idx=i)
            for i in range(1, 6)
        }
    )

    assert count_shares(data_set) == 5


def test_validate_share_indices() -> None:
    """Test share index validation."""
    # Valid indices for a 3-node cluster (1-3)
    valid_set = ParSignedDataSet(
        set={
            "pk1": ParSignedData(data=b"x", signature=b"y" * 96, share_idx=1),
            "pk2": ParSignedData(data=b"x", signature=b"y" * 96, share_idx=2),
            "pk3": ParSignedData(data=b"x", signature=b"y" * 96, share_idx=3),
        }
    )

    assert validate_share_indices(valid_set, (1, 3)) is True
    assert validate_share_indices(valid_set, (1, 2)) is False  # idx 3 out of range

    # Index 4 is out of range for a 3-node cluster
    invalid_set = ParSignedDataSet(
        set={
            "pk1": ParSignedData(data=b"x", signature=b"y" * 96, share_idx=1),
            "pk4": ParSignedData(data=b"x", signature=b"y" * 96, share_idx=4),
        }
    )

    assert validate_share_indices(invalid_set, (1, 3)) is False
    assert validate_share_indices(invalid_set, (1, 4)) is True


# A non-contiguous layout: "other" keeps share index 4 after the operators that
# held indices 2 and 3 were removed. This is the case that separates a peer map
# from an assumption that share_idx == peer position + 1.
SELF_PEER = "peer-self"
OTHER_PEER = "peer-other"
SHARE_IDX_BY_PEER = {SELF_PEER: 1, OTHER_PEER: 4}


def partial_sig(share_idx: int) -> ParSignedData:
    return ParSignedData(data=b"lockhash", signature=b"y" * 96, share_idx=share_idx)


@pytest.mark.parametrize(
    ("sender", "share_idx"),
    [
        pytest.param(SELF_PEER, 1, id="own share index accepted"),
        pytest.param(OTHER_PEER, 4, id="assigned non-contiguous share index accepted"),
    ],
)
def test_verify_peer_share_idx_accepts_assigned_index(sender: str, share_idx: int) -> None:
    verify_peer_share_idx(SHARE_IDX_BY_PEER, sender, partial_sig(share_idx))


@pytest.mark.parametrize(
    ("sender", "share_idx", "message"),
    [
        pytest.param(OTHER_PEER, 2, "does not match", id="mismatched share index rejected"),
        pytest.param(SELF_PEER, 4, "does not match", id="another peer's share index rejected"),
        pytest.param("peer-unknown", 1, "unknown peer", id="unknown sender rejected"),
    ],
)
def test_verify_peer_share_idx_rejects(sender: str, share_idx: int, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        verify_peer_share_idx(SHARE_IDX_BY_PEER, sender, partial_sig(share_idx))


def test_par_signed_data_rejects_non_positive_share_idx_at_parse() -> None:
    """A non-positive share index cannot be parsed, so it never reaches the binding.

    Charon has no such constraint on the type and rejects the index inside the
    binding check instead. Both refuse the same input; the spec refuses it sooner.
    """
    with pytest.raises(ValidationError):
        partial_sig(0)


@pytest.mark.parametrize("share_idx", [0, -1])
def test_verify_peer_share_idx_rejects_non_positive_index(share_idx: int) -> None:
    """The binding still rejects a non-positive index it was handed unvalidated.

    Constructed without validation on purpose: this is the check that stands in
    for Charon's, for a caller that did not go through the model.
    """
    unvalidated = ParSignedData.model_construct(
        data=b"lockhash", signature=b"y" * 96, share_idx=share_idx
    )

    with pytest.raises(ValueError, match="does not match"):
        verify_peer_share_idx(SHARE_IDX_BY_PEER, SELF_PEER, unvalidated)


def test_validate_exchange_peers_accepts_non_contiguous_indices() -> None:
    validate_exchange_peers([SELF_PEER, OTHER_PEER], SHARE_IDX_BY_PEER, peer_idx=0)


def test_validate_exchange_peers_rejects_incomplete_map() -> None:
    """A peer missing from the map would otherwise time the exchange out."""
    with pytest.raises(ValueError, match="missing valid share index"):
        validate_exchange_peers([SELF_PEER, OTHER_PEER], {SELF_PEER: 1}, peer_idx=0)


@pytest.mark.parametrize("peer_idx", [-1, 2])
def test_validate_exchange_peers_rejects_out_of_range_peer_idx(peer_idx: int) -> None:
    with pytest.raises(ValueError, match="peer index out of range"):
        validate_exchange_peers([SELF_PEER, OTHER_PEER], SHARE_IDX_BY_PEER, peer_idx=peer_idx)


def test_duty_type_values() -> None:
    """Test DutyType enum values match expected constants."""
    assert DutyType.UNKNOWN.value == 0
    assert DutyType.PROPOSER.value == 1
    assert DutyType.ATTESTER.value == 2
    assert DutyType.SIGNATURE.value == 3
    assert DutyType.EXIT.value == 4
    # assert DutyType.BUILDER_PROPOSER.value == 5  # Deprecated
    assert DutyType.BUILDER_REGISTRATION.value == 6
    assert DutyType.RANDAO.value == 7
    assert DutyType.PREPARE_AGGREGATOR.value == 8
    assert DutyType.AGGREGATOR.value == 9
    assert DutyType.SYNC_MESSAGE.value == 10
    assert DutyType.PREPARE_SYNC_CONTRIBUTION.value == 11
    assert DutyType.SYNC_CONTRIBUTION.value == 12
    assert DutyType.INFO_SYNC.value == 13


def test_json_serialization() -> None:
    """Test that models can be serialized to/from JSON."""
    duty = Duty(slot=123, type=DutyType.ATTESTER)
    par_sig = ParSignedData(data=b"test", signature=b"s" * 96, share_idx=1)
    data_set = ParSignedDataSet(set={"pk1": par_sig})
    msg = ParSigExMsg(duty=duty, data_set=data_set)

    # Serialize to JSON
    json_str = msg.model_dump_json()
    assert isinstance(json_str, str)

    # Deserialize from JSON
    msg2 = ParSigExMsg.model_validate_json(json_str)
    assert msg2.duty.slot == 123
    assert msg2.duty.type == DutyType.ATTESTER
    assert msg2.data_set.set["pk1"].share_idx == 1
