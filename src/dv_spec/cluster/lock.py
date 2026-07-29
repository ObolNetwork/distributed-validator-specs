"""The cluster lock: a definition plus the keys a DKG produced for it.

A lock is the output of a DKG ceremony and the file every node loads at startup.
It extends the definition with one entry per distributed validator — the group
public key, the public share of each node, the deposit data and the pre-generated
builder registration — and is attested to twice over:

- `signature_aggregate` is a *plain* BLS aggregate (not a threshold aggregate) of
  the lock hash signed by every private key share of every validator. It proves
  the DKG participants all reached the same lock.
- `node_signatures` holds one secp256k1 signature of the lock hash per operator,
  made by the charon node key in that operator's ENR.

Neither signature is covered by the lock hash, which spans only the definition
and the validators. See `hashing.py`.

Scope
-----
- The v1.10.0 lock and its members, and their JSON form.

Out of scope
------------
- ENR decoding, so verifying `node_signatures` needs each node's public key
  supplied separately.
- Deposit message signing roots, which are beacon chain domain-separated and
  specified upstream.
"""

from __future__ import annotations

from typing import Annotated, List

from pydantic import Field

from dv_spec.cluster.definition import Definition, GoInt, Gwei, NullableList
from dv_spec.types.base import StrictBaseModel
from dv_spec.types.hex import HexBytes

PUBKEY_LENGTH = 48
"""Length of a compressed BLS12-381 G1 public key."""

BLS_SIGNATURE_LENGTH = 96
"""Length of a compressed BLS12-381 G2 signature."""

WITHDRAWAL_CREDENTIALS_LENGTH = 32
"""Length of the withdrawal credentials in deposit data."""


class DepositData(StrictBaseModel):
    """A signed deposit of one amount towards a validator.

    A validator may be funded by several partial deposits, which is why a lock
    carries a list of these per validator rather than one.
    """

    pubkey: HexBytes = Field(description="The distributed validator's group public key")
    withdrawal_credentials: HexBytes = Field(
        description="32-byte withdrawal credentials included in the deposit",
    )
    amount: Gwei = Field(description="Amount in Gwei, written as a JSON string")
    signature: HexBytes = Field(
        description="BLS signature of the deposit message by the group key",
    )


class Registration(StrictBaseModel):
    """An unsigned builder registration message."""

    fee_recipient: HexBytes = Field(description="20-byte fee recipient address")
    gas_limit: GoInt = Field(description="Gas limit advertised to builders")
    timestamp: GoInt = Field(description="Registration time as a unix timestamp in seconds")
    pubkey: HexBytes = Field(description="The distributed validator's group public key")


class BuilderRegistration(StrictBaseModel):
    """A builder registration pre-generated at DKG time and signed by the group key.

    Pre-generating it means a cluster can register with the builder network
    without first running a consensus round.
    """

    message: Registration = Field(description="The registration being signed")
    signature: HexBytes = Field(description="BLS signature of the message by the group key")


class DistValidator(StrictBaseModel, populate_by_name=True, serialize_by_alias=True):
    """One distributed validator produced by the DKG.

    `populate_by_name` accepts both Charon's JSON key names and the shorter field
    names used in code; `serialize_by_alias` makes a plain `model_dump_json()`
    write the key names Charon reads.
    """

    pubkey: HexBytes = Field(
        alias="distributed_public_key",
        description="The validator's group public key, 48 bytes",
    )
    pubshares: Annotated[List[HexBytes], NullableList] = Field(
        default_factory=list,
        alias="public_shares",
        description=(
            "Public key of each node's secret share, in node order. Used to "
            "verify partial signatures. There must be one per operator"
        ),
    )
    partial_deposit_data: Annotated[List[DepositData], NullableList] = Field(
        default_factory=list,
        description="Deposits funding this validator, in the definition's amount order",
    )
    builder_registration: BuilderRegistration = Field(
        description="The pre-generated signed builder registration",
    )


class Lock(StrictBaseModel, populate_by_name=True, serialize_by_alias=True):
    """A cluster lock at version v1.10.0.

    `populate_by_name` accepts both Charon's JSON key names and the shorter field
    names used in code; `serialize_by_alias` makes a plain `model_dump_json()`
    write the key names Charon reads.
    """

    definition: Definition = Field(
        alias="cluster_definition",
        description="The definition this cluster was created from",
    )
    validators: Annotated[List[DistValidator], NullableList] = Field(
        default_factory=list,
        alias="distributed_validators",
        description="The distributed validators the DKG produced",
    )
    lock_hash: HexBytes = Field(
        default=b"",
        description="Hash of the definition and the validators; see `hashing.py`",
    )
    signature_aggregate: HexBytes = Field(
        default=b"",
        description=(
            "Plain BLS aggregate of the lock hash signed by every private share of every validator"
        ),
    )
    node_signatures: Annotated[List[HexBytes], NullableList] = Field(
        default_factory=list,
        description=(
            "One 65-byte secp256k1 signature of the lock hash per operator, by "
            "the node key in that operator's ENR"
        ),
    )

    @property
    def version(self) -> str:
        """The definition's version, which also selects the lock hash function."""
        return self.definition.version

    @property
    def threshold(self) -> int:
        """The definition's signing threshold."""
        return self.definition.threshold
