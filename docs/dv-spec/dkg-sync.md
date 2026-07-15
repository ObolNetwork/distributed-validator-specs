# DKG Synchronization Protocol

This document describes the synchronization protocol used to coordinate distributed key generation (DKG) ceremonies between multiple nodes. The sync protocol ensures robust network connectivity, verifies cluster configuration consistency, and synchronizes multi-step cryptographic ceremonies.

Scope:

- Over-the-wire message shapes and fields
- Protocol identifiers, connection establishment, and step synchronization
- Barrier synchronization mechanics and shutdown coordination

Out of scope: Transport implementation details, connection retry logic, state machine internals

## Purpose

During a DKG ceremony, nodes must progress through multiple phases. The sync protocol provides:

1. **Connectivity Verification**: Ensure all participants are reachable before starting
2. **Configuration Consistency**: Verify all nodes agree on cluster definition
3. **Step Synchronization**: Coordinate phase transitions across all nodes
4. **Graceful Shutdown**: Ensure all nodes complete cleanly

## Terms and Notation

- `n`: number of participating nodes in the ceremony
- `Definition Hash`: a 32-byte hash of the cluster configuration shared by all nodes
- `Step`: integer phase counter (0, 1, 2, ...) tracking ceremony progression
- `RTT`: round-trip time measured from sync message exchanges

## Protocol Overview

The sync protocol wraps the entire DKG ceremony, providing barriers between each phase:

```
┌───────────────────────────────────────────────────────┐
│              DKG Synchronization Protocol             │
│                                                       │
│  ┌─────────────────────────────────────────────────┐  │
│  │ Phase 0: Connection Establishment               │  │
│  │  • All nodes connect to all other nodes         │  │
│  │  • Verify definition hash signatures            │  │
│  │  • Check version compatibility                  │  │
│  │  • Wait for full N×(N-1) connectivity           │  │
│  └─────────────────────────────────────────────────┘  │
│                        ↓                              │
│              ═══ Barrier Sync ═══                     │
│                        ↓                              │
│  ┌─────────────────────────────────────────────────┐  │
│  │ Phase 1: Cryptographic DKG                      │  │
│  │  ┌────────────────────────────────────────┐     │  │
│  │  │  Pedersen/FROST DKG Protocol           │     │  │
│  │  │  → Produces threshold key shares       │     │  │
│  │  └────────────────────────────────────────┘     │  │
│  └─────────────────────────────────────────────────┘  │
│                        ↓                              │
│              ═══ Barrier Sync ═══                     │
│                        ↓                              │
│  ┌─────────────────────────────────────────────────┐  │
│  │ Phase 2: Validator Setup                        │  │
│  │  • Derive validator public keys                 │  │
│  │  • Create & sign deposit data                   │  │
│  │  • Create & sign builder registrations          │  │
│  └─────────────────────────────────────────────────┘  │
│                        ↓                              │
│              ═══ Barrier Sync ═══                     │
│                        ↓                              │
│  ┌─────────────────────────────────────────────────┐  │
│  │ Phase 3: Lock File Creation                     │  │
│  │  • Aggregate all ceremony outputs               │  │
│  │  • Create cluster lock structure                │  │
│  │  • Sign lock hash with threshold signature      │  │
│  └─────────────────────────────────────────────────┘  │
│                        ↓                              │
│              ═══ Barrier Sync ═══                     │
│                        ↓                              │
│  ┌─────────────────────────────────────────────────┐  │
│  │ Phase 4: Node Signature Exchange                │  │
│  │  • Each node signs lock hash with p2p key       │  │
│  │  • Broadcast signatures to all nodes            │  │
│  │  • Collect all N signatures                     │  │
│  └─────────────────────────────────────────────────┘  │
│                        ↓                              │
│              ═══ Barrier Sync ═══                     │
│                        ↓                              │
│  ┌─────────────────────────────────────────────────┐  │
│  │ Phase 5: Verification & Persistence             │  │
│  │  • Verify all signatures                        │  │
│  │  • Verify cluster lock integrity                │  │
│  │  • Write validator keys to disk                 │  │
│  │  • Write cluster lock to disk                   │  │
│  │  • Write deposit data to disk                   │  │
│  └─────────────────────────────────────────────────┘  │
│                        ↓                              │
│              ═══ Barrier Sync ═══                     │
│                        ↓                              │
│  ┌─────────────────────────────────────────────────┐  │
│  │ Phase 6: Graceful Shutdown                      │  │
│  │  • All clients send shutdown flag               │  │
│  │  • Servers wait for all shutdown messages       │  │
│  │  • Coordinated termination (no node left behind)│  │
│  └─────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────┘

Legend:
  ═══ Barrier Sync ═══  All nodes must reach this point before
                        any node proceeds to next phase
```

Each barrier synchronization ensures no node proceeds until all nodes complete the current phase.

## Protocol Identifier (libp2p)

The sync protocol uses the following protocol ID for stream multiplexing:

```text
/charon/dkg/sync/1.0.0/
```

## Message Schemas

The following protobuf definitions are used over the wire:

- [dkg_sync.proto](../../proto/dkg_sync.proto) - DKG sync message definitions

See the Python reference implementation: [`MsgSync` and `MsgSyncResponse`](../../src/dv_spec/subspecs/dkg_sync/message.py)

`MsgSync` also carries an optional `nickname` field (max 32 characters): a
human-friendly peer name displayed to other operators during the ceremony.
It is purely informational and MUST NOT affect protocol behavior.

## Ceremony Sequencing

The sync protocol coordinates the DKG ceremony through the following sequence:

1. **Connection Establishment**

   - Each node runs both a server and N-1 clients (one per remote peer)
   - Clients open persistent streams to all peer servers using protocol ID `/charon/dkg/sync/1.0.0/`
   - Initial `MsgSync` contains definition hash signature for verification
   - Servers verify signatures and version compatibility (DKG compatibility requires matching minor version)
   - Server responds with `MsgSyncResponse` (empty error = success, non-empty error = failure)
   - Wait until all N-1 peers successfully connect

2. **Step Synchronization Loop**

   - For each ceremony phase (cryptographic DKG, validator setup, lock creation, etc.):
     - All nodes perform the phase operations locally
     - Each node increments its step counter
     - Clients send `MsgSync` with updated step to their servers (approximately once per second)
     - Servers track all client steps and echo timestamp for RTT measurement
     - Servers only allow progression when all clients reach the same step (barrier)
     - Ceremony code blocks until `await_all_at_step(N)` returns
   - Steps must progress monotonically (0 → 1 → 2 → ...); servers reject step decreases

3. **Graceful Shutdown**
   - After final phase completes, all clients set `shutdown=true` in `MsgSync`
   - Servers wait for shutdown messages from all N-1 clients
   - Server marks each client as shutdown and only completes when all are shutdown
   - Coordinated termination ensures no node left hanging

## Architecture Details

### Server-Client Model

Each node runs both a **server** and multiple **clients**:

- **Server**: Accepts connections from N-1 other nodes, tracks their connection status and current step
- **Clients**: One client per remote peer (N-1 total), maintains persistent connection to that peer's server

### Verification and Validation

**Definition Hash Signature**:

- Each node signs the cluster definition hash with its libp2p private key
- Server extracts peer public key from stream connection
- Server verifies signature

**Version Compatibility**:

- DKG compatibility requires matching minor version (e.g., 1.x.y)
- Server parses client version string and compares
- Mismatch results in `MsgSyncResponse.error = "version mismatch..."`

**Step Monotonicity**:

- Steps must progress monotonically: 0 → 1 → 2 → ...
- Server rejects messages with step < previously recorded step
- Prevents rollback attacks or protocol confusion

### Reconnection Support

The reconnection behavior operates in two distinct phases:

**Phase 1: During Initial Connection**

- Client starts with `reconnect=true` state
- Uses exponential backoff with 1s max delay for connection attempts
- Always retries on connection failures until all peers connected
- Relay circuit recycling errors (`network.ErrReset`, `network.ErrResourceScopeClosed`) trigger immediate reconnection

**Phase 2: After All Peers Connected**

- All clients disable reconnect, setting `reconnect=false`
- Connection breaks now cause immediate failure (fail-fast mode)
- Exception: Relay circuit recycling errors still trigger reconnection regardless of `reconnect` state
- Rationale: Avoid hanging on transient connection issues after ceremony has started

## Step Synchronization

The DKG ceremony proceeds through numbered steps (0, 1, 2, ...). Between each step, all nodes must synchronize via barrier coordination.

### Client Behavior

Clients maintain a local step counter and send periodic `MsgSync` updates (~1 second interval) containing:

- Current UTC timestamp
- Definition hash signature (constant throughout ceremony)
- Current step number
- Shutdown flag (false during ceremony)
- Version string
- Nickname (optional, max 32 characters; informational only)

After completing each ceremony phase, the client increments its step counter and waits for the barrier to lift before proceeding. The server response timestamp allows RTT measurement for network monitoring.

### Server Behavior

Servers track state for each connected peer:

- Connection status (connected/disconnected)
- Current step number
- Shutdown status

For each incoming `MsgSync`, the server:

1. Echoes the timestamp in `MsgSyncResponse` for RTT calculation
2. Validates version compatibility (matching MAJOR.MINOR)
3. Verifies definition hash signature on first message
4. Enforces monotonic step progression (no backwards steps)
5. Updates peer's current step in tracking table
6. Marks peer for shutdown if `shutdown=true`

The barrier lifts when all N-1 connected peers report the same step number.

### Step Validation Rules

Servers enforce the following rules:

1. **First Step**: Must be 0 or 1 (to handle initialization race conditions)
2. **Monotonicity**: Steps must not decrease (step_new ≥ step_old)
3. **Maximum Jump**: Steps should not skip more than 2
4. **All Peers Progress**: Server only unblocks barrier when all N-1 clients report step N or N+1

## Graceful Shutdown

At ceremony completion, nodes coordinate shutdown to ensure no peer terminates prematurely.

**Client**: Sends final `MsgSync` with `shutdown=true` flag, waits for server acknowledgment, then closes the stream.

**Server**: Tracks shutdown requests from all N-1 clients. Only after receiving shutdown messages from every peer does the server consider shutdown complete.

This coordination prevents premature exits that could leave other nodes waiting indefinitely.

## Error Handling

### Validation Errors

Version mismatches and invalid definition hash signatures are fatal errors. The server returns `MsgSyncResponse` with a non-empty error string describing the issue. Upon receiving a validation error, clients abort the ceremony immediately.

### Timeout Errors

Servers monitor the last message timestamp from each peer. If a peer stops sending sync messages for longer than the timeout threshold (typically 30 seconds), the server aborts the ceremony for all participants.
