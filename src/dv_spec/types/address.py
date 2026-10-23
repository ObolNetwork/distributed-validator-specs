"""Ethereum addresses as cluster files write them.

Unlike every other byte field in a cluster file, an address stays a hex *string*
in the data model and is decoded only where it is hashed or compared. This
module is the one place that decoding happens, so every address in a definition
or lock is held to the same rules:

- The string is `0x` followed by exactly 40 hex digits. No other length, no
  missing prefix, no `0X`.
- All-lowercase and all-uppercase digits are accepted as written.
- Mixed case is an EIP-55 checksum and MUST be the correct one. A mixed-case
  address with a wrong checksum is most likely a typo, and the checksum exists
  precisely so that a typo is caught rather than funds sent to it.

Charon decodes addresses without checking their case when it loads a cluster
file, so a lock carrying a mis-checksummed address hashes and verifies there.
This spec rejects it at validation.

Scope
-----
- Address syntax, EIP-55 checksums, and decoding to 20 bytes.

Out of scope
------------
- Which addresses a cluster should use. The zero address is a valid address
  here; refusing it is creation-time policy for tooling, not file validity.
"""

from __future__ import annotations

import re

from eth_hash.auto import keccak

ADDRESS_LENGTH = 20
"""Length of an Ethereum address, once its hex string is decoded."""

ZERO_ADDRESS = "0x" + "00" * ADDRESS_LENGTH
"""The all-zero address, which no one controls."""

_ADDRESS_RE = re.compile(r"0x[0-9a-fA-F]{40}")


def to_checksum_address(raw: bytes) -> str:
    """Encode a 20-byte address with its EIP-55 checksum.

    Each hex letter is upper-cased when the matching nibble of
    `keccak256(lowercase hex digits)` is 8 or more; digits have no case.

    Raises:
        ValueError: If `raw` is not 20 bytes.
    """
    if len(raw) != ADDRESS_LENGTH:
        raise ValueError(f"address has the wrong length: {len(raw)} bytes, expected 20")

    digits = raw.hex()
    digest = keccak(digits.encode("ascii")).hex()

    return "0x" + "".join(
        char.upper() if int(digest[index], 16) >= 8 else char for index, char in enumerate(digits)
    )


def decode_address(address: str) -> bytes:
    """Decode a hex Ethereum address to its 20 bytes, enforcing the rules above.

    Args:
        address: `0x` followed by 40 hex digits, all one case or EIP-55 mixed case.

    Returns:
        The 20 address bytes.

    Raises:
        ValueError: If the string is not `0x` plus 40 hex digits ("invalid
            address"), or is mixed case with a wrong EIP-55 checksum ("bad
            address checksum").
    """
    if not _ADDRESS_RE.fullmatch(address):
        raise ValueError(f"invalid address {address!r}: expected 0x followed by 40 hex digits")

    digits = address[2:]
    raw = bytes.fromhex(digits)

    if digits != digits.lower() and digits != digits.upper():
        if address != to_checksum_address(raw):
            raise ValueError(f"bad address checksum: {address!r} is mixed case but not EIP-55")

    return raw


def validate_address(address: str) -> str:
    """Validate an address string, returning it unchanged for use as a validator."""
    decode_address(address)

    return address


def validate_optional_address(address: str) -> str:
    """Validate an address string that may be empty, meaning absent."""
    if address:
        decode_address(address)

    return address
