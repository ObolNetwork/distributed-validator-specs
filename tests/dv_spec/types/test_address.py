"""Tests for Ethereum address syntax and EIP-55 checksums."""

from __future__ import annotations

import pytest

from dv_spec.types.address import (
    decode_address,
    to_checksum_address,
    validate_optional_address,
)

# The test vectors from EIP-55 itself.
EIP55_VECTORS = [
    "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed",
    "0xfB6916095ca1df60bB79Ce92cE3Ea74c37c5d359",
    "0xdbF03B407c01E7cD3CBea99509d93f8DDDC8C6FB",
    "0xD1220A0cf47c7B9Be7A2E6BA89F429762e7b9aDb",
]


@pytest.mark.parametrize("address", EIP55_VECTORS)
def test_checksum_matches_eip55(address: str) -> None:
    assert to_checksum_address(bytes.fromhex(address[2:])) == address
    assert decode_address(address) == bytes.fromhex(address[2:])


@pytest.mark.parametrize("address", EIP55_VECTORS)
def test_single_case_addresses_need_no_checksum(address: str) -> None:
    raw = bytes.fromhex(address[2:])

    assert decode_address(address.lower()) == raw
    assert decode_address("0x" + address[2:].upper()) == raw


def test_a_wrong_checksum_is_rejected() -> None:
    with pytest.raises(ValueError, match="bad address checksum"):
        decode_address("0x5aaeb6053F3E94C9b9A09f33669435E7Ef1BeAed")


@pytest.mark.parametrize(
    "address",
    [
        "",
        "5aaeb6053f3e94c9b9a09f33669435e7ef1beaed",
        "0X5aaeb6053f3e94c9b9a09f33669435e7ef1beaed",
        "0x5aaeb6053f3e94c9b9a09f33669435e7ef1bea",
        "0x5aaeb6053f3e94c9b9a09f33669435e7ef1beaed00",
        "0x5aaeb6053f3e94c9b9a09f33669435e7ef1beaeg",
        " 0x5aaeb6053f3e94c9b9a09f33669435e7ef1beaed",
    ],
)
def test_malformed_addresses_are_rejected(address: str) -> None:
    with pytest.raises(ValueError, match="invalid address"):
        decode_address(address)


def test_optional_address_accepts_only_empty_as_absent() -> None:
    assert validate_optional_address("") == ""

    with pytest.raises(ValueError, match="invalid address"):
        validate_optional_address("0x")
