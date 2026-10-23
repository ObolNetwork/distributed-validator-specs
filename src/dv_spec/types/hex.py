"""Byte strings as cluster configuration files encode them.

Charon writes every byte field of a cluster definition or lock as a `0x`
prefixed lower-case hex string, and accepts the prefix as optional when reading
(`ethHex` in `cluster/helpers.go`). Ethereum addresses are the exception: they
stay strings all the way into the hash function, which decodes them there.

Every byte field of a cluster file has a fixed length, and the typed variants
`FixedHexBytes*` variants below reject any other length at validation. SSZ hashing
silently pads a short fixed-size field, so a malformed value would otherwise
hash like a padded one and every signature over that hash would still verify.

Scope
-----
- The JSON representation of byte fields in cluster files, and their lengths.

Out of scope
------------
- Ethereum addresses, which stay strings; see `dv_spec.types.address`.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import AfterValidator, BeforeValidator, PlainSerializer

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


def require_length(size: int, *, absent_ok: bool = False) -> AfterValidator:
    """Build a validator that requires bytes of exactly `size`.

    Args:
        size: The required length.
        absent_ok: Also accept empty bytes, for a field that is legitimately
            absent — an operator signature not yet collected, or a hash not yet
            computed. Only empty is accepted: a short value is still rejected.
    """

    def check(value: bytes) -> bytes:
        if not value and absent_ok:
            return value

        if len(value) != size:
            raise ValueError(f"wrong length: {len(value)} bytes, expected {size}")

        return value

    return AfterValidator(check)


FixedHexBytes4 = Annotated[HexBytes, require_length(4)]
"""Hex bytes of exactly 4 bytes: a fork version."""

FixedHexBytes20 = Annotated[HexBytes, require_length(20)]
"""Hex bytes of exactly 20 bytes: an execution address held as bytes."""

FixedHexBytes32 = Annotated[HexBytes, require_length(32)]
"""Hex bytes of exactly 32 bytes: withdrawal credentials."""

FixedHexBytes48 = Annotated[HexBytes, require_length(48)]
"""Hex bytes of exactly 48 bytes: a BLS public key or public share."""

FixedHexBytes96 = Annotated[HexBytes, require_length(96)]
"""Hex bytes of exactly 96 bytes: a BLS signature."""

OptionalHexBytes32 = Annotated[HexBytes, require_length(32, absent_ok=True)]
"""32 bytes or empty: a config, definition or lock hash not yet computed."""

OptionalHexBytes65 = Annotated[HexBytes, require_length(65, absent_ok=True)]
"""65 bytes or empty: a secp256k1 signature not yet collected."""
