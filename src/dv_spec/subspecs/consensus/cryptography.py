"""
Cryptographic utilities for QBFT consensus.

This module provides cryptographic primitives used in the QBFT consensus protocol,
including hashing, signing, and verification functions.
"""

from abc import abstractmethod
from typing import Protocol

from dv_spec.crypto import secp256k1
from dv_spec.encoding.ssz import hash_proto


class Hasher(Protocol):
    """Protocol for hash functions used in consensus."""

    @abstractmethod
    def hash_value(self, value: bytes) -> bytes:
        """Hash a given value and return the digest as bytes."""


class Signer(Protocol):
    """Protocol for signing functions used in consensus."""

    def sign(self, message: bytes, private_key: bytes) -> bytes:
        """Sign a message and return the signature."""
        ...

    def recover(self, message: bytes, signature: bytes) -> bytes:
        """Recover the public key for a given message and signature."""
        ...


class SSZHasher:
    """Hashes a consensus value by merkleizing its protobuf encoding."""

    def hash_value(self, value: bytes) -> bytes:
        """Return the SSZ hash root of an already-encoded consensus value.

        Callers pass the deterministic protobuf encoding of the value — for a
        duty that is an `UnsignedDataSet`, see
        `dv_spec.encoding.proto.encode_unsigned_data_set`. Encoding is the
        caller's job because the value type varies by duty, while this hash does
        not.
        """
        return hash_proto(value)


class Secp256k1Signer:
    """Signs consensus messages with the node's secp256k1 identity key."""

    def sign(self, message: bytes, private_key: bytes) -> bytes:
        """Sign a 32-byte signing root, returning 65 bytes of `R || S || V`."""
        return secp256k1.sign(private_key, message)

    def recover(self, message: bytes, signature: bytes) -> bytes:
        """Recover the compressed public key that signed a signing root."""
        return secp256k1.recover(message, signature)


# Default implementations
default_hasher = SSZHasher()


def hash_value(value: bytes) -> bytes:
    """Default hash function for consensus values."""
    return default_hasher.hash_value(value)


default_signer = Secp256k1Signer()


def sign(message: bytes, private_key: bytes) -> bytes:
    """Default sign function for consensus messages."""
    return default_signer.sign(message, private_key)


def recover(message: bytes, signature: bytes) -> bytes:
    """Default recover function for consensus messages."""
    return default_signer.recover(message, signature)
