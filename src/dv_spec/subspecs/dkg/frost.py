"""FROST DKG specification models, constants, and validation rules.

FROST is the **default** DKG algorithm: a cluster definition with
`dkg_algorithm` set to `default`, `frost`, or left empty runs FROST. It is a
two-round protocol run once per distributed validator, with all validators
sharing the same two transport rounds (see `runFrostParallel` in Charon's
`dkg/frost.go`).

Scope
-----
- Message data models mirroring the protobuf schema used on the wire.
- The bcast message IDs and the libp2p protocol ID used to route them.
- The receiver-side validation rules that a conforming node MUST enforce.
- Round completion conditions and output artifact assembly.

Out of scope
------------
- FROST cryptography (Feldman verification, secret sharing, key derivation).
  These are library internals; the spec pins only what appears on the wire.
- Reliable broadcast mechanics; see `dv_spec.subspecs.reliable_bcast`.
- Ceremony step synchronisation; see `dv_spec.subspecs.dkg_sync`.
"""

from __future__ import annotations

from typing import Dict, Iterable, List

from pydantic import Field

from dv_spec.types.base import StrictBaseModel
from dv_spec.types.uint32 import Uint32

from .share import PublicShares, ValidatorShare

# ----------------------------
# Protocol identifiers
# ----------------------------

FROST_PROTOCOL_PREFIX = "/charon/dkg/frost/2.0.0"
"""Common prefix of every FROST message ID.

Charon builds the concrete IDs by path-joining a suffix onto the literal
`"/charon/dkg/frost/2.0.0/"`. The join normalises the path, so the trailing
slash of that literal does **not** appear in the resulting IDs.
"""

ROUND1_CAST_MSG_ID = f"{FROST_PROTOCOL_PREFIX}/round1/cast"
"""Reliable-broadcast message ID carrying `FrostRound1Casts`.

This is a *bcast message ID* (the `id` field of `BCastSigRequest` and
`BCastMessage`), not a libp2p protocol ID: the bytes travel over the reliable
broadcast protocol IDs `/charon/dkg/bcast/1.0.0/{sig,msg}`.
"""

ROUND2_CAST_MSG_ID = f"{FROST_PROTOCOL_PREFIX}/round2/cast"
"""Reliable-broadcast message ID carrying `FrostRound2Casts`."""

ROUND1_P2P_PROTOCOL_ID = f"{FROST_PROTOCOL_PREFIX}/round1/p2p"
"""libp2p protocol ID carrying `FrostRound1P2P` directly to a single peer.

Unlike the two cast IDs above, this is a real libp2p protocol ID with its own
stream handler, because the Shamir shares are secret and per-recipient.
"""

BROADCAST_TARGET_ID = 0
"""The `FrostMsgKey.target_id` value that marks a message as a broadcast."""

# ----------------------------
# Encoding constants
# ----------------------------

SCALAR_LENGTH = 32
"""Byte length of a BLS12-381 scalar (`wi`, `ci`, secret shares)."""

POINT_LENGTH = 48
"""Byte length of a compressed BLS12-381 G1 point (commitments, keys)."""


def frost_dkg_context(definition_hash: bytes) -> str:
    """Derive the FROST context string that binds a ceremony to its cluster.

    Every participant feeds this string into FROST key generation, so a
    mismatch makes the ceremony fail rather than silently produce diverging
    keys. Charon formats the cluster definition hash with Go's `%#x` verb,
    which is lowercase hex with a `0x` prefix.

    Args:
        definition_hash: The 32-byte cluster definition hash.

    Returns:
        The context string, e.g. `"0x1234...ef"`.

    Example:
        >>> frost_dkg_context(bytes([0xDE, 0xAD, 0xBE, 0xEF]))
        '0xdeadbeef'
    """
    return "0x" + definition_hash.hex()


# ----------------------------
# Message models (wire schema)
# ----------------------------


class FrostMsgKey(StrictBaseModel):
    """Routing key identifying the validator, sender, and recipient.

    Because all distributed validators share the two transport rounds, every
    payload carries the key that tells receivers which parallel FROST instance
    it belongs to.
    """

    val_idx: Uint32 = Field(
        description="Distributed validator index within this ceremony, 0-indexed"
    )
    source_id: Uint32 = Field(
        description="Sender's participant ID, 1-indexed and equal to cluster.NodeIdx.ShareIdx"
    )
    target_id: Uint32 = Field(
        description=(
            "Recipient's participant ID, 1-indexed; "
            f"{BROADCAST_TARGET_ID} marks an outgoing broadcast"
        )
    )


class FrostRound1Cast(StrictBaseModel):
    """One validator's round 1 broadcast: the Feldman commitments and proof."""

    key: FrostMsgKey = Field(description="Routing key; target_id MUST be the broadcast value")
    wi: bytes = Field(description=f"Schnorr proof scalar ({SCALAR_LENGTH} bytes)")
    ci: bytes = Field(description=f"Schnorr challenge scalar ({SCALAR_LENGTH} bytes)")
    commitments: List[bytes] = Field(
        default_factory=list,
        description=(
            f"Feldman commitments, each a compressed G1 point ({POINT_LENGTH} bytes); "
            "exactly `threshold` entries"
        ),
    )


class FrostRound1Casts(StrictBaseModel):
    """Round 1 broadcast bundle: one cast per validator in the ceremony."""

    casts: List[FrostRound1Cast] = Field(default_factory=list)


class FrostRound1ShamirShare(StrictBaseModel):
    """One validator's secret Shamir share destined for a single recipient."""

    key: FrostMsgKey = Field(description="Routing key; target_id MUST be the recipient")
    id: Uint32 = Field(description="Recipient's participant ID as produced by FROST secret sharing")
    value: bytes = Field(description=f"Shamir share scalar ({SCALAR_LENGTH} bytes)")


class FrostRound1P2P(StrictBaseModel):
    """Round 1 direct bundle: one Shamir share per validator, for one peer."""

    shares: List[FrostRound1ShamirShare] = Field(default_factory=list)


class FrostRound2Cast(StrictBaseModel):
    """One validator's round 2 broadcast: the group and per-node public keys."""

    key: FrostMsgKey = Field(description="Routing key; target_id MUST be the broadcast value")
    verification_key: bytes = Field(
        description=(
            f"Aggregate validator public key ({POINT_LENGTH}-byte compressed G1); "
            "identical across all honest participants"
        )
    )
    vk_share: bytes = Field(
        description=f"This node's public key share ({POINT_LENGTH}-byte compressed G1)"
    )


class FrostRound2Casts(StrictBaseModel):
    """Round 2 broadcast bundle: one cast per validator in the ceremony."""

    casts: List[FrostRound2Cast] = Field(default_factory=list)


# ----------------------------
# Receiver-side validation
# ----------------------------


def verify_round1_casts(
    msg: FrostRound1Casts,
    sender_share_idx: int,
    num_validators: int,
    threshold: int,
) -> None:
    """Validate a received round 1 broadcast bundle.

    Every cast in the bundle is checked, so a single malformed entry rejects
    the whole bundle and fails the ceremony for the sender.

    Args:
        msg: The received bundle.
        sender_share_idx: Share index of the peer that broadcast the bundle.
        num_validators: Number of validators generated by this ceremony.
        threshold: Cluster signing threshold `t`.

    Raises:
        ValueError: If any cast has a mismatched source, a non-broadcast
            target, an out-of-range validator index, or the wrong number of
            commitments.
    """
    for cast in msg.casts:
        _verify_cast_key(cast.key, sender_share_idx, num_validators, "round 1")

        if len(cast.commitments) != threshold:
            raise ValueError(
                f"invalid amount of commitments in round 1: "
                f"received {len(cast.commitments)}, expected {threshold}"
            )


def verify_round2_casts(
    msg: FrostRound2Casts,
    sender_share_idx: int,
    num_validators: int,
) -> None:
    """Validate a received round 2 broadcast bundle.

    Args:
        msg: The received bundle.
        sender_share_idx: Share index of the peer that broadcast the bundle.
        num_validators: Number of validators generated by this ceremony.

    Raises:
        ValueError: If any cast has a mismatched source, a non-broadcast
            target, or an out-of-range validator index.
    """
    for cast in msg.casts:
        _verify_cast_key(cast.key, sender_share_idx, num_validators, "round 2")


def verify_round1_p2p(
    msg: FrostRound1P2P,
    sender_share_idx: int,
    receiver_share_idx: int,
    num_validators: int,
) -> None:
    """Validate a received round 1 direct (Shamir share) bundle.

    Args:
        msg: The received bundle.
        sender_share_idx: Share index of the sending peer.
        receiver_share_idx: Share index of this node.
        num_validators: Number of validators generated by this ceremony.

    Raises:
        ValueError: If any share has a mismatched source, a target that is not
            this node, or an out-of-range validator index.
    """
    for share in msg.shares:
        if share.key.source_id != sender_share_idx:
            raise ValueError("invalid round 1 p2p source ID")

        if share.key.target_id != receiver_share_idx:
            raise ValueError("invalid round 1 p2p target ID")

        _verify_val_idx(share.key.val_idx, num_validators, "round 1 p2p")


def _verify_cast_key(
    key: FrostMsgKey,
    sender_share_idx: int,
    num_validators: int,
    round_name: str,
) -> None:
    """Validate the routing key of a broadcast cast.

    Args:
        key: The routing key to validate.
        sender_share_idx: Share index of the broadcasting peer.
        num_validators: Number of validators generated by this ceremony.
        round_name: Round label used in error messages.

    Raises:
        ValueError: If the key does not match the sender or the broadcast form.
    """
    if key.source_id != sender_share_idx:
        raise ValueError(f"invalid {round_name} cast source ID")

    if key.target_id != BROADCAST_TARGET_ID:
        raise ValueError(f"invalid {round_name} cast target ID")

    _verify_val_idx(key.val_idx, num_validators, f"{round_name} cast")


def _verify_val_idx(val_idx: int, num_validators: int, context: str) -> None:
    """Validate that a validator index addresses a validator in this ceremony.

    Args:
        val_idx: The validator index to validate.
        num_validators: Number of validators generated by this ceremony.
        context: Label used in the error message.

    Raises:
        ValueError: If the index is out of range.
    """
    if val_idx >= num_validators:
        raise ValueError(f"invalid {context} validator index")


# ----------------------------
# Round completion
# ----------------------------


def round1_complete(num_cast_bundles: int, num_p2p_bundles: int, num_nodes: int) -> bool:
    """Report whether round 1 has collected every expected bundle.

    A node counts its own broadcast bundle (it feeds a copy to itself), so it
    expects `n` cast bundles, but only `n - 1` direct bundles because it does
    not send Shamir shares to itself.

    Args:
        num_cast_bundles: Round 1 cast bundles received so far, including own.
        num_p2p_bundles: Round 1 direct bundles received so far.
        num_nodes: Number of nodes `n` participating in the ceremony.

    Returns:
        True once both counts have reached their expected values.

    Raises:
        ValueError: If either count exceeds its expected value, which means a
            peer sent more bundles than the protocol allows.
    """
    if num_cast_bundles > num_nodes:
        raise ValueError("too many round 1 casts messages")

    if num_p2p_bundles > num_nodes - 1:
        raise ValueError("too many round 1 p2p messages")

    return num_cast_bundles == num_nodes and num_p2p_bundles == num_nodes - 1


def round2_complete(num_cast_bundles: int, num_nodes: int) -> bool:
    """Report whether round 2 has collected every expected broadcast bundle.

    Args:
        num_cast_bundles: Round 2 cast bundles received so far, including own.
        num_nodes: Number of nodes `n` participating in the ceremony.

    Returns:
        True once `n` bundles have been received.
    """
    return num_cast_bundles == num_nodes


# ----------------------------
# Output artifact assembly
# ----------------------------


def assemble_validator_shares(
    round2_casts: Iterable[FrostRound2Cast],
    validator_pubkeys: Dict[int, bytes],
    secret_shares: Dict[int, bytes],
) -> List[ValidatorShare]:
    """Build the per-validator output artifacts from the round 2 broadcasts.

    The public share of each node is read from that node's round 2 cast, keyed
    by its 1-based share index. The aggregate validator public key and the
    secret share come from the local FROST instance: the `verification_key`
    field peers put on the wire is **not** cross-checked by Charon, so a
    divergent peer is only detected later, when the cluster lock signatures are
    verified.

    Args:
        round2_casts: All round 2 casts received, across all peers and
            validators, including this node's own.
        validator_pubkeys: Locally computed aggregate public key per validator
            index.
        secret_shares: This node's secret share per validator index.

    Returns:
        One `ValidatorShare` per validator index, ordered by ascending index.

    Raises:
        ValueError: If a validator index has casts but no local key material.
    """
    pub_shares: Dict[int, Dict[int, bytes]] = {}

    for cast in round2_casts:
        pub_shares.setdefault(cast.key.val_idx, {})[cast.key.source_id] = cast.vk_share

    shares: List[ValidatorShare] = []

    for val_idx in sorted(pub_shares):
        if val_idx not in validator_pubkeys or val_idx not in secret_shares:
            raise ValueError(f"missing local key material for validator index {val_idx}")

        shares.append(
            ValidatorShare(
                validator_pubkey=validator_pubkeys[val_idx],
                secret_share=secret_shares[val_idx],
                public_shares=PublicShares(shares=pub_shares[val_idx]),
            )
        )

    return shares
