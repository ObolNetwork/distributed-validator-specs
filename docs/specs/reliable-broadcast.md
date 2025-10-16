## Reliable Broadcast (two-phase signed broadcast)

This document specifies a generic, transport-agnostic signed broadcast component intended to prevent equivocation for a single message per logical ID.

Applicability

- Use this component whenever a group must agree on a single, invariant payload before proceeding (e.g., Pedersen DKG `node_pubkeys`). It is heavier than direct p2p fan-out, so limit usage to agreement-critical messages.

Model

- Participants: a known set of N peers, each identified by a unique peer ID and possessing an ENR-based secp256k1 identity.
- Cryptography: each peer signs over a SHA256 hash of an Any-like envelope (type_url || value) using secp256k1, producing a 65-byte R||S||V signature.
- Equivocation guard: each peer enforces at-most-one-hash per (requester_peer_id, message_id). On a second signing request with a different hash, the peer rejects it.

Data structures

- AnyMessage
  - type_url: string
  - value: bytes
  - Hash: SHA256(type_url || value)
- BCastSigRequest
  - message_id: string
  - message: AnyMessage
- BCastSigResponse
  - signature: bytes // 65-byte secp256k1 signature over Hash
- BCastMessage
  - message_id: string
  - message: AnyMessage
  - signatures: repeated bytes // one signature per peer, ordered canonically

Protocol

1) Signature collection
- Requester sends BCastSigRequest(message_id, message) to all peers.
- Each peer computes Hash, checks its EquivocationGuardKey = (requester_peer_id, message_id):
  - If no prior entry, stores Hash and returns signature over Hash.
  - If prior entry exists with same Hash, returns signature again (idempotent).
  - If prior entry exists with different Hash, rejects the request (equivocation attempt).

2) Broadcast
- After collecting signatures from all peers, requester sends BCastMessage(message_id, message, signatures) to all peers.
- Receivers verify:
  - The signatures list length and ordering matches the canonical peer order.
  - Each signature validates over Hash for the corresponding peer.
  - message_id/type_url are expected for the application context.
- If valid, the application’s handler is invoked with the embedded message.

Properties

- Anti-equivocation: A requester cannot convince different peers to accept different payloads under the same message_id; peers sign only one hash per (requester,message_id).
- Group attestation: Receivers accept only payloads that carry N valid signatures (or the configured quorum) corresponding to the known peer set.
- Idempotence: Replaying the same Hash yields the same signatures; duplicates are harmless.

Interop notes

- Hashing discipline is critical: use exactly SHA256(type_url || value) bytes.
- The type_url should uniquely identify the embedded message schema (e.g., a Protobuf URL or stable string).
- Canonical order must be shared across peers (e.g., lock/operator order) to align signature ordering.

References

- Python reference models: `dv_spec.subspecs.bcast`
- DKG usage: `docs/specs/pedersen-dkg.md` (node_pubkeys step)
