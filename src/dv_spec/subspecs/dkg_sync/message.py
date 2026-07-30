"""DKG Synchronization Protocol specification models.

This module defines the message shapes and constants for the DKG sync protocol
used to coordinate distributed key generation ceremonies between multiple nodes.

Scope
-----
- Message data models mirror the protobuf schema used on the wire.
- Constants capture protocol identifiers used on libp2p.
- The sync protocol ensures connectivity verification, configuration consistency,
  step synchronization, and graceful shutdown coordination.

Out of scope
------------
- Transport implementation, connection management, and state machines. These are
  implementation details documented in the spec docs.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from dv_spec.types.base import StrictBaseModel

# ----------------------------
# Protocol identifier (libp2p)
# ----------------------------

DKG_SYNC_PROTOCOL_ID = "/charon/dkg/sync/1.0.0/"
"""Protocol ID for libp2p stream handling.

The sync protocol uses a single long-lived bidirectional stream per peer pair.
Servers register this protocol ID to accept incoming sync connections.
"""


# ----------------------------
# Message models (wire schema)
# ----------------------------


class MsgSync(StrictBaseModel):
    """Sync message sent periodically by clients to servers.

    Clients send this message approximately once per second to maintain
    connectivity, report their current step, and signal shutdown when complete.
    """

    timestamp: datetime = Field(
        description=(
            "Client's current wall clock time. Used by the server to calculate "
            "round-trip time (RTT) and detect stale connections."
        )
    )

    hash_signature: bytes = Field(
        description=(
            "Signature over the cluster definition hash, signed with the node's "
            "libp2p private key. Proves the client is part of the agreed cluster "
            "configuration. Note: libp2p signature verification performs an additional "
            "hash of the definition hash internally."
        )
    )

    shutdown: bool = Field(
        default=False,
        description=(
            "Graceful shutdown flag. When True, the client signals it has completed "
            "the ceremony and is shutting down. The server marks this client as shutdown "
            "and waits for all clients to shutdown before completing."
        ),
    )

    version: str = Field(
        description=(
            "Semantic version string of the DV client (e.g., '1.0.0'). Servers reject "
            "connections from clients with incompatible versions to ensure protocol "
            "consistency. DKG compatibility requires matching minor version."
        )
    )

    step: int = Field(
        ge=0,
        description=(
            "Current phase/step number the client has reached in the ceremony. "
            "Servers track all client steps and implement barrier synchronization: "
            "only when all clients reach the same step does the ceremony progress. "
            "Steps are numbered 0, 1, 2, ... and must progress monotonically."
        ),
    )

    nickname: str = Field(
        default="",
        max_length=32,
        description=(
            "Optional human-friendly peer nickname, displayed to other operators "
            "during the ceremony (e.g., in server logs). Maximum 32 characters "
            "(enforced by senders). Empty string when no nickname is configured. "
            "Purely informational; MUST NOT affect protocol behavior."
        ),
    )


class MsgSyncResponse(StrictBaseModel):
    """Response message sent by servers back to clients.

    Servers respond to each MsgSync with this message, echoing the timestamp
    for RTT calculation and optionally reporting validation errors.
    """

    sync_timestamp: datetime = Field(
        description=(
            "Echoes the timestamp from the MsgSync request. Clients use this to "
            "calculate round-trip time: RTT = now() - sync_timestamp. The measured "
            "RTT is recorded in the peer latency store for connection quality metrics."
        )
    )

    error: str = Field(
        default="",
        description=(
            "Human-readable error message if the sync message was rejected. "
            "Common errors include version mismatch, invalid definition hash signature, "
            "or incorrect cluster configuration. Empty string indicates success."
        ),
    )
