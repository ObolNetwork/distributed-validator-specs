"""secp256k1 signatures in the form Distributed Validators exchange them.

Node identity is a secp256k1 key: it signs QBFT consensus messages, the cluster
lock hash, and the operator entries of a cluster definition. Every one of those
signatures is 65 bytes in `R || S || V` order with the recovery id **last**, and
the public key is recovered from the signature rather than being carried
alongside it — which is what lets a QBFT message identify its sender by peer
index alone.

Charon signs with `ecdsa.SignCompact` and then moves the recovery byte from the
front to the back (`app/k1util`). The nonce is RFC 6979 deterministic, so signing
the same hash with the same key twice gives identical bytes; this spec's
signatures are byte-identical to Charon's.

Scope
-----
- The 65-byte signature layout and the recovery id encoding.
- Signing, recovery and verification over a 32-byte hash.

Out of scope
------------
- What gets hashed. Callers pass a digest; see
  `dv_spec.subspecs.consensus.qbft.hashing` for the QBFT signing root.
- ENR encoding and peer ID derivation.
"""

from __future__ import annotations

from eth_keys import KeyAPI
from eth_keys.backends import NativeECCBackend
from eth_keys.exceptions import BadSignature, ValidationError

SECRET_LENGTH = 32
"""Byte length of a secret key, big-endian."""

PUBKEY_LENGTH = 33
"""Byte length of a compressed public key."""

SIGNATURE_LENGTH = 65
"""Byte length of a signature: 32 bytes R, 32 bytes S, one byte V."""

HASH_LENGTH = 32
"""Byte length of the digest being signed."""

RECOVERY_ID_OFFSET = 27
"""Offset some encodings add to the recovery id, giving 27 or 28 instead of 0 or 1.

Charon emits the un-offset form but accepts both on receive, so an implementation
that normalises to 0/1 interoperates with one that does not.
"""

_keys = KeyAPI(NativeECCBackend())
"""Pure-Python ECC backend; correctness matters here, throughput does not."""


def _check_hash(digest: bytes) -> bytes:
    if len(digest) != HASH_LENGTH:
        raise ValueError(f"hash must be {HASH_LENGTH} bytes, got {len(digest)}")

    return digest


def normalise_recovery_id(signature: bytes) -> bytes:
    """Return the signature with its recovery id reduced to 0 or 1.

    Raises:
        ValueError: If the signature is the wrong length or its recovery id is
            not one of 0, 1, 27 or 28.
    """
    if len(signature) != SIGNATURE_LENGTH:
        raise ValueError(f"signature must be {SIGNATURE_LENGTH} bytes, got {len(signature)}")

    recovery_id = signature[-1]
    if recovery_id in (RECOVERY_ID_OFFSET, RECOVERY_ID_OFFSET + 1):
        return signature[:-1] + bytes([recovery_id - RECOVERY_ID_OFFSET])

    if recovery_id in (0, 1):
        return signature

    raise ValueError(f"invalid recovery id {recovery_id}")


def secret_to_pubkey(secret: bytes) -> bytes:
    """Derive the compressed public key of a secret key."""
    if len(secret) != SECRET_LENGTH:
        raise ValueError(f"secret must be {SECRET_LENGTH} bytes, got {len(secret)}")

    return bytes(_keys.PrivateKey(secret).public_key.to_compressed_bytes())


def sign(secret: bytes, digest: bytes) -> bytes:
    """Sign a 32-byte digest, returning 65 bytes of `R || S || V`."""
    if len(secret) != SECRET_LENGTH:
        raise ValueError(f"secret must be {SECRET_LENGTH} bytes, got {len(secret)}")

    return bytes(_keys.PrivateKey(secret).sign_msg_hash(_check_hash(digest)))


def recover(digest: bytes, signature: bytes) -> bytes:
    """Recover the compressed public key that produced a signature.

    Raises:
        ValueError: If the digest or signature is malformed — wrong length,
            invalid recovery id, or `R`/`S` outside the curve order. The
            backend's own exception types do not escape, so receiver-side
            validation only ever has to handle `ValueError`.
    """
    _check_hash(digest)
    normalised = normalise_recovery_id(signature)

    try:
        recovered = _keys.ecdsa_recover(digest, _keys.Signature(signature_bytes=normalised))
    except (BadSignature, ValidationError) as exc:
        raise ValueError(f"invalid signature: {exc}") from exc

    return bytes(recovered.to_compressed_bytes())


def verify(pubkey: bytes, digest: bytes, signature: bytes) -> bool:
    """Check that a signature recovers to the given compressed public key.

    Malformed signature bytes verify as False rather than raising: to a
    receiver, a signature that cannot be decoded and a signature by the wrong
    key are the same outcome. A wrong-length digest still raises, because that
    is a caller bug, not attacker-controlled input.
    """
    _check_hash(digest)

    try:
        return recover(digest, signature) == pubkey
    except ValueError:
        return False
