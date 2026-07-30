"""Tests for the rules a node applies before trusting a lock file.

The happy path over real Charon-generated keys is covered by
`tests/test_vectors.py`. These tests cover the rejections, which is where the
security value is: a lock that fails one of these checks attests to a different
cluster than the one it describes.
"""

from __future__ import annotations

from typing import List, NamedTuple

import pytest

from dv_spec.cluster.definition import Creator, Definition, Operator, ValidatorAddresses
from dv_spec.cluster.hashing import lock_hash
from dv_spec.cluster.lock import (
    BuilderRegistration,
    DistValidator,
    Lock,
    Registration,
)
from dv_spec.cluster.verification import (
    aggregate_pubkeys,
    verify_node_signatures,
    verify_pubshare_counts,
    verify_shares_reconstruct,
    verify_signature_aggregate,
)
from dv_spec.crypto import bls, secp256k1

ADDRESS = "0x" + "11" * 20

# A degree-1 polynomial over the BLS scalar field, so a threshold of 2
# reconstructs the group key and a third share still lies on the same line.
SECRET_CONSTANT = 0x2A5D4F1C3B7E9016D8C4A2F0E6B8D1C3A5F7092B4D6E8A0C2F4160B8D3A5C7E91
SECRET_SLOPE = 0x11223344556677889900AABBCCDDEEFF0011223344556677889900AABBCCDDEE
THRESHOLD = 2
SHARE_COUNT = 3

NODE_SECRETS = [
    bytes.fromhex("4f3edf983ac636a65a842ce7c78d9aa706d3b113bce9c46f30d7d21715b23b1d"),
    bytes.fromhex("2b0f1a3f5c9d8e7b6a4c2d0e1f3a5b7c9d8e6f4a2b0c1d3e5f7a9b8c6d4e2f01"),
]


def scalar_to_secret(value: int) -> bytes:
    return (value % bls.BLS_MODULUS).to_bytes(32, "big")


class Sharing(NamedTuple):
    """A real threshold sharing, so recovery arithmetic is exercised for real."""

    group_pubkey: bytes
    shares: List[bytes]
    pubshares: List[bytes]


@pytest.fixture(scope="module")
def sharing() -> Sharing:
    shares = [
        scalar_to_secret(SECRET_CONSTANT + SECRET_SLOPE * point)
        for point in range(1, SHARE_COUNT + 1)
    ]

    return Sharing(
        group_pubkey=bls.secret_to_pubkey(scalar_to_secret(SECRET_CONSTANT)),
        shares=shares,
        pubshares=[bls.secret_to_pubkey(share) for share in shares],
    )


def make_definition(operator_count: int) -> Definition:
    return Definition(
        uuid="0194FDC2-FA2F-4CC0-81D3-FF12045B73C8",
        name="verification",
        version="v1.10.0",
        timestamp="2026-07-29T12:00:00+00:00",
        num_validators=1,
        threshold=THRESHOLD,
        dkg_algorithm="default",
        fork_version=bytes.fromhex("90000069"),
        operators=[
            Operator(address=ADDRESS, enr=f"enr:-node{index}") for index in range(operator_count)
        ],
        creator=Creator(address=ADDRESS),
        validator_addresses=[
            ValidatorAddresses(fee_recipient_address=ADDRESS, withdrawal_address=ADDRESS)
        ],
        target_gas_limit=30000000,
    )


def make_lock(pubkey: bytes, pubshares: List[bytes], operator_count: int = SHARE_COUNT) -> Lock:
    validator = DistValidator(
        pubkey=pubkey,
        pubshares=pubshares,
        builder_registration=BuilderRegistration(
            message=Registration(
                fee_recipient=b"\xfe" * 20,
                gas_limit=30000000,
                timestamp=1655733600,
                pubkey=pubkey,
            ),
            signature=b"\x55" * 96,
        ),
    )

    return Lock(definition=make_definition(operator_count), validators=[validator])


def test_aggregate_pubkeys_flattens_every_validators_shares() -> None:
    first = make_lock(b"\xa1" * 48, [b"\xb1" * 48, b"\xb2" * 48]).validators[0]
    second = first.model_copy(update={"pubkey": b"\xa2" * 48, "pubshares": [b"\xc1" * 48]})

    assert aggregate_pubkeys([first, second]) == [b"\xb1" * 48, b"\xb2" * 48, b"\xc1" * 48]


def test_pubshare_count_must_match_the_operator_count() -> None:
    lock = make_lock(b"\xa1" * 48, [b"\xb1" * 48], operator_count=3)

    with pytest.raises(ValueError, match="expected one per operator"):
        verify_pubshare_counts(lock)


def test_duplicate_validator_keys_are_rejected() -> None:
    lock = make_lock(b"\xa1" * 48, [b"\xb1" * 48], operator_count=1)
    duplicated = lock.model_copy(update={"validators": list(lock.validators) * 2})

    with pytest.raises(ValueError, match="repeats an earlier group public key"):
        verify_pubshare_counts(duplicated)


def test_a_repeated_public_share_is_rejected() -> None:
    # Charon rejects this outright, and reconstruction cannot be relied on to
    # catch it: a polynomial can legitimately take the same value at two points.
    lock = make_lock(b"\xa1" * 48, [b"\xb1" * 48, b"\xb1" * 48], operator_count=2)

    with pytest.raises(ValueError, match="repeats a public share"):
        verify_pubshare_counts(lock)


def test_shares_reconstruct_the_group_key(sharing: Sharing) -> None:
    lock = make_lock(sharing.group_pubkey, sharing.pubshares)

    verify_pubshare_counts(lock)
    verify_shares_reconstruct(lock)


def test_shares_reconstruct_with_threshold_equal_to_share_count(sharing: Sharing) -> None:
    # n-of-n leaves no extra shares, so the substitution loop must run zero
    # times rather than fail; every share is already in the quorum.
    lock = make_lock(sharing.group_pubkey, sharing.pubshares)
    n_of_n = lock.model_copy(
        update={"definition": lock.definition.model_copy(update={"threshold": len(sharing.shares)})}
    )

    verify_shares_reconstruct(n_of_n)


def test_an_empty_lock_fails_only_the_aggregate_check() -> None:
    # The structural checks pass vacuously on a lock with no operators and no
    # validators — as they do in charon — so the aggregate check is the one
    # that must reject it.
    empty = Lock(
        definition=make_definition(0).model_copy(
            update={"num_validators": 0, "validator_addresses": []}
        ),
        validators=[],
    )

    verify_pubshare_counts(empty)
    verify_shares_reconstruct(empty)
    assert verify_node_signatures(empty, [])
    assert not verify_signature_aggregate(empty)


def test_a_share_off_the_polynomial_is_rejected(sharing: Sharing) -> None:
    # Charon checks every share beyond the first quorum individually, so a single
    # corrupted extra share is caught here rather than when that node first signs.
    pubshares = list(sharing.pubshares)
    pubshares[2] = bls.secret_to_pubkey(scalar_to_secret(SECRET_CONSTANT + 1))
    lock = make_lock(sharing.group_pubkey, pubshares)

    with pytest.raises(ValueError, match="does not lie on the group key's polynomial"):
        verify_shares_reconstruct(lock)


def test_a_wrong_group_key_is_rejected(sharing: Sharing) -> None:
    other = bls.secret_to_pubkey(scalar_to_secret(SECRET_CONSTANT + 7))
    lock = make_lock(other, sharing.pubshares)

    with pytest.raises(ValueError, match="do not reconstruct"):
        verify_shares_reconstruct(lock)


@pytest.mark.parametrize("threshold", [0, -1, SHARE_COUNT + 1])
def test_an_out_of_range_threshold_is_rejected(sharing: Sharing, threshold: int) -> None:
    lock = make_lock(sharing.group_pubkey, sharing.pubshares)
    changed = lock.model_copy(
        update={"definition": lock.definition.model_copy(update={"threshold": threshold})}
    )

    with pytest.raises(ValueError, match="threshold"):
        verify_shares_reconstruct(changed)


def test_signature_aggregate_over_the_lock_hash(sharing: Sharing) -> None:
    lock = make_lock(sharing.group_pubkey, sharing.pubshares)
    digest = lock_hash(lock)
    aggregate = bls.aggregate([bls.sign(share, digest) for share in sharing.shares])

    signed = lock.model_copy(update={"signature_aggregate": aggregate})

    assert verify_signature_aggregate(signed)

    # Signing anything other than the lock hash must not verify, which is what
    # binds the aggregate to this exact cluster configuration.
    wrong = lock.model_copy(
        update={
            "signature_aggregate": bls.aggregate(
                [bls.sign(share, b"\x00" * 32) for share in sharing.shares]
            )
        }
    )

    assert not verify_signature_aggregate(wrong)


def test_node_signatures_verify_against_the_lock_hash() -> None:
    lock = make_lock(b"\xa1" * 48, [b"\xb1" * 48, b"\xb2" * 48], operator_count=2)
    digest = lock_hash(lock)
    pubkeys = [secp256k1.secret_to_pubkey(secret) for secret in NODE_SECRETS]
    signed = lock.model_copy(
        update={"node_signatures": [secp256k1.sign(secret, digest) for secret in NODE_SECRETS]}
    )

    assert verify_node_signatures(signed, pubkeys)

    swapped = signed.model_copy(update={"node_signatures": signed.node_signatures[::-1]})
    assert not verify_node_signatures(swapped, pubkeys)


def test_node_signature_count_mismatch_is_an_error_not_a_rejection() -> None:
    # A count mismatch means the file is malformed, which a caller should not be
    # able to confuse with a signature that simply failed to verify.
    lock = make_lock(b"\xa1" * 48, [b"\xb1" * 48, b"\xb2" * 48], operator_count=2)
    pubkeys = [secp256k1.secret_to_pubkey(secret) for secret in NODE_SECRETS]

    with pytest.raises(ValueError, match="node signatures for 2 operators"):
        verify_node_signatures(lock, pubkeys)

    signed = lock.model_copy(
        update={
            "node_signatures": [secp256k1.sign(NODE_SECRETS[0], lock_hash(lock))],
        }
    )

    with pytest.raises(ValueError, match="node signatures for 2 operators"):
        verify_node_signatures(signed, pubkeys)

    complete = lock.model_copy(
        update={
            "node_signatures": [secp256k1.sign(secret, lock_hash(lock)) for secret in NODE_SECRETS]
        }
    )

    with pytest.raises(ValueError, match="node public keys for 2 operators"):
        verify_node_signatures(complete, pubkeys[:1])
