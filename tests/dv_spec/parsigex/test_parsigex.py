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
    validate_share_indices,
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

    par_sig1 = ParSignedData(data=b"data1", signature=b"s" * 96, share_idx=0)
    par_sig2 = ParSignedData(data=b"data2", signature=b"t" * 96, share_idx=1)

    data_set = ParSignedDataSet(set={pubkey1: par_sig1, pubkey2: par_sig2})

    assert len(data_set.set) == 2
    assert data_set.set[pubkey1].share_idx == 0
    assert data_set.set[pubkey2].share_idx == 1


def test_parsigex_msg() -> None:
    """Test ParSigExMsg creation."""
    duty = Duty(slot=456, type=DutyType.RANDAO)
    data_set = ParSignedDataSet(
        set={"pubkey1": ParSignedData(data=b"x", signature=b"y" * 96, share_idx=0)}
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
            for i, pk in enumerate(pubkeys)
        }
    )

    extracted = extract_pubkeys(data_set)
    assert set(extracted) == set(pubkeys)


def test_count_shares() -> None:
    """Test counting shares in data set."""
    data_set = ParSignedDataSet(
        set={f"pk{i}": ParSignedData(data=b"x", signature=b"y" * 96, share_idx=i) for i in range(5)}
    )

    assert count_shares(data_set) == 5


def test_validate_share_indices() -> None:
    """Test share index validation."""
    # Valid indices (0-2)
    valid_set = ParSignedDataSet(
        set={
            "pk0": ParSignedData(data=b"x", signature=b"y" * 96, share_idx=0),
            "pk1": ParSignedData(data=b"x", signature=b"y" * 96, share_idx=1),
            "pk2": ParSignedData(data=b"x", signature=b"y" * 96, share_idx=2),
        }
    )

    assert validate_share_indices(valid_set, (0, 2)) is True
    assert validate_share_indices(valid_set, (0, 1)) is False  # idx 2 out of range

    # Invalid index (3 out of range)
    invalid_set = ParSignedDataSet(
        set={
            "pk0": ParSignedData(data=b"x", signature=b"y" * 96, share_idx=0),
            "pk3": ParSignedData(data=b"x", signature=b"y" * 96, share_idx=3),
        }
    )

    assert validate_share_indices(invalid_set, (0, 2)) is False
    assert validate_share_indices(invalid_set, (0, 3)) is True


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
