import pytest

from dv_spec.encoding.proto import (
    bytes_field,
    encode_any,
    encode_duty,
    encode_string_value,
    encode_unsigned_data_set,
    length_delimited,
    string_field,
    tag,
    varint,
    varint_field,
)
from dv_spec.types.duty import Duty, DutyType


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, "00"),
        (1, "01"),
        (127, "7f"),
        (128, "8001"),
        (300, "ac02"),
        (18446744073709551615, "ffffffffffffffffff01"),
    ],
)
def test_varint(value: int, expected: str) -> None:
    assert varint(value).hex() == expected


def test_varint_encodes_negatives_as_64_bit_twos_complement() -> None:
    # Protobuf sign-extends negative int32/int64 to 64 bits, so -1 is ten bytes
    # of ones rather than a compact encoding.
    assert varint(-1).hex() == "ffffffffffffffffff01"
    assert varint(-2).hex() == "feffffffffffffffff01"


def test_tag_packs_field_number_and_wire_type() -> None:
    assert tag(1, 0).hex() == "08"
    assert tag(1, 2).hex() == "0a"
    assert tag(11, 2).hex() == "5a"


def test_zero_and_empty_singular_fields_are_omitted() -> None:
    assert varint_field(1, 0) == b""
    assert bytes_field(1, b"") == b""
    assert string_field(1, "") == b""


def test_length_delimited_emits_empty_payloads() -> None:
    # Embedded messages and map entry fields have explicit presence, so an empty
    # payload is still a record on the wire.
    assert length_delimited(2, b"").hex() == "1200"


def test_encode_duty() -> None:
    assert encode_duty(Duty(slot=0, type=DutyType.UNKNOWN)) == b""
    assert encode_duty(Duty(slot=1, type=DutyType.ATTESTER)).hex() == "08011002"


def test_encode_unsigned_data_set_sorts_by_key() -> None:
    reverse = {"0xcc": b"\x03", "0xbb": b"\x02", "0xaa": b"\x01"}
    forward = {"0xaa": b"\x01", "0xbb": b"\x02", "0xcc": b"\x03"}

    assert encode_unsigned_data_set(reverse) == encode_unsigned_data_set(forward)
    assert encode_unsigned_data_set(forward).hex().startswith("0a090a0430786161")


def test_encode_any_omits_empty_value() -> None:
    assert encode_any("", b"") == b""
    assert encode_any("t", b"").hex() == "0a0174"


def test_encode_string_value_emits_empty_oneof_member() -> None:
    assert encode_string_value("").hex() == "1a00"
    assert encode_string_value("v1").hex() == "1a027631"
