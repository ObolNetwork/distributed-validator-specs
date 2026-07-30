"""BLS12-381 signatures and threshold aggregation.

Distributed Validators sign with BLS12-381 under the Ethereum scheme
(`BLS_SIG_BLS12381G2_XMD:SHA-256_SSWU_RO_POP_`, minimal-pubkey-size), so a
partial signature produced by a DV node is an ordinary validator signature under
that node's key share. Charon reaches this scheme by initialising Herumi with
`SetETHmode(EthModeLatest)`; here it is `py_ecc`'s `G2ProofOfPossession`.

Two aggregations exist and they are not interchangeable:

- **Threshold aggregation** reconstructs the *validator's* signature from
  `threshold` partial signatures by Lagrange interpolation at zero over the
  1-based share indices. Used for every duty, and for the deposit data and
  builder registrations produced by a DKG.
- **Plain aggregation** sums signatures with no coefficients, producing a
  multi-signature that verifies against the *set* of signing keys rather than
  against one key. Used for the cluster lock hash.

Applying the wrong one yields a signature that verifies against nothing.

Scope
-----
- Key derivation, signing, verification, and both aggregations.

Out of scope
------------
- Ethereum signing roots and domains; a message here is already the bytes to be
  signed.
- Key generation and secret handling. The spec never needs to invent a secret.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from eth_typing import BLSPubkey, BLSSignature
from py_ecc.bls import G2ProofOfPossession
from py_ecc.bls.g2_primitives import (
    G1_to_pubkey,
    G2_to_signature,
    pubkey_to_G1,
    signature_to_G2,
)
from py_ecc.optimized_bls12_381 import add, curve_order, multiply

BLS_MODULUS = curve_order
"""Order `r` of the BLS12-381 scalar field, the modulus for interpolation."""

SECRET_LENGTH = 32
"""Byte length of a secret key or key share, big-endian."""

PUBKEY_LENGTH = 48
"""Byte length of a public key or public share (compressed G1 point)."""

SIGNATURE_LENGTH = 96
"""Byte length of a signature (compressed G2 point)."""


def secret_to_int(secret: bytes) -> int:
    """Interpret secret key bytes as a scalar.

    Secrets are big-endian, matching both the Ethereum key format and Charon's
    `tbls.PrivateKey` serialization.

    Raises:
        ValueError: If the length is wrong or the scalar is out of range.
    """
    if len(secret) != SECRET_LENGTH:
        raise ValueError(f"secret must be {SECRET_LENGTH} bytes, got {len(secret)}")

    value = int.from_bytes(secret, "big")
    if not 0 < value < BLS_MODULUS:
        raise ValueError("secret out of range")

    return value


def secret_to_pubkey(secret: bytes) -> bytes:
    """Derive the public key of a secret key or key share."""
    return bytes(G2ProofOfPossession.SkToPk(secret_to_int(secret)))


def sign(secret: bytes, message: bytes) -> bytes:
    """Sign a message with a secret key or key share.

    Signing with a key share produces a partial signature; nothing about the
    operation distinguishes the two.
    """
    return bytes(G2ProofOfPossession.Sign(secret_to_int(secret), message))


def verify(pubkey: bytes, message: bytes, signature: bytes) -> bool:
    """Verify a signature under a single public key or public share."""
    return bool(G2ProofOfPossession.Verify(BLSPubkey(pubkey), message, BLSSignature(signature)))


def aggregate(signatures: Sequence[bytes]) -> bytes:
    """Aggregate signatures with no coefficients, into a multi-signature.

    The result verifies with `verify_aggregate` against the signers' public keys,
    not with `verify` against any one key.
    """
    if not signatures:
        raise ValueError("no signatures to aggregate")

    return bytes(G2ProofOfPossession.Aggregate([BLSSignature(sig) for sig in signatures]))


def verify_aggregate(pubkeys: Sequence[bytes], message: bytes, signature: bytes) -> bool:
    """Verify a multi-signature over one message against every signer's key."""
    return bool(
        G2ProofOfPossession.FastAggregateVerify(
            [BLSPubkey(pubkey) for pubkey in pubkeys], message, BLSSignature(signature)
        )
    )


def lagrange_coefficient(index: int, indices: Sequence[int]) -> int:
    """Compute the Lagrange interpolation coefficient for one share index.

    The coefficient evaluates the interpolating polynomial at zero, where the
    secret lives:

        lambda_i = product over j != i of (0 - j) / (i - j)  (mod r)

    Args:
        index: The share index to compute the coefficient for.
        indices: All share indices participating in the aggregation.

    Returns:
        The coefficient in `[0, BLS_MODULUS)`.

    Raises:
        ValueError: If `index` is not in `indices`, or `indices` contains
            duplicates or a non-positive index.

    Example:
        >>> lagrange_coefficient(1, [1, 2, 3])
        3
        >>> lagrange_coefficient(3, [1, 2, 3])
        1
    """
    if index not in indices:
        raise ValueError(f"index {index} not among the aggregation indices")

    if len(set(indices)) != len(indices):
        raise ValueError("duplicate share index among the aggregation indices")

    if any(other < 1 for other in indices):
        raise ValueError("share indices are 1-based and must be positive")

    coefficient = 1

    for other in indices:
        if other == index:
            continue

        numerator = -other % BLS_MODULUS
        denominator = (index - other) % BLS_MODULUS
        coefficient = coefficient * numerator * pow(denominator, -1, BLS_MODULUS) % BLS_MODULUS

    return coefficient


def _interpolate_at_zero(points_by_index: Mapping[int, Any]) -> Any:
    """Sum `lambda_i * P_i` over the given curve points."""
    if not points_by_index:
        raise ValueError("no points to interpolate")

    indices = sorted(points_by_index)
    total = None

    for index in indices:
        term = multiply(points_by_index[index], lagrange_coefficient(index, indices))
        total = term if total is None else add(total, term)

    return total


def threshold_aggregate(signatures_by_share_idx: Mapping[int, bytes]) -> bytes:
    """Reconstruct the validator's signature from partial signatures.

    Any `threshold` distinct share indices give the same result, because they
    interpolate the same polynomial. That is the property to test against: an
    implementation that has the coefficients subtly wrong still produces a
    well-formed signature, and only disagreement between two different quorums
    or a failed verification reveals it.

    Args:
        signatures_by_share_idx: Partial signatures keyed by 1-based share index.

    Returns:
        The 96-byte group signature.

    Raises:
        ValueError: If no signatures were supplied or an index is invalid.
    """
    points = {
        index: signature_to_G2(BLSSignature(sig)) for index, sig in signatures_by_share_idx.items()
    }

    return bytes(G2_to_signature(_interpolate_at_zero(points)))


def recover_pubkey(pubshares_by_share_idx: Mapping[int, bytes]) -> bytes:
    """Recover the validator's public key from public shares.

    The same interpolation as `threshold_aggregate`, in G1 instead of G2.

    Args:
        pubshares_by_share_idx: Public shares keyed by 1-based share index.

    Returns:
        The 48-byte validator public key.

    Raises:
        ValueError: If no shares were supplied or an index is invalid.
    """
    points = {
        index: pubkey_to_G1(BLSPubkey(share)) for index, share in pubshares_by_share_idx.items()
    }

    return bytes(G1_to_pubkey(_interpolate_at_zero(points)))
