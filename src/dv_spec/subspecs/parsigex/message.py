"""Partial signature exchange protocol message models.

The ParSigEx component exchanges partially signed validator duty data among
distributed validator nodes. Each node broadcasts its partial signatures to
all peers, who verify and store them. Once threshold signatures are collected,
they can be aggregated into a full signature.

This module is transport-agnostic and only defines data models for the over-
the-wire message structures.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from dv_spec.types.duty import Duty


class ParSignedData(BaseModel):
    """A partially signed duty data item from one operator.

    Contains a signature share and the share index identifying which
    operator produced it.
    """

    data: bytes = Field(
        description="Serialized SignedData (duty-type specific, e.g., attestation, block proposal)"
    )
    signature: bytes = Field(description="BLS signature share (96 bytes, compressed G2 point)")
    share_idx: int = Field(ge=0, description="Operator index (0-based in protocol)")


class ParSignedDataSet(BaseModel):
    """A set of partial signatures keyed by validator public key.

    Typically contains one ParSignedData per validator that the
    node is responsible for signing.
    """

    set: dict[str, ParSignedData] = Field(
        default_factory=dict,
        description="Mapping from validator public key (hex or bytes) to partial signature",
    )


class ParSigExMsg(BaseModel):
    """Partial signature exchange message.

    Broadcast by each node to all peers containing partial signatures
    for one or more validators for a given duty.
    """

    duty: Duty = Field(description="The validator duty being performed")
    data_set: ParSignedDataSet = Field(
        description="Set of partial signatures, one per validator pubkey"
    )
