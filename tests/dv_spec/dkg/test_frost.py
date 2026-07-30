import pytest

from dv_spec.subspecs.dkg.frost import (
    BROADCAST_TARGET_ID,
    FROST_PROTOCOL_PREFIX,
    ROUND1_CAST_MSG_ID,
    ROUND1_P2P_PROTOCOL_ID,
    ROUND2_CAST_MSG_ID,
    FrostMsgKey,
    FrostRound1Cast,
    FrostRound1Casts,
    FrostRound1P2P,
    FrostRound1ShamirShare,
    FrostRound2Cast,
    FrostRound2Casts,
    assemble_validator_shares,
    frost_dkg_context,
    round1_complete,
    round2_complete,
    verify_round1_casts,
    verify_round1_p2p,
    verify_round2_casts,
)

THRESHOLD = 3
NUM_VALIDATORS = 2
NUM_NODES = 4


def cast_key(val_idx: int = 0, source_id: int = 1, target_id: int = 0) -> FrostMsgKey:
    return FrostMsgKey(val_idx=val_idx, source_id=source_id, target_id=target_id)


def round1_cast(key: FrostMsgKey, commitments: int = THRESHOLD) -> FrostRound1Cast:
    return FrostRound1Cast(
        key=key,
        wi=b"\x01" * 32,
        ci=b"\x02" * 32,
        commitments=[bytes([i]) * 48 for i in range(commitments)],
    )


def round2_cast(key: FrostMsgKey, source_id: int) -> FrostRound2Cast:
    return FrostRound2Cast(
        key=key,
        verification_key=b"\xaa" * 48,
        vk_share=bytes([source_id]) * 48,
    )


def test_protocol_ids_have_no_trailing_slash() -> None:
    assert ROUND1_CAST_MSG_ID == "/charon/dkg/frost/2.0.0/round1/cast"
    assert ROUND1_P2P_PROTOCOL_ID == "/charon/dkg/frost/2.0.0/round1/p2p"
    assert ROUND2_CAST_MSG_ID == "/charon/dkg/frost/2.0.0/round2/cast"
    assert not FROST_PROTOCOL_PREFIX.endswith("/")


def test_frost_dkg_context_is_prefixed_lowercase_hex() -> None:
    assert frost_dkg_context(bytes([0xDE, 0xAD, 0xBE, 0xEF])) == "0xdeadbeef"
    assert frost_dkg_context(b"\x00" * 32) == "0x" + "00" * 32


def test_verify_round1_casts_accepts_valid_bundle() -> None:
    msg = FrostRound1Casts(
        casts=[round1_cast(cast_key(val_idx=idx, source_id=2)) for idx in range(NUM_VALIDATORS)]
    )
    verify_round1_casts(msg, sender_share_idx=2, num_validators=NUM_VALIDATORS, threshold=THRESHOLD)


@pytest.mark.parametrize(
    ("key", "commitments", "error"),
    [
        (cast_key(source_id=3), THRESHOLD, "invalid round 1 cast source ID"),
        (cast_key(source_id=2, target_id=1), THRESHOLD, "invalid round 1 cast target ID"),
        (cast_key(source_id=2, val_idx=NUM_VALIDATORS), THRESHOLD, "validator index"),
        (cast_key(source_id=2), THRESHOLD - 1, "invalid amount of commitments"),
    ],
)
def test_verify_round1_casts_rejects_invalid_bundle(
    key: FrostMsgKey, commitments: int, error: str
) -> None:
    msg = FrostRound1Casts(casts=[round1_cast(key, commitments=commitments)])
    with pytest.raises(ValueError, match=error):
        verify_round1_casts(
            msg, sender_share_idx=2, num_validators=NUM_VALIDATORS, threshold=THRESHOLD
        )


def test_verify_round2_casts() -> None:
    valid = FrostRound2Casts(casts=[round2_cast(cast_key(source_id=2), source_id=2)])
    verify_round2_casts(valid, sender_share_idx=2, num_validators=NUM_VALIDATORS)

    wrong_source = FrostRound2Casts(casts=[round2_cast(cast_key(source_id=1), source_id=1)])
    with pytest.raises(ValueError, match="invalid round 2 cast source ID"):
        verify_round2_casts(wrong_source, sender_share_idx=2, num_validators=NUM_VALIDATORS)


def test_verify_round1_p2p_requires_this_node_as_target() -> None:
    share = FrostRound1ShamirShare(key=cast_key(source_id=2, target_id=3), id=3, value=b"\x07" * 32)
    verify_round1_p2p(
        FrostRound1P2P(shares=[share]),
        sender_share_idx=2,
        receiver_share_idx=3,
        num_validators=NUM_VALIDATORS,
    )

    with pytest.raises(ValueError, match="invalid round 1 p2p target ID"):
        verify_round1_p2p(
            FrostRound1P2P(shares=[share]),
            sender_share_idx=2,
            receiver_share_idx=4,
            num_validators=NUM_VALIDATORS,
        )


def test_verify_round1_p2p_rejects_mismatched_source() -> None:
    share = FrostRound1ShamirShare(key=cast_key(source_id=1, target_id=3), id=3, value=b"\x07" * 32)
    with pytest.raises(ValueError, match="invalid round 1 p2p source ID"):
        verify_round1_p2p(
            FrostRound1P2P(shares=[share]),
            sender_share_idx=2,
            receiver_share_idx=3,
            num_validators=NUM_VALIDATORS,
        )


def test_verify_round1_p2p_rejects_unknown_validator() -> None:
    share = FrostRound1ShamirShare(
        key=cast_key(val_idx=NUM_VALIDATORS, source_id=2, target_id=3), id=3, value=b"\x07" * 32
    )
    with pytest.raises(ValueError, match="validator index"):
        verify_round1_p2p(
            FrostRound1P2P(shares=[share]),
            sender_share_idx=2,
            receiver_share_idx=3,
            num_validators=NUM_VALIDATORS,
        )


def test_round1_complete_counts_own_cast_but_not_own_share() -> None:
    assert not round1_complete(NUM_NODES - 1, NUM_NODES - 1, NUM_NODES)
    assert not round1_complete(NUM_NODES, NUM_NODES - 2, NUM_NODES)
    assert round1_complete(NUM_NODES, NUM_NODES - 1, NUM_NODES)


@pytest.mark.parametrize(
    ("casts", "p2ps", "error"),
    [
        (NUM_NODES + 1, NUM_NODES - 1, "too many round 1 casts messages"),
        (NUM_NODES, NUM_NODES, "too many round 1 p2p messages"),
    ],
)
def test_round1_complete_rejects_excess_bundles(casts: int, p2ps: int, error: str) -> None:
    with pytest.raises(ValueError, match=error):
        round1_complete(casts, p2ps, NUM_NODES)


def test_round2_complete() -> None:
    assert not round2_complete(NUM_NODES - 1, NUM_NODES)
    assert round2_complete(NUM_NODES, NUM_NODES)


def test_assemble_validator_shares_keys_public_shares_by_share_index() -> None:
    casts = [
        round2_cast(cast_key(val_idx=val_idx, source_id=source_id), source_id)
        for val_idx in range(NUM_VALIDATORS)
        for source_id in range(1, NUM_NODES + 1)
    ]
    pubkeys = {val_idx: bytes([val_idx]) * 48 for val_idx in range(NUM_VALIDATORS)}
    secrets = {val_idx: bytes([val_idx + 100]) * 32 for val_idx in range(NUM_VALIDATORS)}

    shares = assemble_validator_shares(casts, pubkeys, secrets)

    assert len(shares) == NUM_VALIDATORS
    for val_idx, share in enumerate(shares):
        assert share.validator_pubkey == pubkeys[val_idx]
        assert share.secret_share == secrets[val_idx]
        assert sorted(share.public_shares.shares) == list(range(1, NUM_NODES + 1))
        assert share.public_shares.shares[1] == b"\x01" * 48


def test_assemble_validator_shares_requires_local_key_material() -> None:
    casts = [round2_cast(cast_key(source_id=1), source_id=1)]
    with pytest.raises(ValueError, match="missing local key material"):
        assemble_validator_shares(casts, {}, {0: b"\x01" * 32})


def test_broadcast_target_id_is_zero() -> None:
    assert BROADCAST_TARGET_ID == 0
