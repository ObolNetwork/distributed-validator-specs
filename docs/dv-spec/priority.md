# Priority Interoperability Spec

This document describes the Priority protocol used for achieving cluster-wide consensus on ordered lists of arbitrary priorities across distributed validator nodes.

## Overview

The Priority protocol enables distributed validator nodes to reach cluster-wide consensus on ordered preference lists. This is essential for coordinating behavior across independent nodes that may have different capabilities, versions, or configurations.

This document specifies the generic mechanism. Its one production use is [InfoSync](infosync.md), which defines the concrete topics, the trigger cadence, and how the agreed result selects the cluster's consensus protocol.

### Use Cases

Distributed validators are composed of multiple independent nodes that need to coordinate on shared preferences. For example:

- **Consensus protocol selection**: When a cluster needs to agree on which consensus protocol to use (e.g., QBFT v2.0 or future protocols), each node may support different versions. The priority protocol allows nodes to exchange their preferences and converge on the best protocol supported by threshold nodes.

- **Version monitoring**: During cluster upgrades, nodes running different Charon versions exchange version information. This information is monitored and logged, providing visibility into cluster version heterogeneity.

- **Proposal type preferences**: Nodes may prefer different block proposal strategies (full blocks, builder/blinded blocks, or synthetic proposals). The priority protocol ensures the cluster uses proposal types supported by threshold nodes.

### Specification Scope

This document describes:

- Over-the-wire message shapes and fields
- Protocol identifiers and exchange patterns
- Result calculation and scoring logic

Out of scope: cryptographic signature routines, consensus algorithm implementation, transport reliability

## Terms and Notation

- `n`: number of participating nodes in the cluster
- `t`: threshold required for consensus (typically ceil(2n/3))
- `Duty`: a validator responsibility at a specific slot
- `Topic`: a named grouping of related priorities (e.g., "protocol", "version", "proposal")
- `Priority`: an arbitrary piece of data being prioritized within a topic
- `Score`: calculated weight of a priority based on peer count and position
- `Exchange timeout`: maximum time allowed for priority message exchange (typically 6 seconds)

## Protocol Identifiers (libp2p)

Priority has two protocol IDs for the same protocol, listed here in order of
precedence:

```text
/charon/priority/2.0.0     preferred
charon/priority/2.0.0      legacy, no leading "/"
```

The legacy spelling is missing its leading `/`, unlike every other protocol in
this specification — a historical accident in Charon
(`core/priority/prioritiser.go`) that put the bare string on the wire. Charon
normalised the ID and kept the old spelling as an alias, so the wire format is
identical under either and the version stays at `2.0.0`.

Three rules follow, and an implementation needs all three to interoperate:

1. **Dialling**: offer both IDs, the preferred one first, and use whichever the
   peer negotiates. Charon obtains this ordering with
   `p2p.WithDelimitedProtocol`, which prepends.
2. **Listening**: serve both IDs, registering a handler for each one
   **separately, as an exact match**.
3. **Do not register the two IDs together under a common prefix.** They share no
   common prefix, so a combined registration reduces that prefix to the bare
   wildcard `*` — and libp2p identify then advertises `*` to peers in place of
   either real protocol ID.

> **Warning**: serving only the preferred ID is not sufficient. Every Charon
> release up to and including `v1.11.0-rc1` speaks the legacy spelling alone, so
> an implementation that drops it cannot exchange priorities with any released
> Charon. Charon's own code targets `v1.12` for the preferred ID and `v1.14` for
> removing the alias.

## Exchange Pattern

Priority implements a two-phase request-response pattern:

### Phase 1: Priority Exchange

1. **Initiation**: When a priority protocol instance is triggered (typically for `DutyInfoSync` at the last slot of each epoch), a node creates a `PriorityMsg` containing:

   - The duty being performed
   - One or more topics, each with an ordered list of priorities
   - The node's peer ID
   - A cryptographic signature

2. **Broadcast phase**: Each node in the cluster independently initiates the priority protocol by sending its `PriorityMsg` to all other peers using libp2p `SendReceive`. All nodes perform this broadcast in parallel.

3. **Handler response**: Each peer that receives a `PriorityMsg` request immediately responds with its own `PriorityMsg` for the same duty.

4. **Collection**: Each node collects priority messages from peers. Messages are deduplicated by peer ID (only the first message from each peer is kept). Duplicates can occur because nodes both send their own broadcast AND respond to incoming requests from other nodes.

5. **Exchange completion**: The exchange phase completes when either:
   - Messages from all peers have been received, or
   - The exchange timeout expires (typically 6 seconds)

### Phase 2: Consensus

1. **Result calculation**: Once the exchange phase completes, each node deterministically calculates cluster-wide priorities from the collected messages.

2. **Consensus proposal**: Each node proposes its calculated `PriorityResult` to the consensus protocol (typically QBFT).

3. **Consensus output**: Consensus is reached when threshold peers propose the same result, which is then delivered to all subscribers.

## Message Schemas

The following protobuf definitions are used over the wire:

- [priority.proto](https://github.com/ObolNetwork/distributed-validator-specs/blob/main/proto/priority.proto) - Priority protocol message definitions
- [core.proto](https://github.com/ObolNetwork/distributed-validator-specs/blob/main/proto/core.proto) - Common core type definitions (Duty)

See the Python reference implementation: [`PriorityMsg`, `PriorityTopicProposal`, `PriorityResult`, `PriorityTopicResult` and `PriorityScoredResult`](https://github.com/ObolNetwork/distributed-validator-specs/blob/main/src/dv_spec/subspecs/priority/message.py), and [`Duty`](https://github.com/ObolNetwork/distributed-validator-specs/blob/main/src/dv_spec/types/duty.py).

## Protocol Flow

### 1. Message Creation and Signing

When initiating a priority instance:

```
msg := PriorityMsg{
  duty: duty,          // field 1
  topics: [topics...], // field 2
  peer_id: own_peer_id,// field 3
  signature: nil       // field 4
}

hash := ssz_hash(deterministic_marshal(msg))
msg.signature = secp256k1_sign(private_key, hash)
```

The signature is computed over the entire message with the signature field set to nil.

Because the signature covers the encoding, the field numbers are part of the
protocol: `topics` is field 2 and `peer_id` is field 3, per
[`proto/priority.proto`](https://github.com/ObolNetwork/distributed-validator-specs/blob/main/proto/priority.proto).
Transposing the two yields a signing root no peer can reproduce, so no signature
verifies. `scripts/check_proto_parity.py` pins this against Charon.

### 2. Exchange with Peers

Send the signed message to all peers concurrently:

```
for each peer in peers:
  if peer != self:
    go sendReceive(peer, own_msg, response_channel)
```

Each peer's handler responds immediately with its own priorities for the same duty.

### 3. Peer Request Handling

When receiving a priority request from a peer:

1. **Validate request**:

   - Verify message signature using peer's public key
   - Verify duty is not expired
   - Verify peer_id matches sender

2. **Enqueue request**: Add request to instance-specific request buffer

3. **Generate response**: Return own `PriorityMsg` for the same duty via response channel

### 4. Response Collection

The instance collects responses until:

- All peer messages received (including own message)
- Exchange timeout expires (6 seconds)

Deduplication: Only the first message from each peer is kept.

### 5. Result Calculation

Once exchange completes, calculate the cluster-wide result:

1. **Validate messages**:

   - All messages must have the same duty
   - No duplicate peer IDs
   - Each peer's topics must not have duplicates
   - Each topic must not exceed 1000 priorities
   - Each topic must not have duplicate priorities

2. **Group by topic**: Collect all priority proposals for each topic across all peers

3. **Score calculation**: For each priority in each topic:

   ```
   count = number of peers that included this priority
   position_scores = sum of (1000 - position) for each peer
   overall_score = (count * 1000) + position_scores
   ```

   This scoring ensures priorities are ordered by:

   - First, by how many peers included them (more peers = higher priority)
   - Second, by their average position across peers (earlier position = higher priority)

4. **Filter by threshold**: Only include priorities that appear in at least `minRequired` peer messages

5. **Sort priorities**: Within each topic, sort by score descending. The sort **must be stable**, so equal-scoring priorities keep the order in which they were first seen — which is why the messages are processed in ascending peer ID order.

6. **Deterministic ordering**: Sort topics by hash for deterministic output

### 6. Consensus

Start a consensus round proposing the calculated result.
The consensus protocol ensures all nodes agree on the same result.

## Verification

### Signature Verification

All received priority messages must be cryptographically verified:

1. **Extract sender's public key** from peer ID (secp256k1 public key)

2. **Clone message** and set signature field to nil

3. **Hash message**:

   ```
   hash = ssz_hash(deterministic_protobuf_marshal(msg))
   ```

4. **Recover public key** from signature:

   ```
   recovered_pubkey = secp256k1_recover(hash, signature)
   ```

5. **Verify match**:
   ```
   if recovered_pubkey != sender_pubkey:
       reject message
   ```

### Message Validation

Before processing a priority message:

- Verify `duty` field is non-nil
- Verify `peer_id` matches the sender
- Verify signature is valid
- Verify duty has not expired based on deadliner

### Result Validation

Before starting consensus:

- Messages contain no duplicate peers
- All messages reference the same duty
- No peer has duplicate topics
- No topic exceeds 1000 priorities
- No topic has duplicate priorities

## Scoring Algorithm

The scoring algorithm ensures deterministic, fair prioritization:

1. **Count weight**: A priority appearing in more peer lists always ranks higher than one appearing in fewer, regardless of position

2. **Position weight**: For priorities with equal peer counts, earlier positions rank higher

3. **Score formula**:

   ```
   count_weight = 1000  // constant
   for each peer that included priority:
     peer_position = index of priority in peer's list (0-based)
     position_score = count_weight - peer_position
     total_position_score += position_score

   overall_score = (peer_count * count_weight) + total_position_score
   ```

4. **Example**:

   - Priority "A" appears in 3 peers at positions [0, 1, 2]
     - score = (3 × 1000) + (1000 + 999 + 998) = 5997
   - Priority "B" appears in 2 peers at positions [0, 0]
     - score = (2 × 1000) + (1000 + 1000) = 4000
   - Result: "A" ranks higher despite "B" having better average position

## Properties

- **Deterministic calculation**: All nodes calculate the same result from the same inputs
- **Threshold-based filtering**: Only priorities supported by threshold peers are included
- **Score-based ordering**: Priorities ordered by peer count, then position
- **Signature-authenticated**: All messages cryptographically signed and verified
- **Idempotent**: Duplicate messages from same peer are ignored
- **Duty-scoped**: Each instance operates on a specific duty

## Interop Notes

- **Protocol versioning**: Both `/charon/priority/2.0.0` and the legacy `charon/priority/2.0.0` identify version `2.0.0` of this protocol and must both be served (see [Protocol Identifiers](#protocol-identifiers-libp2p)); future versions may use different IDs
- **Signature algorithm**: Uses secp256k1 ECDSA signatures with recovery; public keys derived from libp2p peer IDs
- **Hash function**: Uses SSZ (Simple Serialize) hashing over deterministic protobuf marshalling for message signing and priority deduplication
- **Protobuf Any encoding**: Topics and priorities are encoded as protobuf `Any` types for flexibility; current implementation uses `structpb.StringValue` for both
- **Exchange timeout**: Fixed at 6 seconds (half a slot) to allow sufficient time for all peers to exchange while staying within slot boundaries
- **Maximum priorities**: Limited to 1000 priorities per topic to prevent unbounded message growth and calculation overhead
- **Consensus backend**: Currently uses QBFT v2.0 as the consensus protocol

- **Topic ordering**: Topics in results are ordered by their SSZ hash for deterministic output across all peers

- **Tie breaking**: When priorities have identical scores, the one first proposed wins, taking peers in ascending peer ID order. This requires a stable sort by score over messages pre-sorted by peer ID; it is *not* a tie-break by priority hash (that ordering applies to topics, not to priorities within a topic). Charon sorts stably as of `6054bcb2`; releases up to `v1.11.0-rc1` used a non-stable sort that agreed only because Go's pdqsort falls back to insertion sort below thirteen elements

- **Minimum required**: Typically set to threshold (ceil(2n/3)); priorities appearing in fewer peer messages are excluded from results

- **Request buffering**: Each duty instance maintains its own request buffer; peer requests are queued and responded to by the running instance

- **Empty topics**: Topics with no priorities meeting the threshold are included in results with empty priority lists
