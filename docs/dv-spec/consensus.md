# Consensus and QBFT Interoperability Spec

This document describes the QBFT consensus protocol used for reaching agreement among distributed validator nodes.

Scope:

- Over-the-wire message structures and fields
- Consensus flow and round mechanics
- Protocol identifiers and exchange patterns
- Verification and validation flows

Out of scope: cluster discovery/formation, storage, application-specific value encoding beyond the hashing contract, and any non-libp2p transport.

## Terms and notation

- `n`: Number of nodes in the cluster
- `f`: Maximum Byzantine faults tolerated, where f < n/3
- `quorum`: ceil(2n/3) nodes must agree for decisions
- `duty`: Consensus instance identifier `(slot, type)`. Each duty requires independent consensus
- `round`: 1-based counter for coordination. Rounds increase on timeout or failure
- `peer_idx`: 0-based index into membership list, maps to a configured public key

## Protocol identifiers (libp2p)

All messages are sent under protocol ID:

```text
/charon/consensus/qbft/2.0.0
```

## Consensus Flow

QBFT operates in rounds. Each round attempts to reach consensus through three phases:

**Normal operation:**

1. **Pre-Prepare**: The leader for `(duty, round)` proposes a value `V` by broadcasting `PRE_PREPARE(round, V)`
2. **Prepare**: Upon receiving a justified `PRE_PREPARE`, nodes broadcast `PREPARE(round, V)`
3. **Commit**: Upon receiving quorum `PREPARE(round, V)`, nodes broadcast `COMMIT(round, V)`
4. **Decision**: Upon receiving quorum `COMMIT(round, V)`, nodes decide on `V`

**Round changes:**

When a round times out or fails, nodes initiate a round change:

- Nodes broadcast `ROUND_CHANGE` messages for the next round
- A quorum of `ROUND_CHANGE` allows entering the new round
- The new round's leader includes justification in their `PRE_PREPARE`

**Justification types:**

- **J1 (null-prepared)**: Quorum of `ROUND_CHANGE` with no prepared value (fresh start)
- **J2 (prepared)**: Quorum of `ROUND_CHANGE` where some have prepared `(round*, value*)` in a prior round. The leader MUST propose `value*` with `prepared_round=round*`

Note: `round*` and `value*` denote the highest prepared round number and its corresponding value from the justification (i.e., values from a previous round, not the current round).

**Leader selection:**

```text
leader_index = (duty.slot + duty.type + round) % n
```

**Timers:**

- Each round runs under a timer
- On timeout, nodes trigger a round change and increment the round
- Timer/backoff strategy does not affect safety, but must guarantee eventual progress
- The default strategy is the *eager double linear* timer: round `r` lasts
  `r` seconds, and the first deadline of each round is computed
  deterministically from the chain (`genesis_time + slot * slot_duration +
  duty_start_delay + timeout`) rather than the local clock, so round
  boundaries — and hence leader election — stay aligned across all peers.
  The duty start delay is `slot_duration/3` for attestations,
  `2*slot_duration/3` for aggregations and sync contributions, and `0`
  otherwise. Implementations SHOULD match this strategy: a peer with
  misaligned round deadlines degrades cluster liveness (it changes rounds,
  and expects leaders, at the wrong times)

See the Python reference implementation: [`RoundTimer`](https://github.com/ObolNetwork/distributed-validator-specs/blob/main/src/dv_spec/subspecs/consensus/timer/timer.py).

**Message limits:**

Receivers MUST bound incoming consensus messages before expensive
verification work (see `verify_msg_limits` and `MAX_CONSENSUS_MSG_SIZE` in
the reference implementation):

- Wire size: at most 32 MiB per message (enforced as a stream read limit)
- Justifications: at most `2 * n` per message
- Values: at most `2 * (justifications + 1)` per message

**Decided messages:**

`DECIDED` messages are optional since consensus is achieved upon quorum `COMMIT(r, V)`, however they can be used to help slow nodes catch up.

After deciding, a node responds to any ROUND-CHANGE from a peer by
rebroadcasting `DECIDED` (helping lagging peers catch up), rate-limited to at
most one rebroadcast per source per strictly-increasing round and at most 16
rebroadcasts per source in total, to prevent amplification abuse.

### Message Schemas

The following protobuf definitions are used over the wire:

- [consensus.proto](https://github.com/ObolNetwork/distributed-validator-specs/blob/main/proto/consensus.proto) - QBFT consensus message definitions
- [core.proto](https://github.com/ObolNetwork/distributed-validator-specs/blob/main/proto/core.proto) - Common core type definitions (Duty, ParSignedData, etc.)

See the Python reference implementation: `MsgType`, `QBFTMsg` and `QBFTConsensusMsg` in [`qbft/message.py`](https://github.com/ObolNetwork/distributed-validator-specs/blob/main/src/dv_spec/subspecs/consensus/qbft/message.py), and `Duty` in [`types/duty.py`](https://github.com/ObolNetwork/distributed-validator-specs/blob/main/src/dv_spec/types/duty.py).

**Value carriage:**

The `values` array MUST contain an Any-wrapped payload for every non-zero hash referenced by:

- `msg.value_hash`
- `msg.prepared_value_hash`
- Every `justification[i].value_hash`
- Every `justification[i].prepared_value_hash`

Extra values MAY be included; order is irrelevant.

### Hashes and Signatures

**Hashing:**

- Leader computes a deterministic hash root for values from deterministic protobuf encodings: `HashRoot(deterministic_proto(value))`

**Signature:**

- Message signature is computed over: `HashRoot(deterministic_proto(unsigned QBFTMsg))`
- Format: secp256k1 signature (65-byte R||S||V)
- The public key used for verification can be obtained by matching the `peer_idx` from the message with the `peer_idx` in the lock file (see [Cluster Configuration](cluster-files.md) for lock file structure)

### Message Constraints

See the Python validation implementation in [`qbft/message.py`](https://github.com/ObolNetwork/distributed-validator-specs/blob/main/src/dv_spec/subspecs/consensus/qbft/message.py) and [`types/duty.py`](https://github.com/ObolNetwork/distributed-validator-specs/blob/main/src/dv_spec/types/duty.py); the names in parentheses below are the symbols in those modules that implement each rule.

**Validation rules (receivers MUST reject if any fails):**

- `msg` and `msg.duty` are present
- `msg.type` ∈ {1,...,5} (`MsgType`)
- `duty.type` is valid (`DutyType`)
- `peer_idx` >= 0 (`validate_peer_idx`)
- `peer_idx` is a valid index in ordered peer list and maps to a known public key
- `signature` is 65 bytes when present (R||S||V format) (`validate_signature`)
- Signature recovery matches the public key for `peer_idx`
- `round` >= 1 (`validate_round`)
- `prepared_round` >= 0; `0` indicates no preparation (null-prepared) (`validate_prepared_round`)
- `prepared_round` <= `round` (`validate_prepared_round`)
- `value_hash` is 32 bytes when non-zero (`validate_value_hash`)
- `prepared_value_hash` must be zero hash if `prepared_round` is 0; must be non-zero hash if `prepared_round` > 0 (`validate_prepared_value_hash`)
- `justification` is a flat list (nested justifications are rejected) with each object in `justification` having identical duty to `msg.duty`
- For each referenced non-zero hash in `msg` or `justifications`, a matching value exists in `values` and re-hashes to that hash

### Field Requirements by Message Type

All message types share these common requirements:

- `type`: MUST be set to the appropriate [`MsgType`](https://github.com/ObolNetwork/distributed-validator-specs/blob/main/src/dv_spec/subspecs/consensus/qbft/message.py)
- `duty`: MUST be present with valid `slot` and `type` fields
- `peer_idx`: MUST be >= 0 and a valid index in the ordered peer list
- `round`: MUST be >= 1
- `signature`: MUST be 65 bytes (secp256k1 R||S||V format) and verify against the peer's public key

**`PRE_PREPARE`:**

Sent by the leader of `(duty, round)` only upon startup or round change to every other node.

Required fields:

- `value_hash`: MUST be present (32-byte non-zero hash of proposed value)
- `prepared_round` and `prepared_value_hash`:
  - For J1 (null-prepared): MUST be `0` and zero hash (32 zero bytes) respectively
  - For J2 (prepared): MUST be present with `prepared_round=round*` (where `round* > 0`) and `prepared_value_hash=H(value*)` (non-zero hash) from the highest prepared round in the justification
- `justification`:
  - Round 1: MUST be empty
  - J1 (null-prepared): MUST include quorum `ROUND_CHANGE` messages with null prepared values
  - J2 (prepared): MUST include quorum `ROUND_CHANGE` messages AND quorum `PREPARE(round*, value*)` messages from the highest prepared round

**`PREPARE`:**

Sent by any node upon receiving justified `PRE_PREPARE` to every other node.

Required fields:

- `value_hash`: MUST be present (32-byte non-zero hash matching the `PRE_PREPARE` value)

**`COMMIT`:**

Sent by any node upon receiving quorum `PREPARE` messages to every other node.

Required fields:

- `value_hash`: MUST be present (32-byte non-zero hash of the prepared value)

**`ROUND_CHANGE`:**

Sent by any node on round timeout or f+1 `ROUND_CHANGE` receipt to every other node.

Required fields:

- `prepared_round`:
  - If null-prepared: `0`
  - If prepared: MUST be `> 0` with `round*` from the highest prepared round
- `prepared_value_hash`:
  - If null-prepared: zero hash (32 zero bytes)
  - If prepared: MUST be non-zero hash `H(value*)` from the highest prepared round
- `justification`:
  - If null-prepared: MUST be empty
  - If prepared: MUST include quorum `PREPARE(round*, value*)` messages that justify the prepared round and value

**`DECIDED`:**

Sent by decided nodes when receiving `ROUND_CHANGE` from late-joining peers.
Optional message type for optimization, implementations MUST NOT rely on `DECIDED` messages for safety or liveness guarantees

Required fields:

- `value_hash`: MUST be present (32-byte non-zero hash of decided value)
- `justification`: MUST include quorum `COMMIT(round, value)` messages that achieved consensus
