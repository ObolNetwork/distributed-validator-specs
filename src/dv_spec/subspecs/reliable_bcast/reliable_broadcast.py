"""Reliable broadcast (two-phase signed broadcast) models and helpers.

The component provides equivocation resistance for a single message per ID by
collecting signatures from all peers over the hash of the message and sending a
single broadcast with the aggregated signatures.

- Phase 1 (signature collection): requester sends BCastSigRequest with an Any-
  like payload and collects BCastSigResponse from each peer. Peers enforce a
  single hash per (requester, message_id) to prevent equivocation.
- Phase 2 (broadcast): requester sends BCastMessage with the same Any payload
  plus the collected signatures; receivers verify all signatures and deliver
  the payload to the application.

This module is transport-agnostic and only defines data models and hashing
rules for the payload.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from pydantic import BaseModel, Field


class AnyMessage(BaseModel):
    """Minimal "Any" envelope.

    This is not Protobuf Any; it just captures the two fields relevant for
    hashing/signing discipline and interop.
    """

    type_url: str = Field(description="Fully qualified type URL/name of the embedded message")
    value: bytes = Field(description="Binary serialization of the embedded message")


def compute_any_hash(any_msg: AnyMessage) -> bytes:
    """Compute the hash of an AnyMessage as SHA256(type_url || value).

    This mirrors the hashing convention used by Charon's bcast component.
    """
    return sha256(any_msg.type_url.encode("utf-8") + any_msg.value).digest()


class BCastSigRequest(BaseModel):
    """Phase-1 signature request sent by the requester to all peers."""

    message_id: str = Field(description="Logical identifier (e.g., 'node_pubkeys')")
    message: AnyMessage = Field(description="Payload to be signed")


class BCastSigResponse(BaseModel):
    """Phase-1 signature response sent by each peer."""

    signature: bytes = Field(
        description="65-byte secp256k1 signature (R||S||V) over the payload hash"
    )


class BCastMessage(BaseModel):
    """Phase-2 broadcast message sent by the requester to all peers."""

    message_id: str = Field(description="Logical identifier (e.g., 'node_pubkeys')")
    message: AnyMessage = Field(description="Payload that was signed in phase 1")
    signatures: list[bytes] = Field(
        default_factory=list,
        description="Signatures collected from all peers in canonical order",
    )


@dataclass
class EquivocationGuardKey:
    """Key used by peers to enforce at-most-one-hash per (requester, message_id)."""

    requester_peer_id: str
    message_id: str
