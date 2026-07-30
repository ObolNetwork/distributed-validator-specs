"""The cluster definition: a cluster's intended configuration.

A definition is what the operators of a prospective cluster agree on *before*
any keys exist. It is created by one operator, signed by all of them, and is the
input to the DKG ceremony. `docs/dv-spec/cluster-files.md` describes the file and
the workflow around it; this module is the data model, and `hashing.py` derives
the two hashes the signatures cover.

Only version v1.10.0 is modelled. Charon still reads every version back to
v1.0.0, each with its own hash function and in some cases its own JSON shape, but
a spec that reproduced all of them would document Charon's history rather than
the protocol. See `hashing.py` for what changed at v1.10 and v1.11.

A `cluster-definition.json` written by `charon create dkg` parses into these
models unchanged, and every field default is Go's zero value, so a key absent
from a file parses — and therefore hashes — exactly as Charon parses it. Two
encoding quirks are Charon's and are reproduced deliberately:

- Ethereum addresses stay hex *strings*, and are decoded only inside the hash
  function. Nothing compares them as text, so case is not significant.
- Deposit amounts are JSON strings, not numbers, because Charon types them as
  `phase0.Gwei`.

Serialization is not byte-identical to Go's: these models write `[]` where Go
writes `null` for a nil slice, and keep empty string fields that Go's
`omitempty` drops. Both forms parse to the same model and hash on either side.

Scope
-----
- The v1.10.0 definition and its members, and their JSON form.

Out of scope
------------
- EIP-712 signature construction over the config hash. The definition's
  signatures authorise operators and are verified by Charon before a DKG, but
  they are an Ethereum-signing concern rather than a DV wire format.
- Address checksums, ENR decoding, and the deposit-amount sum rules.
"""

from __future__ import annotations

from typing import Annotated, Any, List

from pydantic import BeforeValidator, Field, PlainSerializer, field_validator, model_validator

from dv_spec.types.base import StrictBaseModel
from dv_spec.types.hex import HexBytes
from dv_spec.types.uint64 import UINT64_MAX


def empty_list_if_null(value: Any) -> Any:
    """Turn a JSON null into an empty list, leaving anything else alone.

    Go marshals a nil slice as `null` rather than `[]`, so any empty list in a
    cluster file Charon wrote arrives as null. The two are indistinguishable in
    the hash — both mix in a length of zero — so they must parse the same.
    """
    return [] if value is None else value


NullableList = BeforeValidator(empty_list_if_null)
"""Annotation accepting JSON null for a list field. See `empty_list_if_null`."""

GoInt = Annotated[int, Field(ge=0, le=2**63 - 1)]
"""A numeric field Charon types as a signed 64-bit Go `int`.

The upper bound is Go's: a larger JSON number fails Charon's parse outright.
The lower bound is this spec's one deliberate strictness: Charon accepts a
negative value and hashes its two's-complement wrapping (`uint64(v)` in
`cluster/ssz.go`), which this spec rejects at validation rather than reproduces.
"""

Gwei = Annotated[
    int,
    Field(ge=0, le=UINT64_MAX),
    PlainSerializer(str, return_type=str, when_used="json"),
]
"""An amount in Gwei — a `uint64` written as a JSON string.

Charon marshals these as strings (`phase0.Gwei` and `json:"amount,string"`)
because a 64-bit amount overflows a JSON reader that parses numbers as doubles.
Read accepts both forms; write always produces the string, which is also the
only form Charon's own parser accepts.
"""

VERSION_V1X10 = "v1.10.0"
"""The definition version this spec models."""

SUPPORTED_VERSIONS = (VERSION_V1X10,)
"""Versions this spec hashes. Charon additionally hashes v1.0.0 through v1.11.0."""


def require_supported_version(version: str) -> None:
    """Reject a version this spec does not model.

    Raises:
        ValueError: If `version` is not in `SUPPORTED_VERSIONS`.
    """
    if version not in SUPPORTED_VERSIONS:
        supported = ", ".join(SUPPORTED_VERSIONS)
        raise ValueError(f"unsupported cluster version {version!r}, this spec models {supported}")


MAX_UUID_BYTES = 64
"""SSZ byte-list capacity of `uuid`."""

MAX_NAME_BYTES = 256
"""SSZ byte-list capacity of `name`, and of `consensus_protocol`."""

MAX_VERSION_BYTES = 16
"""SSZ byte-list capacity of `version`."""

MAX_TIMESTAMP_BYTES = 32
"""SSZ byte-list capacity of `timestamp`."""

MAX_DKG_ALGORITHM_BYTES = 32
"""SSZ byte-list capacity of `dkg_algorithm`."""

MAX_ENR_BYTES = 1024
"""SSZ byte-list capacity of an operator's `enr`."""

MAX_OPERATORS = 256
"""SSZ list capacity of `operators`, and of a validator's public shares."""

MAX_VALIDATORS = 65536
"""SSZ list capacity of `validators`, and of a lock's distributed validators."""

MAX_DEPOSIT_AMOUNTS = 256
"""SSZ list capacity of `deposit_amounts`, and of partial deposit data."""

ADDRESS_LENGTH = 20
"""Length of an Ethereum address, once its hex string is decoded."""

FORK_VERSION_LENGTH = 4
"""Length of the beacon chain fork version."""

K1_SIGNATURE_LENGTH = 65
"""Length of a secp256k1 `R || S || V` signature."""

HASH_LENGTH = 32
"""Length of a config, definition or lock hash."""


class Operator(StrictBaseModel):
    """A charon node in the cluster and the operator that runs it."""

    address: str = Field(
        description=("The operator's 20-byte Ethereum address, as a 0x-prefixed hex string"),
    )
    enr: str = Field(
        default="",
        description="ENR identifying the charon node, at most 1024 characters",
    )
    config_signature: HexBytes = Field(
        default=b"",
        description=("EIP-712 signature of the config hash by `address`, 65 bytes at v1.10"),
    )
    enr_signature: HexBytes = Field(
        default=b"",
        description=(
            "EIP-712 signature of the ENR by `address`, authorising the node to "
            "act for the operator. 65 bytes at v1.10"
        ),
    )


class Creator(StrictBaseModel):
    """The operator that created the definition. May also be an operator."""

    address: str = Field(
        description="The creator's 20-byte Ethereum address, as a 0x-prefixed hex string",
    )
    config_signature: HexBytes = Field(
        default=b"",
        description="EIP-712 signature of the config hash by `address`, 65 bytes at v1.10",
    )


class ValidatorAddresses(StrictBaseModel):
    """The fee recipient and withdrawal addresses of one validator."""

    fee_recipient_address: str = Field(
        description="20-byte Ethereum address to receive execution layer rewards",
    )
    withdrawal_address: str = Field(
        description="20-byte Ethereum address to receive withdrawals",
    )


class Definition(StrictBaseModel, populate_by_name=True, serialize_by_alias=True):
    """A cluster's intended configuration, at version v1.10.0.

    The field order below is the order the hash functions walk, which is also
    the `config_hash`/`definition_hash` struct-tag order in Charon. It is not
    the order Charon's JSON writer emits, and JSON key order is not significant.

    `populate_by_name` accepts both Charon's JSON key names and the field names
    used in code, since `validators` reads naturally in a file but ambiguously
    beside a lock's own validators. `serialize_by_alias` makes a plain
    `model_dump_json()` write the key names Charon reads.
    """

    uuid: str = Field(description="Random unique identifier, at most 64 bytes of UTF-8")
    name: str = Field(default="", description="Cosmetic cluster name, at most 256 bytes of UTF-8")
    version: str = Field(description="Definition schema version; only v1.10.0 is supported")
    timestamp: str = Field(
        default="",
        description="RFC 3339 creation timestamp, at most 32 bytes",
    )
    num_validators: GoInt = Field(
        description="Number of distributed validators the cluster will create",
    )
    threshold: GoInt = Field(
        description="Partial signatures required to reconstruct a group signature",
    )
    dkg_algorithm: str = Field(
        default="",
        description="DKG algorithm to run; Charon writes 'default', which selects FROST",
    )
    fork_version: HexBytes = Field(
        description="The 4-byte beacon chain fork version, identifying the network",
    )
    operators: Annotated[List[Operator], NullableList] = Field(
        default_factory=list,
        description="The cluster's nodes, in the order that fixes each node's index",
    )
    creator: Creator = Field(description="The operator that created this definition")
    validator_addresses: Annotated[List[ValidatorAddresses], NullableList] = Field(
        default_factory=list,
        alias="validators",
        description="Per-validator fee recipient and withdrawal addresses",
    )
    deposit_amounts: Annotated[List[Gwei], NullableList] = Field(
        default_factory=list,
        description=(
            "Partial deposit amounts in Gwei, written as JSON strings. Empty "
            "means a single full deposit"
        ),
    )
    consensus_protocol: str = Field(
        default="",
        description="Preferred consensus protocol name, for example 'abft'. Empty means default",
    )
    target_gas_limit: GoInt = Field(
        default=0,
        description="Target block gas limit advertised in builder registrations",
    )
    compounding: bool = Field(
        default=False,
        description="Whether validators use 0x02 compounding withdrawal credentials",
    )
    config_hash: HexBytes = Field(
        default=b"",
        description=(
            "Hash of the configuration excluding operator ENRs and signatures. "
            "Operators sign this, so it must be stable while signatures are collected"
        ),
    )
    definition_hash: HexBytes = Field(
        default=b"",
        description="Hash of the whole definition, including ENRs and signatures",
    )

    @field_validator("version")
    @classmethod
    def _version_must_be_supported(cls, value: str) -> str:
        """Reject other versions at parse, before defaults masquerade as content.

        A v1.9 file's key set is a subset of v1.10's, so without this it would
        validate cleanly and report fields the file does not have.
        """
        require_supported_version(value)

        return value

    @model_validator(mode="after")
    def _num_validators_must_match(self) -> Definition:
        """Reject a `num_validators` that disagrees with the address list.

        Charon rejects such a file when loading it, so a spec that accepted it
        would hash files no other implementation ever sees.
        """
        if self.num_validators != len(self.validator_addresses):
            raise ValueError(
                f"num_validators is {self.num_validators} but the file has "
                f"{len(self.validator_addresses)} validator address entries"
            )

        return self

    @property
    def num_operators(self) -> int:
        """Number of nodes in the cluster, which is also the number of shares."""
        return len(self.operators)
