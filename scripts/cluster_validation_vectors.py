"""Build the `cluster_validation` vector suite.

Imported by `generate_test_vectors.py`; not run on its own.

Every case is a complete cluster file that breaks **exactly one** rule, and is
otherwise as valid as this spec can make it: hashes recomputed, the signature
aggregate and node signatures re-signed, the deposit data and builder
registration signed by the real group key. A rejection therefore has only one
possible cause, which is what lets the suite assert the reason.

The cases that break a length or address rule go one step further: their hashes
and signatures are computed over the value a *lenient* reader ends up with —
the short field left-padded as Charon pads it, the long one truncated, the
mis-checksummed address decoded case-insensitively. A reader that pads instead
of rejecting finds every hash and every signature in such a file valid, so the
only way to pass the case is to enforce the rule itself. That is the failure
the suite exists to catch.

Keys are reused rather than invented: the BLS sharing is the one
`bls_threshold.json` pins, and the operators' ENRs and node keys are those of the
`real_keys_3_of_4` lock in `cluster_hashing.json`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from dv_spec.cluster.definition import (
    Creator,
    Definition,
    Operator,
    ValidatorAddresses,
)
from dv_spec.cluster.deposit import (
    GWEI_PER_ETH,
    default_deposit_amounts,
    deposit_signing_root,
    withdrawal_credentials,
)
from dv_spec.cluster.hashing import (
    config_hash,
    definition_hash,
    lock_hash,
    verify_definition_hashes,
)
from dv_spec.cluster.lock import (
    BuilderRegistration,
    DepositData,
    DistValidator,
    Lock,
    Registration,
)
from dv_spec.cluster.verification import registration_signing_root, verify_lock
from dv_spec.crypto import bls, secp256k1
from dv_spec.types.address import decode_address, to_checksum_address

VECTOR_ROOT = Path(__file__).resolve().parent.parent / "test_vectors"

HOODI = bytes.fromhex("10000910")
MAINNET = bytes.fromhex("00000000")
GNOSIS = bytes.fromhex("00000064")

ETH = GWEI_PER_ETH

# EIP-55's own examples, so the checksummed spellings are independently known.
WITHDRAWAL_ADDRESS = "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed"
FEE_RECIPIENT = "0xfB6916095ca1df60bB79Ce92cE3Ea74c37c5d359"
OTHER_ADDRESS = "0xdbF03B407c01E7cD3CBea99509d93f8DDDC8C6FB"
ZERO_ADDRESS = "0x" + "00" * 20

GAS_LIMIT = 30000000
REGISTRATION_TIMESTAMP = 1655733600

# The charon node keys of the real_keys_3_of_4 lock's operators, as in
# test_vectors/charon/cluster_generator/main.go. Checked against that lock's
# node_pubkeys before use.
NODE_SECRETS = [
    bytes.fromhex(secret)
    for secret in (
        "4f3edf983ac636a65a842ce7c78d9aa706d3b113bce9c46f30d7d21715b23b1d",
        "2b0f1a3f5c9d8e7b6a4c2d0e1f3a5b7c9d8e6f4a2b0c1d3e5f7a9b8c6d4e2f01",
        "6d4e2f0a1b3c5d7e9f8a6b4c2d0e1f3a5b7c9d8e6f4a2b0c1d3e5f7a9b8c6d42",
        "1f3a5b7c9d8e6f4a2b0c1d3e5f7a9b8c6d4e2f0a1b3c5d7e9f8a6b4c2d0e1f30",
    )
]

# Reason slugs, and the error text that identifies each. A rejection matching
# none of these — a hash mismatch, a failed aggregate — means a case broke more
# than its one rule, and generation stops.
REASONS: Dict[str, str] = {
    "invalid_length": "wrong length",
    "invalid_address": "invalid address",
    "bad_address_checksum": "bad address checksum",
    "deposit_amount_out_of_range": "deposit amount out of range",
    "deposit_amounts_sum_too_low": "deposit amounts sum to less than 32 ETH",
    "deposit_pubkey_mismatch": "deposit pubkey mismatch",
    "withdrawal_credentials_mismatch": "withdrawal credentials mismatch",
    "deposit_amount_not_in_definition": "deposit amount not in definition",
    "invalid_deposit_signature": "invalid deposit signature",
    "registration_pubkey_mismatch": "registration pubkey mismatch",
    "registration_fee_recipient_mismatch": "registration fee recipient mismatch",
    "invalid_registration_signature": "invalid registration signature",
}


class VectorGenerationError(Exception):
    """The spec disagreed with a case's expected verdict."""


def classify(error: ValueError) -> str:
    """Name the rule a rejection came from, refusing any unexpected rejection."""
    message = str(error)
    matches = [slug for slug, text in REASONS.items() if text in message]
    if len(matches) != 1:
        raise VectorGenerationError(f"unexpected rejection: {message}")

    return matches[0]


@dataclass(frozen=True)
class Keys:
    """The BLS sharing and node keys every case is signed with."""

    group_secret: bytes
    group_pubkey: bytes
    share_secrets: List[bytes]
    pubshares: List[bytes]
    enrs: List[str]
    node_pubkeys: List[bytes]


def load_keys() -> Keys:
    """Load the sharing from bls_threshold.json and the nodes from cluster_hashing.json."""
    sharing = json.loads((VECTOR_ROOT / "bls_threshold.json").read_text())
    partials = sorted(sharing["partials"], key=lambda partial: partial["input"]["share_idx"])
    share_secrets = [bytes.fromhex(partial["input"]["secret_hex"]) for partial in partials]

    hashing = json.loads((VECTOR_ROOT / "cluster_hashing.json").read_text())
    real = next(case for case in hashing["lock"] if case["name"] == "real_keys_3_of_4")
    node_pubkeys = [bytes.fromhex(pubkey) for pubkey in real["node_pubkeys"]]
    enrs = [operator["enr"] for operator in real["input"]["cluster_definition"]["operators"]]

    if [secp256k1.secret_to_pubkey(secret) for secret in NODE_SECRETS] != node_pubkeys:
        raise VectorGenerationError("node secrets do not match cluster_hashing.json's node_pubkeys")

    group_secret = bytes.fromhex(sharing["group_secret_hex"])

    return Keys(
        group_secret=group_secret,
        group_pubkey=bls.secret_to_pubkey(group_secret),
        share_secrets=share_secrets,
        pubshares=[bls.secret_to_pubkey(secret) for secret in share_secrets],
        enrs=enrs,
        node_pubkeys=node_pubkeys,
    )


def base_definition(keys: Keys, **updates: Any) -> Definition:
    """An unsigned 3-of-4 definition, the shape `charon create cluster` writes.

    Operator and creator addresses and signatures are absent, which is the
    legitimate empty case. `updates` are applied without validation, so a case
    can carry a value the model would reject.
    """
    definition = Definition(
        uuid="5C3F0B1E-6A2D-4E8F-9B7C-1D2E3F4A5B6C",
        name="cluster validation",
        version="v1.10.0",
        timestamp="2026-10-23T12:00:00+00:00",
        num_validators=1,
        threshold=3,
        dkg_algorithm="default",
        fork_version=HOODI,
        operators=[Operator(enr=enr) for enr in keys.enrs],
        creator=Creator(),
        validator_addresses=[
            ValidatorAddresses(
                fee_recipient_address=FEE_RECIPIENT, withdrawal_address=WITHDRAWAL_ADDRESS
            )
        ],
        deposit_amounts=[32 * ETH],
        consensus_protocol="qbft",
        target_gas_limit=GAS_LIMIT,
    )

    return definition.model_copy(update=updates)


def with_hashes(definition: Definition) -> Definition:
    """Store the definition's own config and definition hashes in it."""
    hashed = definition.model_copy(update={"config_hash": config_hash(definition)})

    return hashed.model_copy(update={"definition_hash": definition_hash(hashed)})


DepositTweak = Callable[[Dict[str, Any]], None]
"""Edits a deposit's fields before it is signed: pubkey, credentials, amount."""


@dataclass
class LockRecipe:
    """How a case's lock departs from the valid one, before it is signed."""

    definition: Dict[str, Any] = field(default_factory=dict)
    deposit: Optional[DepositTweak] = None
    # Sign the deposit over these fields instead of the ones it carries.
    deposit_signed_as: Optional[DepositTweak] = None
    deposit_fork_version: Optional[bytes] = None
    deposit_signer: Optional[bytes] = None
    # Replace the deposit signature after signing, for a malformed-length case.
    deposit_signature: Optional[Callable[[bytes], bytes]] = None
    registration: Dict[str, Any] = field(default_factory=dict)
    registration_signed_as: Dict[str, Any] = field(default_factory=dict)
    pubshares: Optional[Callable[[List[bytes]], List[bytes]]] = None


def sign_deposit(keys: Keys, fields: Dict[str, Any], fork_version: bytes, signer: bytes) -> bytes:
    """Sign a deposit message the way a DKG does, with the group secret."""
    root = deposit_signing_root(
        fields["pubkey"], fields["withdrawal_credentials"], fields["amount"], fork_version
    )

    return bls.sign(signer, root)


def build_lock(keys: Keys, recipe: LockRecipe) -> Lock:
    """Build and fully sign a lock from the valid one and a recipe."""
    definition = with_hashes(base_definition(keys, **recipe.definition))
    amounts = definition.deposit_amounts or list(default_deposit_amounts(definition.compounding))
    addresses = definition.validator_addresses[0]

    deposits = []
    for amount in amounts:
        fields: Dict[str, Any] = {
            "pubkey": keys.group_pubkey,
            # Lenient on purpose: a case may carry an address the strict rules
            # reject, and the credentials are what a lenient reader derives.
            "withdrawal_credentials": (b"\x02" if definition.compounding else b"\x01")
            + bytes(11)
            + bytes.fromhex(addresses.withdrawal_address[2:]),
            "amount": amount,
        }
        if recipe.deposit:
            recipe.deposit(fields)

        signed_as = dict(fields)
        if recipe.deposit_signed_as:
            recipe.deposit_signed_as(signed_as)

        signature = sign_deposit(
            keys,
            signed_as,
            recipe.deposit_fork_version or definition.fork_version,
            recipe.deposit_signer or keys.group_secret,
        )
        if recipe.deposit_signature:
            signature = recipe.deposit_signature(signature)
        deposits.append(DepositData.model_construct(**fields, signature=signature))

    message_fields: Dict[str, Any] = {
        "fee_recipient": bytes.fromhex(addresses.fee_recipient_address[2:]),
        "gas_limit": GAS_LIMIT,
        "timestamp": REGISTRATION_TIMESTAMP,
        "pubkey": keys.group_pubkey,
    }
    message = Registration.model_construct(**{**message_fields, **recipe.registration})
    signed_message = Registration.model_construct(
        **{**message_fields, **recipe.registration, **recipe.registration_signed_as}
    )
    registration = BuilderRegistration.model_construct(
        message=message,
        signature=bls.sign(
            keys.group_secret, registration_signing_root(signed_message, definition.fork_version)
        ),
    )

    pubshares = list(keys.pubshares)
    if recipe.pubshares:
        pubshares = recipe.pubshares(pubshares)

    validator = DistValidator.model_construct(
        pubkey=keys.group_pubkey,
        pubshares=pubshares,
        partial_deposit_data=deposits,
        builder_registration=registration,
    )
    lock = Lock.model_construct(
        definition=definition,
        validators=[validator],
        lock_hash=b"",
        signature_aggregate=b"",
        node_signatures=[],
    )
    digest = lock_hash(lock)

    return lock.model_copy(
        update={
            "lock_hash": digest,
            "signature_aggregate": bls.aggregate(
                [bls.sign(secret, digest) for secret in keys.share_secrets]
            ),
            "node_signatures": [secp256k1.sign(secret, digest) for secret in NODE_SECRETS],
        }
    )


JsonPatch = Callable[[Dict[str, Any]], None]
"""Edits a case's JSON after signing, to carry a value no model would build."""


def to_json(model: Definition | Lock, patch: Optional[JsonPatch]) -> Dict[str, Any]:
    """Serialize as Charon's file format, then apply the case's patch."""
    data: Dict[str, Any] = json.loads(model.model_dump_json())
    if patch:
        patch(data)

    return data


def verdict_of_definition(data: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """Parse and verify a definition the way the suite's consumer must."""
    try:
        verify_definition_hashes(Definition.model_validate(data))
    except ValueError as error:
        return False, classify(error)

    return True, None


def verdict_of_lock(data: Dict[str, Any], node_pubkeys: List[bytes]) -> Tuple[bool, Optional[str]]:
    """Parse and fully verify a lock the way the suite's consumer must."""
    try:
        verify_lock(Lock.model_validate(data), node_pubkeys)
    except ValueError as error:
        return False, classify(error)

    return True, None


# --- patches ----------------------------------------------------------------


def hex_bytes(value: bytes) -> str:
    """Encode bytes as Charon writes them."""
    return "0x" + value.hex()


def set_path(*path: Any, value: Any) -> JsonPatch:
    """A patch replacing the value at a JSON path."""

    def patch(data: Dict[str, Any]) -> None:
        target: Any = data
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = value

    return patch


def edit_path(*path: Any, edit: Callable[[str], str]) -> JsonPatch:
    """A patch rewriting the string at a JSON path."""

    def patch(data: Dict[str, Any]) -> None:
        target: Any = data
        for key in path[:-1]:
            target = target[key]
        target[path[-1]] = edit(target[path[-1]])

    return patch


def drop_leading_byte(value: str) -> str:
    """Drop the first byte of a 0x hex string: what Charon left-pads back."""
    return "0x" + value[4:]


def drop_trailing_byte(value: str) -> str:
    """Drop the last byte of a 0x hex string: what Charon right-pads back."""
    return value[:-2]


def mis_checksum(address: str) -> str:
    """Flip the case of one letter, leaving a mixed-case address with a bad checksum."""
    digits = list(address[2:])
    index = next(i for i, char in enumerate(digits) if char.isalpha())
    digits[index] = digits[index].swapcase()

    return "0x" + "".join(digits)


DEPOSIT = ("distributed_validators", 0, "partial_deposit_data", 0)
REGISTRATION = ("distributed_validators", 0, "builder_registration")
LOCK_ADDRESSES = ("cluster_definition", "validators", 0)


def credentials(prefix: int, address: str, padding: bytes = bytes(11)) -> bytes:
    """Withdrawal credentials with an arbitrary prefix and padding."""
    return bytes([prefix]) + padding + decode_address(address)


def set_deposit(**values: Any) -> DepositTweak:
    """A deposit tweak setting fields."""

    def tweak(fields: Dict[str, Any]) -> None:
        fields.update(values)

    return tweak


# --- cases ------------------------------------------------------------------


@dataclass
class Case:
    """One vector: a recipe, an optional JSON patch, the expected verdict."""

    name: str
    reason: Optional[str]
    notes: str
    recipe: Any = None
    patch: Optional[JsonPatch] = None


def definition_cases() -> List[Case]:
    """Cases over a definition file alone."""
    zero_withdrawal = ValidatorAddresses(
        fee_recipient_address=FEE_RECIPIENT, withdrawal_address=ZERO_ADDRESS
    )
    zero_fee = ValidatorAddresses(
        fee_recipient_address=ZERO_ADDRESS, withdrawal_address=WITHDRAWAL_ADDRESS
    )

    def addresses(
        fee_recipient_address: str = FEE_RECIPIENT, withdrawal_address: str = WITHDRAWAL_ADDRESS
    ) -> Dict[str, Any]:
        # Unvalidated, so a case can carry an address the rules reject.
        entry = ValidatorAddresses.model_construct(
            fee_recipient_address=fee_recipient_address, withdrawal_address=withdrawal_address
        )
        return {"validator_addresses": [entry]}

    signed_operators = {
        "operators": [
            Operator(
                address=to_checksum_address(bytes([index + 1]) * 20),
                enr=f"enr:-placeholder{index}",
                config_signature=b"\x00" + bytes([0x10 + index]) * 64,
                enr_signature=bytes([0x20 + index]) * 65,
            )
            for index in range(4)
        ],
        "creator": Creator(address=OTHER_ADDRESS, config_signature=bytes([0x30]) * 65),
    }

    return [
        Case(
            "checksummed_addresses",
            None,
            "The valid base definition: an unsigned definition as `charon create cluster` "
            "writes it, with absent (empty) operator and creator addresses and signatures, "
            "and EIP-55 checksummed validator addresses.",
            {},
        ),
        Case(
            "lowercase_addresses",
            None,
            "All-lowercase addresses carry no checksum and are accepted as written.",
            addresses(
                fee_recipient_address=FEE_RECIPIENT.lower(),
                withdrawal_address=WITHDRAWAL_ADDRESS.lower(),
            ),
        ),
        Case(
            "uppercase_addresses",
            None,
            "All-uppercase hex digits (with a lower-case 0x) carry no checksum either.",
            addresses(
                fee_recipient_address="0x" + FEE_RECIPIENT[2:].upper(),
                withdrawal_address="0x" + WITHDRAWAL_ADDRESS[2:].upper(),
            ),
        ),
        Case(
            "signed_operators",
            None,
            "Operator and creator addresses and 65-byte signatures present. The "
            "signatures are placeholders: only their lengths are in scope here.",
            signed_operators,
        ),
        Case(
            "zero_addresses_on_testnet",
            None,
            "The zero address is a valid validator address.",
            addresses(fee_recipient_address=ZERO_ADDRESS, withdrawal_address=ZERO_ADDRESS),
        ),
        Case(
            "deposit_amounts_at_standard_bounds",
            None,
            "1 ETH and 32 ETH, the bounds for 0x01 credentials.",
            {"deposit_amounts": [1 * ETH, 32 * ETH]},
        ),
        Case(
            "deposit_amounts_sum_to_exactly_32_eth",
            None,
            "16 ETH twice: repetition is allowed, and 32 ETH is the smallest valid sum.",
            {"deposit_amounts": [16 * ETH, 16 * ETH]},
        ),
        Case(
            "deposit_amounts_sum_one_gwei_below_32_eth",
            "deposit_amounts_sum_too_low",
            "16 ETH and 16 ETH less one Gwei: each amount is in range but they sum to "
            "one Gwei under 32 ETH, as Charon's VerifyDepositAmounts rejects.",
            {"deposit_amounts": [16 * ETH, 16 * ETH - 1]},
        ),
        Case(
            "single_deposit_amount_below_32_eth_total",
            "deposit_amounts_sum_too_low",
            "A single 1 ETH amount: in range, but non-empty amounts must sum to at least 32 ETH.",
            {"deposit_amounts": [1 * ETH]},
        ),
        Case(
            "deposit_amounts_at_compounding_bounds",
            None,
            "1 ETH and 2048 ETH with compounding set.",
            {"deposit_amounts": [1 * ETH, 2048 * ETH], "compounding": True},
        ),
        Case(
            "bad_withdrawal_address_checksum",
            "bad_address_checksum",
            "Mixed case with one letter's case flipped. The hashes are those of the "
            "correctly spelled address, which is what a case-insensitive reader decodes, so "
            "only the checksum check rejects it.",
            {},
            edit_path("validators", 0, "withdrawal_address", edit=mis_checksum),
        ),
        Case(
            "bad_fee_recipient_checksum",
            "bad_address_checksum",
            "As bad_withdrawal_address_checksum, for the fee recipient.",
            {},
            edit_path("validators", 0, "fee_recipient_address", edit=mis_checksum),
        ),
        Case(
            "address_without_0x_prefix",
            "invalid_address",
            "40 hex digits with no 0x. The hashes are of the prefixed address.",
            {},
            edit_path("validators", 0, "fee_recipient_address", edit=lambda value: value[2:]),
        ),
        Case(
            "empty_withdrawal_address",
            "invalid_address",
            "A validator address is never absent. Charon hashes an empty address as the "
            "zero address, and the hashes here are computed that way.",
            addresses(withdrawal_address=ZERO_ADDRESS),
            set_path("validators", 0, "withdrawal_address", value=""),
        ),
        Case(
            "withdrawal_address_19_bytes",
            "invalid_address",
            "One byte short. The hashes are of the address left-padded to 20 bytes.",
            addresses(withdrawal_address="0x00" + WITHDRAWAL_ADDRESS.lower()[4:]),
            edit_path("validators", 0, "withdrawal_address", edit=drop_leading_byte),
        ),
        Case(
            "zero_withdrawal_address_on_mainnet",
            None,
            "The zero address is valid on mainnet too. Charon's create dkg refuses it as "
            "policy, but deployed mainnet clusters use it deliberately, so a reader must "
            "accept it.",
            {"fork_version": MAINNET, "validator_addresses": [zero_withdrawal]},
        ),
        Case(
            "zero_fee_recipient_on_mainnet",
            None,
            "A zero fee recipient on mainnet is valid as well.",
            {"fork_version": MAINNET, "validator_addresses": [zero_fee]},
        ),
        Case(
            "zero_withdrawal_address_on_gnosis",
            None,
            "And on Gnosis Chain (fork version 0x00000064).",
            {"fork_version": GNOSIS, "validator_addresses": [zero_withdrawal]},
        ),
        Case(
            "deposit_amount_below_1_eth",
            "deposit_amount_out_of_range",
            "999999999 Gwei, one Gwei under the minimum.",
            {"deposit_amounts": [1 * ETH - 1, 32 * ETH]},
        ),
        Case(
            "deposit_amount_above_32_eth_without_compounding",
            "deposit_amount_out_of_range",
            "32 ETH plus one Gwei with 0x01 credentials.",
            {"deposit_amounts": [32 * ETH + 1]},
        ),
        Case(
            "deposit_amount_above_2048_eth_with_compounding",
            "deposit_amount_out_of_range",
            "2048 ETH plus one Gwei with compounding set.",
            {"deposit_amounts": [2048 * ETH + 1], "compounding": True},
        ),
        Case(
            "fork_version_3_bytes",
            "invalid_length",
            "Charon left-pads a short fixed-size field, so the hashes are those of "
            "0x00 followed by these three bytes.",
            {"fork_version": b"\x00" + HOODI[1:]},
            edit_path("fork_version", edit=drop_leading_byte),
        ),
        Case(
            "operator_config_signature_64_bytes",
            "invalid_length",
            "A signature one byte short. The hashes are of it left-padded to 65 bytes, as "
            "Charon pads it.",
            signed_operators,
            edit_path("operators", 0, "config_signature", edit=drop_leading_byte),
        ),
    ]


def lock_cases(keys: Keys) -> List[Case]:
    """Cases over a full lock file."""
    standard = credentials(0x01, WITHDRAWAL_ADDRESS)
    compounding = {"compounding": True, "deposit_amounts": [32 * ETH, 2048 * ETH]}

    return [
        Case(
            "valid_lock",
            None,
            "The valid base lock: one validator with the bls_threshold.json sharing, one "
            "32 ETH deposit and a builder registration signed by the group key, a real "
            "signature aggregate and real node signatures.",
            LockRecipe(),
        ),
        Case(
            "default_deposit_amounts",
            None,
            "deposit_amounts is empty, so the deposits are Charon's defaults for 0x01 "
            "credentials: 1 ETH and 32 ETH.",
            LockRecipe(definition={"deposit_amounts": []}),
        ),
        Case(
            "compounding_deposits",
            None,
            "compounding is set, so the credentials take the 0x02 prefix and a single "
            "deposit may carry up to 2048 ETH.",
            LockRecipe(definition=compounding),
        ),
        Case(
            "default_compounding_deposit_amounts",
            None,
            "Compounding with empty deposit_amounts: Charon's defaults are 1, 8, 32 and 256 ETH.",
            LockRecipe(definition={"compounding": True, "deposit_amounts": []}),
        ),
        Case(
            "withdrawal_credentials_bare_address",
            "invalid_length",
            "The 20-byte withdrawal address with no prefix or padding. Left-padded, as "
            "Charon pads it, this becomes 0x00-prefixed (BLS) credentials; the lock hash "
            "and deposit signature are over that padded value, so every signature "
            "verifies for a reader that pads.",
            LockRecipe(deposit=set_deposit(withdrawal_credentials=bytes(12) + standard[12:])),
            edit_path(*DEPOSIT, "withdrawal_credentials", edit=lambda value: "0x" + value[26:]),
        ),
        Case(
            "withdrawal_credentials_31_bytes",
            "invalid_length",
            "The credentials without their prefix byte. Left-padding restores a 0x00 "
            "prefix, which is what the hashes and signatures are over.",
            LockRecipe(deposit=set_deposit(withdrawal_credentials=bytes(1) + standard[1:])),
            edit_path(*DEPOSIT, "withdrawal_credentials", edit=drop_leading_byte),
        ),
        Case(
            "withdrawal_credentials_33_bytes",
            "invalid_length",
            "Valid credentials with one byte appended. The hashes and signatures are of "
            "the valid 32 bytes, which is what a reader that truncates sees.",
            LockRecipe(),
            edit_path(*DEPOSIT, "withdrawal_credentials", edit=lambda value: value + "00"),
        ),
        Case(
            "withdrawal_credentials_0x00_prefix",
            "withdrawal_credentials_mismatch",
            "Correct length, BLS (0x00) prefix, signed as carried.",
            LockRecipe(
                deposit=set_deposit(withdrawal_credentials=credentials(0x00, WITHDRAWAL_ADDRESS))
            ),
        ),
        Case(
            "withdrawal_credentials_0x02_prefix_without_compounding",
            "withdrawal_credentials_mismatch",
            "0x02 credentials in a definition that does not set compounding.",
            LockRecipe(
                deposit=set_deposit(withdrawal_credentials=credentials(0x02, WITHDRAWAL_ADDRESS))
            ),
        ),
        Case(
            "withdrawal_credentials_0x01_prefix_with_compounding",
            "withdrawal_credentials_mismatch",
            "0x01 credentials in a compounding definition.",
            LockRecipe(
                definition=compounding,
                deposit=set_deposit(withdrawal_credentials=credentials(0x01, WITHDRAWAL_ADDRESS)),
            ),
        ),
        Case(
            "withdrawal_credentials_nonzero_padding",
            "withdrawal_credentials_mismatch",
            "Correct prefix and address with a non-zero byte in the eleven padding bytes.",
            LockRecipe(
                deposit=set_deposit(
                    withdrawal_credentials=credentials(
                        0x01, WITHDRAWAL_ADDRESS, bytes(10) + b"\x01"
                    )
                )
            ),
        ),
        Case(
            "withdrawal_credentials_for_another_address",
            "withdrawal_credentials_mismatch",
            "Well-formed credentials for an address the definition does not name.",
            LockRecipe(
                deposit=set_deposit(withdrawal_credentials=credentials(0x01, OTHER_ADDRESS))
            ),
        ),
        Case(
            "deposit_pubkey_is_not_the_group_key",
            "deposit_pubkey_mismatch",
            "The deposit names the first public share and is validly signed by that "
            "share's secret.",
            LockRecipe(
                deposit=set_deposit(pubkey=keys.pubshares[0]),
                deposit_signer=keys.share_secrets[0],
            ),
        ),
        Case(
            "deposit_amount_not_in_definition",
            "deposit_amount_not_in_definition",
            "A validly signed 16 ETH deposit against deposit_amounts of 32 ETH.",
            LockRecipe(deposit=set_deposit(amount=16 * ETH)),
        ),
        Case(
            "deposit_amount_not_in_default_amounts",
            "deposit_amount_not_in_definition",
            "deposit_amounts is empty, so only Charon's defaults are allowed; 16 ETH is "
            "not one of them.",
            LockRecipe(definition={"deposit_amounts": []}, deposit=set_deposit(amount=16 * ETH)),
        ),
        Case(
            "bad_deposit_signature",
            "invalid_deposit_signature",
            "The deposit carries 32 ETH but its signature is over the same message with 31 ETH.",
            LockRecipe(deposit_signed_as=set_deposit(amount=31 * ETH)),
        ),
        Case(
            "deposit_signed_for_another_network",
            "invalid_deposit_signature",
            "Signed with the mainnet deposit domain in a Hoodi cluster. The deposit domain "
            "is computed from the definition's fork_version.",
            LockRecipe(deposit_fork_version=MAINNET),
        ),
        Case(
            "deposit_signature_95_bytes",
            "invalid_length",
            "A BLS signature one byte short. The lock hash is over it left-padded, so "
            "the lock hash, aggregate and node signatures verify for a reader that pads; "
            "the padded deposit signature itself does not.",
            LockRecipe(deposit_signature=lambda signature: b"\x00" + signature[1:]),
            edit_path(*DEPOSIT, "signature", edit=lambda value: "0x" + value[4:]),
        ),
        Case(
            "pubshare_47_bytes",
            "invalid_length",
            "A public share one byte short. The lock hash is over it left-padded.",
            LockRecipe(pubshares=lambda shares: [b"\x00" + shares[0][1:], *shares[1:]]),
            edit_path("distributed_validators", 0, "public_shares", 0, edit=drop_leading_byte),
        ),
        Case(
            "registration_fee_recipient_19_bytes",
            "invalid_length",
            "Charon hashes this field right-padded, unlike every other fixed field, so "
            "the lock hash and registration signature are over the address with its last "
            "byte zeroed and the file carries it with that byte dropped.",
            LockRecipe(
                definition={
                    "validator_addresses": [
                        ValidatorAddresses(
                            fee_recipient_address=to_checksum_address(
                                decode_address(FEE_RECIPIENT)[:19] + b"\x00"
                            ),
                            withdrawal_address=WITHDRAWAL_ADDRESS,
                        )
                    ]
                }
            ),
            edit_path(*REGISTRATION, "message", "fee_recipient", edit=drop_trailing_byte),
        ),
        Case(
            "registration_fee_recipient_not_in_definition",
            "registration_fee_recipient_mismatch",
            "The registration names another fee recipient and is validly signed over it.",
            LockRecipe(registration={"fee_recipient": decode_address(OTHER_ADDRESS)}),
        ),
        Case(
            "registration_signed_for_definition_fee_recipient",
            "registration_fee_recipient_mismatch",
            "The registration names another fee recipient but its signature is over the "
            "definition's. Charon verifies the signature over a message rebuilt from the "
            "definition and accepts this; the spec compares the carried message first.",
            LockRecipe(
                registration={"fee_recipient": decode_address(OTHER_ADDRESS)},
                registration_signed_as={"fee_recipient": decode_address(FEE_RECIPIENT)},
            ),
        ),
        Case(
            "registration_pubkey_is_not_the_group_key",
            "registration_pubkey_mismatch",
            "The registration message names the first public share.",
            LockRecipe(registration={"pubkey": keys.pubshares[0]}),
        ),
        Case(
            "bad_registration_signature",
            "invalid_registration_signature",
            "The registration's signature is over a different gas limit.",
            LockRecipe(registration_signed_as={"gas_limit": GAS_LIMIT + 1}),
        ),
        Case(
            "bad_address_checksum_in_lock",
            "bad_address_checksum",
            "The address rules apply to the definition inside a lock too. Hashes and "
            "signatures are over the correctly spelled address.",
            LockRecipe(),
            edit_path(*LOCK_ADDRESSES, "withdrawal_address", edit=mis_checksum),
        ),
        Case(
            "zero_withdrawal_address_on_mainnet_lock",
            None,
            "A fully signed mainnet lock whose deposit credentials are derived from the "
            "zero withdrawal address. Valid: such locks exist on mainnet by design.",
            LockRecipe(
                definition={
                    "fork_version": MAINNET,
                    "validator_addresses": [
                        ValidatorAddresses(
                            fee_recipient_address=FEE_RECIPIENT, withdrawal_address=ZERO_ADDRESS
                        )
                    ],
                }
            ),
        ),
    ]


def require_verdict(name: str, got: Tuple[bool, Optional[str]], reason: Optional[str]) -> None:
    """VectorGenerationError unless the spec's verdict is the one the case was built for."""
    if got != (reason is None, reason):
        raise VectorGenerationError(f"{name}: spec says {got}, the case was built for {reason}")


def check_recipe_credentials(keys: Keys) -> None:
    """Confirm the base lock's credentials are the ones the spec derives.

    The recipes derive credentials without validation so that a case can carry
    an address the strict rules reject. This pins that the shortcut agrees with
    `withdrawal_credentials` on a valid address.
    """
    lock = build_lock(keys, LockRecipe())
    expected = withdrawal_credentials(WITHDRAWAL_ADDRESS, compounding=False)
    if lock.validators[0].partial_deposit_data[0].withdrawal_credentials != expected:
        raise VectorGenerationError("recipe credentials disagree with the spec's derivation")


def cluster_validation(charon_ref: str) -> Dict[str, Any]:
    """Build the suite, failing if the spec's verdict differs from any case's."""
    keys = load_keys()
    check_recipe_credentials(keys)

    definitions = []
    for case in definition_cases():
        definition = with_hashes(base_definition(keys, **case.recipe))
        data = to_json(definition, case.patch)
        require_verdict(case.name, verdict_of_definition(data), case.reason)
        definitions.append(
            {
                "name": case.name,
                "input": data,
                "accepted": case.reason is None,
                "reason": case.reason,
                "notes": case.notes,
            }
        )

    locks = []
    node_pubkeys = [pubkey.hex() for pubkey in keys.node_pubkeys]
    for case in lock_cases(keys):
        data = to_json(build_lock(keys, case.recipe), case.patch)
        require_verdict(case.name, verdict_of_lock(data, keys.node_pubkeys), case.reason)
        locks.append(
            {
                "name": case.name,
                "input": data,
                "node_pubkeys": node_pubkeys,
                "accepted": case.reason is None,
                "reason": case.reason,
                "notes": case.notes,
            }
        )

    return {
        "suite": "cluster_validation",
        "description": (
            "Which v1.10.0 cluster definitions and locks a reader MUST accept or reject. "
            "A definition is accepted if it parses under the field rules (fixed lengths, "
            "addresses, deposit amount bounds and sum) "
            "and its stored hashes match. A lock is accepted if it parses and passes the "
            "full verification sequence: hashes, public shares, deposit data, builder "
            "registrations, signature aggregate, node signatures (against node_pubkeys). "
            "Every rejected case breaks exactly one rule and is otherwise fully valid; "
            "length and address cases are hashed and signed over the value a lenient "
            "reader would decode (short fields left-padded as Charon pads them, the "
            "registration fee recipient right-padded, long fields truncated, addresses "
            "case-insensitive), so a reader that pads instead of rejecting finds every "
            "hash and signature valid."
        ),
        "provenance": {
            "source": "spec",
            "charon_ref": charon_ref,
            "generated_by": "scripts/generate_test_vectors.py",
            "note": (
                "Built by this spec: the rules are stricter than charon at this ref, which "
                "parses most rejected cases (and verifies their hashes and signatures) "
                "without complaint. Keys are reused from bls_threshold.json and the "
                "real_keys_3_of_4 lock in cluster_hashing.json. This script fails if the "
                "spec's verdict or reason differs from the one a case was built for."
            ),
        },
        "definition": definitions,
        "lock": locks,
    }
