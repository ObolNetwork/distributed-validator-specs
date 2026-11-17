"""Tests for parsing Charon's cluster file JSON.

The models exist to read the files Charon writes, so these tests are about the
encoding quirks of that format rather than about the protocol.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from dv_spec.cluster.definition import Definition, empty_list_if_null
from dv_spec.cluster.lock import DepositData, DistValidator, Lock
from dv_spec.types.hex import decode_hex_bytes, encode_hex_bytes

MINIMAL_DEFINITION = {
    "uuid": "0194FDC2-FA2F-4CC0-81D3-FF12045B73C8",
    "name": "test",
    "version": "v1.10.0",
    "timestamp": "2026-07-29T12:00:00+00:00",
    "num_validators": 1,
    "threshold": 1,
    "dkg_algorithm": "default",
    "fork_version": "0x90000069",
    "operators": [{"address": "0x" + "11" * 20, "enr": "enr:-abc"}],
    "creator": {"address": "0x" + "11" * 20},
    "validators": [
        {"fee_recipient_address": "0x" + "22" * 20, "withdrawal_address": "0x" + "33" * 20}
    ],
    "target_gas_limit": 30000000,
}


def test_hex_prefix_is_optional_on_read() -> None:
    assert decode_hex_bytes("0xabcd") == b"\xab\xcd"
    assert decode_hex_bytes("abcd") == b"\xab\xcd"
    assert decode_hex_bytes("") == b""
    assert decode_hex_bytes(b"\xab") == b"\xab"


@pytest.mark.parametrize("value", ["0xabc", "0xzz", "not hex", "0xab cd", "0xab\tcd"])
def test_malformed_hex_is_rejected(value: str) -> None:
    # The whitespace cases matter: bytes.fromhex would skip it, but Go's
    # hex.DecodeString rejects it, and charon must be able to parse any file
    # the spec accepts.
    with pytest.raises(ValueError, match="invalid hex string"):
        decode_hex_bytes(value)


def test_empty_bytes_encode_as_an_empty_string() -> None:
    # Charon's to0xHex writes "" rather than "0x" for empty bytes.
    assert encode_hex_bytes(b"") == ""
    assert encode_hex_bytes(b"\xab\xcd") == "0xabcd"


def test_null_lists_parse_as_empty() -> None:
    # Go marshals a nil slice as null, so Charon's own files contain it.
    assert empty_list_if_null(None) == []
    assert empty_list_if_null([1]) == [1]

    definition = Definition.model_validate(
        MINIMAL_DEFINITION
        | {"num_validators": 0, "operators": None, "validators": None, "deposit_amounts": None}
    )

    assert definition.operators == []
    assert definition.validator_addresses == []
    assert definition.deposit_amounts == []


def test_absent_keys_default_to_go_zero_values() -> None:
    # Charon unmarshals a missing key to the Go zero value and hashes that, so
    # any other default here would hash the same file differently. In particular
    # dkg_algorithm must not default to "default".
    trimmed = {
        key: value
        for key, value in MINIMAL_DEFINITION.items()
        if key not in ("name", "timestamp", "dkg_algorithm", "target_gas_limit")
    }
    definition = Definition.model_validate(trimmed)

    assert definition.name == ""
    assert definition.timestamp == ""
    assert definition.dkg_algorithm == ""
    assert definition.target_gas_limit == 0
    assert definition.compounding is False


def test_charon_json_key_names_are_accepted() -> None:
    definition = Definition.model_validate(MINIMAL_DEFINITION)

    assert len(definition.validator_addresses) == 1
    assert definition.fork_version == bytes.fromhex("90000069")
    assert definition.num_operators == 1


def test_gwei_amounts_are_written_as_json_strings() -> None:
    # Charon types deposit amounts as phase0.Gwei, which marshals as a string —
    # a 64-bit amount overflows a JSON reader that parses numbers as doubles.
    definition = Definition.model_validate(
        MINIMAL_DEFINITION | {"deposit_amounts": ["16000000000", "16000000000"]}
    )

    assert definition.deposit_amounts == [16000000000, 16000000000]

    dumped = json.loads(definition.model_dump_json(by_alias=True))
    assert dumped["deposit_amounts"] == ["16000000000", "16000000000"]

    deposit = DepositData.model_validate(
        {
            "pubkey": "0x" + "a1" * 48,
            "withdrawal_credentials": "0x" + "d1" * 32,
            "amount": "5159484672389300587",
            "signature": "0x" + "e1" * 96,
        }
    )

    assert deposit.amount == 5159484672389300587
    assert json.loads(deposit.model_dump_json())["amount"] == "5159484672389300587"


def test_unknown_fields_are_rejected() -> None:
    # A field this spec does not model is more likely a version mismatch than a
    # harmless addition, and silently ignoring it would hash the wrong thing.
    with pytest.raises(ValidationError, match="extra_forbidden"):
        Definition.model_validate(MINIMAL_DEFINITION | {"invented_field": 1})


def test_other_versions_are_rejected_at_parse() -> None:
    # A v1.9 file's key set is a subset of v1.10's, so extra="forbid" cannot
    # catch it. Without a version check it would parse cleanly and report model
    # defaults — target_gas_limit, compounding — as file content.
    with pytest.raises(ValidationError, match="unsupported cluster version"):
        Definition.model_validate(MINIMAL_DEFINITION | {"version": "v1.9.0"})


def test_num_validators_must_match_the_address_list() -> None:
    # Charon rejects the file at load ("num_validators does not match validators
    # length"), so a spec that accepted it would hash files no other
    # implementation ever sees.
    with pytest.raises(ValidationError, match="num_validators"):
        Definition.model_validate(MINIMAL_DEFINITION | {"num_validators": 2})


def test_int_fields_are_bounded() -> None:
    # Charon types these as signed Go ints and hashes a negative value by
    # letting uint64(v) wrap two's-complement. The spec rejects the file at
    # validation instead of reproducing the wrap; values above 2^63-1 fail Go's
    # own JSON parse, so both sides reject those.
    for override in (
        {"threshold": -1},
        {"num_validators": -1, "validators": []},
        {"target_gas_limit": 2**63},
        {"deposit_amounts": ["-1"]},
    ):
        with pytest.raises(ValidationError, match="greater than or equal|less than or equal"):
            Definition.model_validate(MINIMAL_DEFINITION | override)


def test_lock_uses_its_own_key_names() -> None:
    validator = {
        "distributed_public_key": "0x" + "a1" * 48,
        "public_shares": ["0x" + "b1" * 48],
        "builder_registration": {
            "message": {
                "fee_recipient": "0x" + "fe" * 20,
                "gas_limit": 30000000,
                "timestamp": 1655733600,
                "pubkey": "0x" + "a1" * 48,
            },
            "signature": "0x" + "55" * 96,
        },
    }
    lock = Lock.model_validate(
        {"cluster_definition": MINIMAL_DEFINITION, "distributed_validators": [validator]}
    )

    assert lock.version == "v1.10.0"
    assert lock.threshold == 1
    assert lock.validators[0].pubkey == b"\xa1" * 48
    assert lock.validators[0].pubshares == [b"\xb1" * 48]
    assert lock.validators[0].partial_deposit_data == []


def test_json_serialization_uses_charons_names_and_hex() -> None:
    lock = Lock.model_validate(
        {
            "cluster_definition": MINIMAL_DEFINITION,
            "distributed_validators": [],
            "lock_hash": "0x" + "77" * 32,
        }
    )
    # A plain dump, no by_alias argument: the default output must already be
    # a file charon can read, or every caller has to know the footgun.
    dumped = json.loads(lock.model_dump_json())

    assert dumped["lock_hash"] == "0x" + "77" * 32
    assert "cluster_definition" in dumped
    assert "distributed_validators" in dumped
    assert dumped["cluster_definition"]["fork_version"] == "0x90000069"
    assert "validators" in dumped["cluster_definition"]
    assert Lock.model_validate(dumped) == lock


def test_models_are_immutable() -> None:
    validator = DistValidator.model_validate(
        {
            "distributed_public_key": "0x" + "a1" * 48,
            "builder_registration": {
                "message": {
                    "fee_recipient": "0x" + "fe" * 20,
                    "gas_limit": 1,
                    "timestamp": 2,
                    "pubkey": "0x" + "a1" * 48,
                },
                "signature": "0x" + "55" * 96,
            },
        }
    )

    with pytest.raises(ValidationError, match="frozen"):
        validator.pubkey = b""  # type: ignore[misc]


# --- field rules --------------------------------------------------------------


def definition_with(**changes: object) -> dict[str, object]:
    return MINIMAL_DEFINITION | changes


@pytest.mark.parametrize("fork_version", ["0x900000", "0x9000006900", ""])
def test_fork_version_must_be_four_bytes(fork_version: str) -> None:
    with pytest.raises(ValidationError, match="wrong length"):
        Definition.model_validate(definition_with(fork_version=fork_version))


@pytest.mark.parametrize("length", [1, 64, 66])
def test_signatures_must_be_65_bytes_when_present(length: int) -> None:
    operator = {"address": "0x" + "11" * 20, "config_signature": "0x" + "ab" * length}

    with pytest.raises(ValidationError, match="wrong length"):
        Definition.model_validate(definition_with(operators=[operator]))


def test_absent_operator_and_creator_fields_are_allowed() -> None:
    # The shape `charon create cluster` writes: no operator or creator addresses
    # and no signatures. Empty is absence, and hashes as all zeros.
    definition = Definition.model_validate(
        definition_with(operators=[{"enr": "enr:-abc"}], creator={})
    )

    assert definition.operators[0].address == ""
    assert definition.creator.config_signature == b""


@pytest.mark.parametrize("field", ["fee_recipient_address", "withdrawal_address"])
def test_validator_addresses_are_never_absent(field: str) -> None:
    addresses = {"fee_recipient_address": "0x" + "22" * 20, "withdrawal_address": "0x" + "33" * 20}

    with pytest.raises(ValidationError, match="invalid address"):
        Definition.model_validate(definition_with(validators=[addresses | {field: ""}]))


@pytest.mark.parametrize(
    "address",
    [
        "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed",
        "0x5aaeb6053f3e94c9b9a09f33669435e7ef1beaed",
        "0x5AAEB6053F3E94C9B9A09F33669435E7EF1BEAED",
    ],
)
def test_addresses_may_be_checksummed_or_single_case(address: str) -> None:
    Definition.model_validate(
        definition_with(
            validators=[{"fee_recipient_address": address, "withdrawal_address": address}]
        )
    )


def test_a_mixed_case_address_must_carry_its_checksum() -> None:
    wrong = "0x5aaeb6053F3E94C9b9A09f33669435E7Ef1BeAed"

    with pytest.raises(ValidationError, match="bad address checksum"):
        Definition.model_validate(definition_with(creator={"address": wrong}))


@pytest.mark.parametrize("fork_version", ["0x00000000", "0x00000064"])
@pytest.mark.parametrize("field", ["fee_recipient_address", "withdrawal_address"])
def test_zero_validator_addresses_are_valid_on_mainnet_and_gnosis(
    fork_version: str, field: str
) -> None:
    # Refusing them is creation-time policy, not file validity: deployed mainnet
    # clusters use a zero withdrawal address deliberately.
    addresses = {"fee_recipient_address": "0x" + "22" * 20, "withdrawal_address": "0x" + "33" * 20}
    Definition.model_validate(
        definition_with(
            fork_version=fork_version, validators=[addresses | {field: "0x" + "00" * 20}]
        )
    )


@pytest.mark.parametrize(
    ("amounts", "compounding", "valid"),
    [
        (["1000000000", "31000000000"], False, True),
        (["32000000000"], False, True),
        (["999999999"], False, False),
        (["32000000001"], False, False),
        (["2048000000000"], True, True),
        (["2048000000001"], True, False),
        (["0"], True, False),
    ],
)
def test_deposit_amounts_are_bounded_by_credential_type(
    amounts: list[str], compounding: bool, valid: bool
) -> None:
    data = definition_with(deposit_amounts=amounts, compounding=compounding)
    if valid:
        Definition.model_validate(data)
        return

    with pytest.raises(ValidationError, match="deposit amount out of range"):
        Definition.model_validate(data)


LOCK_VALIDATOR = {
    "distributed_public_key": "0x" + "a1" * 48,
    "public_shares": ["0x" + "b1" * 48],
    "partial_deposit_data": [
        {
            "pubkey": "0x" + "a1" * 48,
            "withdrawal_credentials": "0x01" + "00" * 11 + "33" * 20,
            "amount": "32000000000",
            "signature": "0x" + "c1" * 96,
        }
    ],
    "builder_registration": {
        "message": {
            "fee_recipient": "0x" + "22" * 20,
            "gas_limit": 30000000,
            "timestamp": 1655733600,
            "pubkey": "0x" + "a1" * 48,
        },
        "signature": "0x" + "d1" * 96,
    },
}


@pytest.mark.parametrize(
    ("path", "size"),
    [
        (("distributed_public_key",), 48),
        (("public_shares", 0), 48),
        (("partial_deposit_data", 0, "pubkey"), 48),
        (("partial_deposit_data", 0, "withdrawal_credentials"), 32),
        (("partial_deposit_data", 0, "signature"), 96),
        (("builder_registration", "message", "fee_recipient"), 20),
        (("builder_registration", "message", "pubkey"), 48),
        (("builder_registration", "signature"), 96),
    ],
)
@pytest.mark.parametrize("delta", [-1, 1, "empty"])
def test_lock_fixed_fields_reject_any_other_length(
    path: tuple[object, ...], size: int, delta: object
) -> None:
    validator = json.loads(json.dumps(LOCK_VALIDATOR))
    DistValidator.model_validate(validator)

    target = validator
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = "" if delta == "empty" else "0x" + "ee" * (size + int(str(delta)))

    with pytest.raises(ValidationError, match="wrong length"):
        DistValidator.model_validate(validator)


def test_lock_signatures_are_length_checked_at_verification_not_parse() -> None:
    # Neither is covered by the lock hash, and Charon's own v1.10 regression
    # fixture carries 32-byte placeholders in both, so parsing accepts them.
    lock = Lock.model_validate(
        {
            "cluster_definition": MINIMAL_DEFINITION,
            "distributed_validators": [LOCK_VALIDATOR],
            "signature_aggregate": "0x" + "ab" * 32,
            "node_signatures": ["0x" + "cd" * 32],
        }
    )

    assert len(lock.signature_aggregate) == 32


@pytest.mark.parametrize(
    ("amounts", "valid"),
    [
        ([], True),
        (["16000000000", "16000000000"], True),
        (["16000000000", "15999999999"], False),
        (["1000000000"], False),
    ],
)
def test_non_empty_deposit_amounts_sum_to_at_least_32_eth(amounts: list[str], valid: bool) -> None:
    # Charon's VerifyDepositAmounts: repetition is allowed, empty means defaults.
    data = definition_with(deposit_amounts=amounts)
    if valid:
        Definition.model_validate(data)
        return

    with pytest.raises(ValidationError, match="sum to less than 32 ETH"):
        Definition.model_validate(data)
