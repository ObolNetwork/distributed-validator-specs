"""QBFT message encoding and the signing root.

A QBFT message is authenticated by a secp256k1 signature over the SSZ hash root
of the message's own deterministic protobuf encoding, with the signature field
cleared. Getting this root wrong is silent: signatures verify against nothing
and every peer rejects the message as unauthenticated.

Mirrors Charon's `core/consensus/qbft.signMsg` and `verifyMsgSig`.

Scope
-----
- The wire field numbers of `QBFTMsg`, including the reserved gaps.
- The signing root, and the rule that the signature is excluded from it.

Out of scope
------------
- secp256k1 signing and public-key recovery.
- `QBFTConsensusMsg`, the envelope carrying the message, its justifications and
  its values. It is never hashed as a whole; each part is hashed separately.
"""

from __future__ import annotations

from dv_spec.encoding.proto import bytes_field, encode_duty, length_delimited, varint_field
from dv_spec.encoding.ssz import ZERO_CHUNK, hash_proto
from dv_spec.subspecs.consensus.qbft.message import QBFTMsg


def encode_qbft_msg(msg: QBFTMsg, *, include_signature: bool) -> bytes:
    """Encode a `QBFTMsg` (`consensus.proto`).

    Field numbers 5, 7, 9 and 10 are reserved: they held fields that have since
    been removed, and their numbers are never reused. An implementation that
    renumbered the remaining fields to close the gaps would produce a different
    encoding, and therefore a different signing root.

    The `duty` field is always emitted, even when the duty is all zeros, because
    an embedded message has explicit presence.

    Both hash fields are likewise always emitted as 32 bytes: "no value" is the
    zero hash, not an absent field. Senders MUST follow this, because a receiver
    recomputes the signing root from the fields it decoded — a sender that
    omitted an empty hash field would produce a root no receiver can reproduce,
    and its signature would fail to verify.

    Args:
        msg: The message to encode.
        include_signature: Whether to emit field 8. Pass False to obtain the
            bytes the signature is computed over.

    Returns:
        The deterministic encoding.
    """
    out = varint_field(1, int(msg.type))
    out += length_delimited(2, encode_duty(msg.duty))
    out += varint_field(3, msg.peer_idx)
    out += varint_field(4, msg.round)
    out += varint_field(6, msg.prepared_round)

    if include_signature and msg.signature is not None:
        out += bytes_field(8, msg.signature)

    out += length_delimited(11, msg.value_hash or ZERO_CHUNK)
    out += length_delimited(12, msg.prepared_value_hash)

    return out


def qbft_signing_root(msg: QBFTMsg) -> bytes:
    """Return the 32 bytes a `QBFTMsg` signature is computed over.

    The signature field is excluded rather than zeroed, so signing a message and
    re-deriving the root from the signed message give the same value. Receivers
    MUST recompute the root this way instead of trusting any hash on the wire.

    Args:
        msg: The message, signed or unsigned.

    Returns:
        The 32-byte signing root.
    """
    return hash_proto(encode_qbft_msg(msg, include_signature=False))
