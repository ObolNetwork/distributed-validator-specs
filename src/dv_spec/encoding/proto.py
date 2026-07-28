"""Deterministic protobuf encoding.

Every hash a Distributed Validator signs or compares is taken over protobuf
bytes, so two implementations that encode the same message differently compute
different hashes and cannot interoperate. Protobuf does not define a canonical
encoding, and Charon relies on Go's `proto.MarshalOptions{Deterministic: true}`.
This module pins down what that produces, so an implementation can match it
without running Go.

Three rules make the encoding canonical:

1. Fields are emitted in ascending field-number order.
2. Map entries are emitted in ascending key order.
3. A singular scalar field equal to its zero value is omitted entirely, but a
   *map entry's* key and value are always emitted, even when zero. Map entries
   have explicit presence; ordinary proto3 singular fields do not.

Rule 3 is the one that is easy to get wrong: an `UnsignedDataSet` entry with an
empty value encodes the value field as a zero-length record rather than
dropping it, and a present-but-empty embedded message (`Duty{}` inside a
`QBFTMsg`) likewise encodes as a zero-length record.

Scope
-----
- The wire primitives (varint, length-delimited) used by the DV protos.
- Encoders for the core messages whose hashes are wire-visible: `Duty`,
  `UnsignedDataSet`, `google.protobuf.Any` and `google.protobuf.Value`.

Out of scope
------------
- Field types the DV protos do not use: floats, `sint`/`fixed` variants,
  groups, and unknown-field retention.
- Decoding. Receivers are specified in terms of the decoded models.
"""

from __future__ import annotations

from typing import List, Mapping

from dv_spec.types.duty import Duty

WIRE_TYPE_VARINT = 0
"""Wire type for varint-encoded fields (integers, enums, booleans)."""

WIRE_TYPE_LENGTH_DELIMITED = 2
"""Wire type for length-delimited fields (bytes, strings, embedded messages)."""

STRING_VALUE_TYPE_URL = "type.googleapis.com/google.protobuf.Value"
"""Type URL of the `google.protobuf.Value` wrapper Charon wraps strings in.

Priority topics and priorities are `Any`-wrapped `structpb.Value`s rather than
bare strings, so the type URL is part of every priority hash.
"""

UINT64_MODULUS = 1 << 64
"""Modulus used to encode negative integers as 64-bit two's complement."""


def varint(value: int) -> bytes:
    """Encode an integer as a base-128 varint.

    Negative `int32`/`int64` values are sign-extended to 64 bits first, which is
    why they always occupy ten bytes on the wire.

    Args:
        value: The integer to encode.

    Returns:
        The varint bytes.
    """
    if value < 0:
        value += UINT64_MODULUS

    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def tag(field_number: int, wire_type: int) -> bytes:
    """Encode a field's key: its number shifted left by three, plus its type."""
    return varint((field_number << 3) | wire_type)


def varint_field(field_number: int, value: int) -> bytes:
    """Encode a singular varint field, omitting it when zero."""
    if value == 0:
        return b""

    return tag(field_number, WIRE_TYPE_VARINT) + varint(value)


def length_delimited(field_number: int, payload: bytes) -> bytes:
    """Encode a length-delimited field unconditionally, even when empty.

    Use this for embedded messages and for map entry fields, which have
    explicit presence. For singular `bytes` and `string` fields use
    `bytes_field` and `string_field`, which drop empty values.
    """
    return tag(field_number, WIRE_TYPE_LENGTH_DELIMITED) + varint(len(payload)) + payload


def bytes_field(field_number: int, value: bytes) -> bytes:
    """Encode a singular bytes field, omitting it when empty."""
    if not value:
        return b""

    return length_delimited(field_number, value)


def string_field(field_number: int, value: str) -> bytes:
    """Encode a singular string field, omitting it when empty."""
    return bytes_field(field_number, value.encode())


def encode_duty(duty: Duty) -> bytes:
    """Encode a `Duty` (`core.proto`).

    A `Duty` whose slot and type are both zero encodes to zero bytes; it is the
    enclosing message that records its presence.
    """
    return varint_field(1, duty.slot) + varint_field(2, int(duty.type))


def encode_unsigned_data_set(entries: Mapping[str, bytes]) -> bytes:
    """Encode an `UnsignedDataSet` (`core.proto`): `map<string,bytes> set = 1`.

    This is the consensus value of a duty, so its hash is the `value_hash` every
    node votes on. Entries are keyed by validator public key in `0x`-prefixed
    hex, and are sorted by that string.

    Args:
        entries: Unsigned duty data keyed by validator public key.

    Returns:
        The deterministic encoding.
    """
    out: List[bytes] = []
    for key in sorted(entries):
        entry = length_delimited(1, key.encode()) + length_delimited(2, entries[key])
        out.append(length_delimited(1, entry))

    return b"".join(out)


def encode_any(type_url: str, value: bytes) -> bytes:
    """Encode a `google.protobuf.Any` wrapping an already-encoded message."""
    return string_field(1, type_url) + bytes_field(2, value)


def encode_string_value(value: str) -> bytes:
    """Encode a `google.protobuf.Value` holding a string.

    `string_value` is field 3 of a oneof, and oneof members have explicit
    presence: an empty string is still emitted, as a zero-length record.
    """
    return length_delimited(3, value.encode())


def encode_any_string(value: str) -> bytes:
    """Encode an `Any`-wrapped `Value` holding a string.

    This is the form the priority protocol uses for topics and priorities.
    """
    return encode_any(STRING_VALUE_TYPE_URL, encode_string_value(value))
