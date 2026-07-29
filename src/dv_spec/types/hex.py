"""Byte strings as cluster configuration files encode them.

Charon writes every byte field of a cluster definition or lock as a `0x`
prefixed lower-case hex string, and accepts the prefix as optional when reading
(`ethHex` in `cluster/helpers.go`). Ethereum addresses are the exception: they
stay strings all the way into the hash function, which decodes them there.

Scope
-----
- The JSON representation of byte fields in cluster files.

Out of scope
------------
- Address checksums (EIP-55). Charon compares addresses only after decoding
  them, so case is not significant.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BeforeValidator, PlainSerializer

HEX_PREFIX = "0x"
"""Prefix Charon writes on every hex byte field, and strips on read if present."""


def decode_hex_bytes(value: Any) -> Any:
    """Decode a hex string to bytes, leaving non-strings untouched.

    Whitespace is rejected, although `bytes.fromhex` would skip it, because
    Go's `hex.DecodeString` rejects it: a file this parses must be a file
    Charon parses.

    Args:
        value: A hex string with or without the `0x` prefix, or any other value,
            which is passed through for pydantic to validate.

    Returns:
        The decoded bytes, or `value` unchanged if it was not a string.

    Raises:
        ValueError: If the string is not valid hex, including odd length or
            embedded whitespace.
    """
    if not isinstance(value, str):
        return value

    text = value.removeprefix(HEX_PREFIX)
    if any(char.isspace() for char in text):
        raise ValueError(f"invalid hex string: whitespace in {value!r}")

    try:
        return bytes.fromhex(text)
    except ValueError as exc:
        raise ValueError(f"invalid hex string: {exc}") from exc


def encode_hex_bytes(value: bytes) -> str:
    """Encode bytes as a `0x` prefixed lower-case hex string.

    Empty bytes encode as the empty string rather than a bare `0x`, which is
    what Charon's `to0xHex` does.
    """
    return f"{HEX_PREFIX}{value.hex()}" if value else ""


HexBytes = Annotated[
    bytes,
    BeforeValidator(decode_hex_bytes),
    PlainSerializer(encode_hex_bytes, return_type=str, when_used="json"),
]
"""Bytes that read and write as a `0x` prefixed hex string in JSON."""
