"""Unit tests for cluster hashing behaviour that the vectors cannot express.

The vectors in `test_vectors/cluster_hashing.json` pin the hashes themselves.
These tests cover the rules around them: which fields each hash includes, what
the version guard rejects, and how malformed input fails.
"""

from __future__ import annotations

import pytest

from dv_spec.cluster.definition import (
    Creator,
    Definition,
    Operator,
    ValidatorAddresses,
    require_supported_version,
)
from dv_spec.cluster.hashing import (
    config_hash,
    decode_address,
    definition_hash,
    hash_registration,
    lock_hash,
    verify_definition_hashes,
    verify_lock_hash,
)
from dv_spec.cluster.lock import (
    BuilderRegistration,
    DepositData,
    DistValidator,
    Lock,
    Registration,
)
from dv_spec.encoding.ssz import HashWalker

ADDRESS = "0x" + "11" * 20
K1_SIGNATURE = b"\x22" * 65


def make_definition(**overrides: object) -> Definition:
    fields: dict[str, object] = {
        "uuid": "0194FDC2-FA2F-4CC0-81D3-FF12045B73C8",
        "name": "test",
        "version": "v1.10.0",
        "timestamp": "2026-07-29T12:00:00+00:00",
        "num_validators": 1,
        "threshold": 1,
        "dkg_algorithm": "default",
        "fork_version": bytes.fromhex("90000069"),
        "operators": [Operator(address=ADDRESS, enr="enr:-abc")],
        "creator": Creator(address=ADDRESS),
        "validator_addresses": [
            ValidatorAddresses(fee_recipient_address=ADDRESS, withdrawal_address=ADDRESS)
        ],
        "target_gas_limit": 30000000,
    }
    fields.update(overrides)

    return Definition.model_validate(fields)


def make_validator() -> DistValidator:
    pubkey = b"\xa1" * 48

    return DistValidator(
        pubkey=pubkey,
        pubshares=[b"\xb1" * 48],
        partial_deposit_data=[
            DepositData(
                pubkey=pubkey,
                withdrawal_credentials=b"\xd1" * 32,
                amount=32000000000,
                signature=b"\xe1" * 96,
            )
        ],
        builder_registration=BuilderRegistration(
            message=Registration(
                fee_recipient=b"\xfe" * 20,
                gas_limit=30000000,
                timestamp=1655733600,
                pubkey=pubkey,
            ),
            signature=b"\x55" * 96,
        ),
    )


def make_lock(definition: Definition) -> Lock:
    hashed = definition.model_copy(
        update={
            "config_hash": config_hash(definition),
        }
    )
    hashed = hashed.model_copy(update={"definition_hash": definition_hash(hashed)})
    lock = Lock(definition=hashed, validators=[make_validator()])

    return lock.model_copy(update={"lock_hash": lock_hash(lock)})


def test_config_hash_ignores_enrs_and_signatures() -> None:
    plain = make_definition()
    embellished = make_definition(
        operators=[
            Operator(
                address=ADDRESS,
                enr="enr:-something-completely-different",
                config_signature=K1_SIGNATURE,
                enr_signature=K1_SIGNATURE,
            )
        ],
        creator=Creator(address=ADDRESS, config_signature=K1_SIGNATURE),
    )

    assert config_hash(embellished) == config_hash(plain)
    assert definition_hash(embellished) != definition_hash(plain)


def test_config_hash_covers_every_other_field() -> None:
    base = make_definition()

    other_address = "0x" + "44" * 20
    for field, value in (
        ("uuid", "00000000-0000-0000-0000-000000000000"),
        ("name", "renamed"),
        ("timestamp", "2026-07-30T12:00:00+00:00"),
        ("num_validators", 2),
        ("threshold", 2),
        ("dkg_algorithm", "frost"),
        ("fork_version", bytes.fromhex("00000000")),
        ("operators", [Operator(address=other_address, enr="enr:-abc")]),
        ("creator", Creator(address=other_address)),
        (
            "validator_addresses",
            [ValidatorAddresses(fee_recipient_address=other_address, withdrawal_address=ADDRESS)],
        ),
        ("deposit_amounts", [32000000000]),
        ("consensus_protocol", "abft"),
        ("target_gas_limit", 36000000),
        ("compounding", True),
    ):
        changed = base.model_copy(update={field: value})
        assert config_hash(changed) != config_hash(base), f"{field} must affect the config hash"


def test_definition_hash_covers_the_config_hash() -> None:
    base = make_definition(config_hash=b"\x01" * 32)
    other = base.model_copy(update={"config_hash": b"\x02" * 32})

    assert definition_hash(other) != definition_hash(base)


def test_operator_order_is_significant() -> None:
    first = Operator(address="0x" + "11" * 20)
    second = Operator(address="0x" + "22" * 20)
    forwards = make_definition(operators=[first, second])
    backwards = make_definition(operators=[second, first])

    assert config_hash(forwards) != config_hash(backwards)


def test_lock_hash_covers_the_definition_and_the_validators() -> None:
    lock = make_lock(make_definition())
    other_definition = make_lock(make_definition(name="renamed"))

    assert lock_hash(other_definition) != lock_hash(lock)

    no_validators = lock.model_copy(update={"validators": []})
    assert lock_hash(no_validators) != lock_hash(lock)


def test_lock_hash_excludes_the_signatures_and_itself() -> None:
    lock = make_lock(make_definition())
    signed = lock.model_copy(
        update={
            "signature_aggregate": b"\x33" * 96,
            "node_signatures": [b"\x44" * 65],
            "lock_hash": b"\x00" * 32,
        }
    )

    assert lock_hash(signed) == lock_hash(lock)


def test_verify_definition_hashes_reports_which_hash_failed() -> None:
    definition = make_definition(config_hash=b"\x00" * 32, definition_hash=b"\x00" * 32)

    with pytest.raises(ValueError, match="config hash mismatch"):
        verify_definition_hashes(definition)

    correct_config = definition.model_copy(update={"config_hash": config_hash(definition)})
    with pytest.raises(ValueError, match="definition hash mismatch"):
        verify_definition_hashes(correct_config)


def test_verify_lock_hash_accepts_a_consistent_lock() -> None:
    verify_lock_hash(make_lock(make_definition()))


def test_verify_lock_hash_rejects_a_tampered_lock() -> None:
    lock = make_lock(make_definition())
    tampered = lock.model_copy(update={"validators": []})

    with pytest.raises(ValueError, match="lock hash mismatch"):
        verify_lock_hash(tampered)


@pytest.mark.parametrize("version", ["v1.9.0", "v1.11.0", "v2.0.0", ""])
def test_unsupported_versions_are_rejected(version: str) -> None:
    with pytest.raises(ValueError, match="unsupported cluster version"):
        require_supported_version(version)

    # The model rejects other versions at parse; pydantic's ValidationError is
    # a ValueError, so both layers reject the same way.
    with pytest.raises(ValueError, match="unsupported cluster version"):
        make_definition(version=version)

    # model_copy bypasses validation, so the hash entry points each keep their
    # own guard for objects mutated after construction.
    forced = make_definition().model_copy(update={"version": version})
    for hash_definition in (config_hash, definition_hash):
        with pytest.raises(ValueError, match="unsupported cluster version"):
            hash_definition(forced)

    forced_lock = Lock(definition=make_definition(), validators=[make_validator()]).model_copy(
        update={"definition": forced}
    )
    with pytest.raises(ValueError, match="unsupported cluster version"):
        lock_hash(forced_lock)


def test_decode_address_treats_empty_as_absent() -> None:
    # Charon left-pads the result to 20 bytes, so an absent address and an
    # all-zero address hash identically.
    assert decode_address("") == b""
    assert decode_address(ADDRESS) == b"\x11" * 20
    assert decode_address("11" * 20) == b"\x11" * 20


@pytest.mark.parametrize(
    "address",
    ["0x1234", "0x" + "11" * 21, "0xnothex" + "0" * 33, "0x11 22" + "33" * 18],
)
def test_decode_address_rejects_malformed_input(address: str) -> None:
    # The whitespace case would slip through bytes.fromhex; Go rejects it.
    with pytest.raises(ValueError, match="address"):
        decode_address(address)


def test_absent_signature_hashes_as_an_all_zero_one() -> None:
    absent = make_definition()
    zeroed = make_definition(
        operators=[
            Operator(
                address=ADDRESS,
                enr="enr:-abc",
                config_signature=b"\x00" * 65,
                enr_signature=b"\x00" * 65,
            )
        ]
    )

    assert definition_hash(zeroed) == definition_hash(absent)


def test_byte_list_capacities_are_enforced_at_their_boundary() -> None:
    # The capacity is bytes of UTF-8, not characters, so a name of 100 CJK
    # characters can be over the limit while a 256-character ASCII one is not.
    config_hash(make_definition(uuid="u" * 64))

    with pytest.raises(ValueError, match="uuid is 65 bytes"):
        config_hash(make_definition(uuid="u" * 65))

    with pytest.raises(ValueError, match="name is 300 bytes"):
        config_hash(make_definition(name="名" * 100))

    with pytest.raises(ValueError, match="enr is 1025 bytes"):
        definition_hash(make_definition(operators=[Operator(address=ADDRESS, enr="e" * 1025)]))

    # Composite lists are bounded too: a 257th operator exceeds the tree's
    # declared 256-leaf capacity inside merkleization.
    operators = [Operator(address=ADDRESS, enr="enr:-abc") for _ in range(257)]
    with pytest.raises(ValueError, match="exceed the limit"):
        config_hash(make_definition(operators=operators))


def test_fee_recipient_is_right_padded_unlike_every_other_address() -> None:
    # Charon writes this one field with PutBytes rather than a fixed length. A
    # reader treating it as Bytes20 would agree on every realistic input and
    # diverge on a short one, which is why the rule needs pinning here.
    def registration_root(fee_recipient: bytes) -> bytes:
        walker = HashWalker()
        message = Registration(
            fee_recipient=fee_recipient,
            gas_limit=30000000,
            timestamp=1655733600,
            pubkey=b"\xa1" * 48,
        )
        hash_registration(walker, message)

        return walker.hash_root()

    short = bytes.fromhex("9be1")

    assert registration_root(short) == registration_root(short + b"\x00" * 18)
    assert registration_root(short) != registration_root(b"\x00" * 18 + short)
