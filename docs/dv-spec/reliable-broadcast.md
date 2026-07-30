# Reliable Broadcast (Two-Phase Signed Broadcast)

This document specifies a generic, transport-agnostic signed broadcast component intended to prevent equivocation for a single message per logical ID. Use this component whenever a group must agree on a single, invariant payload before proceeding (e.g., Pedersen DKG `node_pubkeys`). It is heavier than direct p2p fan-out, so limit usage to agreement-critical messages.

Scope:

- Over-the-wire message structures for two-phase broadcast
- Signature collection and verification flows
- Equivocation prevention mechanisms
- Hashing and canonical ordering requirements

Out of scope: application-specific message types, peer discovery, transport reliability, secp256k1 cryptographic primitives.

## Terms and Notation

- `N`: number of peers in the group
- `message_id`: logical identifier for the broadcast (e.g., "node_pubkeys")
- `type_url`: fully qualified type identifier for the embedded message
- `Hash`: SHA256(type_url || value) computed over the Any-like envelope
- `EquivocationGuardKey`: per-peer deduplication key (requester_peer_id, message_id)
- `Canonical order`: agreed-upon peer ordering (e.g., from cluster lock file)

## Protocol Identifiers (libp2p)

All messages are sent under protocol ID prefix:

```
/charon/dkg/bcast/1.0.0
```

The following message topics are appended to the prefix when routing on libp2p:

- `/sig` - signature request/response (phase 1)
- `/msg` - broadcast message delivery (phase 2)

## Message Schemas

The following protobuf definitions are used over the wire:

- [bcast.proto](https://github.com/ObolNetwork/distributed-validator-specs/blob/main/proto/bcast.proto) - Reliable broadcast message definitions

See the Python reference implementation: [`AnyMessage`, `BCastSigRequest`, `BCastSigResponse`, and `BCastMessage`](https://github.com/ObolNetwork/distributed-validator-specs/blob/main/src/dv_spec/subspecs/reliable_bcast/reliable_broadcast.py).

> **Naming note**: This component lives in Charon at `dkg/bcast` and its
> protocol ID is `/charon/dkg/bcast/1.0.0`. It is **not** the same component
> as Charon's `core/bcast`, which broadcasts fully-signed duties to the beacon
> node — see [Beacon Broadcast](broadcast.md). This spec uses the module name
> `reliable_bcast` to avoid that collision.

## Protocol Flow

The reliable broadcast protocol operates in two phases:

### Phase 1: Signature Collection

- Requester sends `BCastSigRequest(message_id, message)` to all other peers (excluding itself)
- Requester computes its own signature locally over the same hash
- Each peer computes `Hash = SHA256(type_url || value)` and checks its `EquivocationGuardKey = (requester_peer_id, message_id)`:
  - If no prior entry exists: stores `Hash` and returns signature over `Hash`
  - If prior entry exists with same `Hash`: returns signature again (idempotent)
  - If prior entry exists with different `Hash`: rejects the request (equivocation attempt detected)

### Phase 2: Broadcast

- After collecting signatures from all peers (including its own), requester sends `BCastMessage(message_id, message, signatures)` to all other peers (excluding itself)
- Receivers verify:
  - The signatures list length and ordering matches the canonical peer order
  - Each signature validates over `Hash` for the corresponding peer
  - `message_id` and `type_url` are expected for the application context
- If valid, the application's handler is invoked with the embedded message

## Verification

**Equivocation prevention:**

Each peer enforces at-most-one-hash per `(requester_peer_id, message_id)`. Each peer maintains a deduplication map and rejects any second signing request with a different hash under the same key.

**Signature verification:**

All `N` signatures must be valid secp256k1 signatures over the same `Hash`. Peers use ENR-based public keys to verify each signature in the canonical peer order.

**Canonical ordering:**

The signatures array must match the agreed-upon peer ordering (typically from the cluster lock file). Mismatched ordering causes verification failure.

## Properties

- Anti-equivocation: A requester cannot convince different peers to accept different payloads under the same message_id; peers sign only one hash per (requester,message_id).
- Group attestation: Receivers accept only payloads that carry all N valid signatures corresponding to the known peer set.
- Idempotence: Replaying the same Hash yields the same signatures; duplicates are harmless.

## Interop Notes

- **Hashing consistency** is critical: use exactly SHA256(type_url || value) bytes.
- The **type_url** should uniquely identify the embedded message schema (e.g., a Protobuf URL or stable string).
- **Canonical order** must be shared across peers (e.g., lock/operator order) to align signature ordering.
- **Timeouts**: Receiving peer uses 1-minute receive timeout; broadcasting peer uses 62-second send timeout (allows receiver to timeout first).
- **Deduplication**: Per (requester_peer_id, message_id) pair - prevents equivocation but allows the same requester to use different message_ids.
