## Consensus and QBFT Interoperability Spec

This document describes the QBFT consensus protocol used for reaching agreement among distributed validator nodes.

Scope:

- Over-the-wire message structures and fields
- Consensus flow and round mechanics
- Protocol identifiers and exchange patterns
- Verification and validation flows

Out of scope: cluster discovery/formation, storage, application-specific value encoding beyond the hashing contract, and any non-libp2p transport.

### Terms and notation

- `n`: Number of nodes in the cluster
- `f`: Maximum Byzantine faults tolerated, where f < n/3
- `quorum`: ceil(2n/3) nodes must agree for decisions
- `duty`: Consensus instance identifier `(slot, type)`. Each duty requires independent consensus
- `round`: 1-based counter for coordination. Rounds increase on timeout or failure
- `peer_idx`: 0-based index into membership list, maps to a configured public key

### Protocol identifiers (libp2p)

All messages are sent under protocol ID:

```text
/charon/consensus/qbft/2.0.0
```

### Consensus Flow

QBFT operates in rounds. Each round attempts to reach consensus through three phases:

**Normal operation:**

1. **Pre-Prepare**: The leader for `(duty, round)` proposes a value `V` by broadcasting `PRE_PREPARE(round, V)`
2. **Prepare**: Upon receiving a valid `PRE_PREPARE`, nodes broadcast `PREPARE(round, V)`
3. **Commit**: Upon receiving quorum `PREPARE(round, V)`, nodes broadcast `COMMIT(round, V)`
4. **Decision**: Upon receiving quorum `COMMIT(round, V)`, nodes decide on `V`

**Round changes:**

When a round times out or fails, nodes initiate a round change:

- Nodes broadcast `ROUND_CHANGE` messages for the next round
- A quorum of `ROUND_CHANGE` allows entering the new round
- The new round's leader includes justification in their `PRE_PREPARE`

**Justification types:**

- **J1 (null-prepared)**: Quorum of `ROUND_CHANGE` with no prepared value (fresh start)
- **J2 (prepared)**: Quorum of `ROUND_CHANGE` where some have prepared `(r*, V*)` in a prior round. The leader MUST propose `V*` with `prepared_round=r*`

**Leader selection:**

```text
leader_index = (duty.slot + duty.type + round) % n
```

**Timers:**

- Each round runs under a timer
- On timeout, nodes trigger a round change and increment the round
- Timer/backoff strategy is implementation-defined but must guarantee eventual progress // Kalo: Probably it's good to devote a paragraph for the timers we have

**Decided messages:**

- `DECIDED` messages are optional
- Consensus is achieved upon quorum `COMMIT(r, V)`; `DECIDED` messages are informational

### Message Schemas

The following structures are used over the wire. The protobuf definitions are available in this repository:

- [consensus.proto](../../proto/consensus/consensus.proto) - QBFT consensus message definitions
- [core.proto](../../proto/consensus/core.proto) - Duty definition

See the Python reference implementation: [`MsgType`](../../src/dv_spec/subspecs/consensus/qbft/message.py#L16-L23), [`QBFTMsg`](../../src/dv_spec/subspecs/consensus/qbft/message.py#L26-L109), [`QBFTConsensusMsg`](../../src/dv_spec/subspecs/consensus/qbft/message.py#L112-L120), [`Duty`](../../src/dv_spec/types/duty.py#L27-L40)

**Value carriage:**

The `values` array MUST contain an Any-wrapped payload for every non-zero hash referenced by:

- `msg.value_hash`
- `msg.prepared_value_hash`
- Every `justification[i].value_hash`
- Every `justification[i].prepared_value_hash`

Extra values MAY be included; order is irrelevant.

### Hashes and Signatures

**Hashing:**

- Compute a deterministic hash root for values from deterministic protobuf encodings: `HashRoot(deterministic_proto(value))` // Kalo: Probably good to say that this is done by the leader upon creating the message and is up to the message type and hashing? Or it's obvious?
- Message signature is computed over: `HashRoot(deterministic_proto(unsigned QBFTMsg))` // Kalo: shouldn't this be under Signature?

**Signature:**

- Format: secp256k1 signature (65-byte R||S||V)
- The public key used for verification can be obtained by matching the `peer_idx` from the message with the `peer_idx` in the lock file (see [Cluster Configuration](cluster-files.md) for lock file structure)

### Message Constraints

See Python validation implementation: [`QBFTMsg`](../../src/dv_spec/subspecs/consensus/qbft/message.py)

**Validation rules (receivers MUST reject if any fails):**

- `msg` and `msg.duty` are present
- `msg.type` ∈ {1,...,5} (see [`MsgType`](../../src/dv_spec/subspecs/consensus/qbft/message.py#L16-L23))
- `duty.type` is valid (see [Duty Types](#duty-types))
- `peer_idx` >= 0 (see [`validate_peer_idx`](../../src/dv_spec/subspecs/consensus/qbft/message.py#L51-L56))
- `peer_idx` is a valid index in ordered membership and maps to a known public key
- `signature` is 65 bytes when present (R||S||V format) (see [`validate_signature`](../../src/dv_spec/subspecs/consensus/qbft/message.py#L85-L90))
- Signature recovery matches the public key for `peer_idx`
- `round` >= 1 (see [`validate_round`](../../src/dv_spec/subspecs/consensus/qbft/message.py#L58-L63))
- `prepared_round` >= 1 when present; `None` indicates no preparation (see [`validate_prepared_round`](../../src/dv_spec/subspecs/consensus/qbft/message.py#L65-L83))
- `prepared_round` <= `round` when present (see [`validate_prepared_round`](../../src/dv_spec/subspecs/consensus/qbft/message.py#L65-L83))
- `value_hash` is 32 bytes when present (see [`validate_value_hash`](../../src/dv_spec/subspecs/consensus/qbft/message.py#L92-L97))
- `prepared_value_hash` is 32 bytes when present (see [`validate_prepared_value_hash`](../../src/dv_spec/subspecs/consensus/qbft/message.py#L99-L111))
- `prepared_value_hash` cannot be `None` if `prepared_round` is set (see [`validate_prepared_value_hash`](../../src/dv_spec/subspecs/consensus/qbft/message.py#L99-L111))
- `justification` is a flat list (nested justifications are rejected)
- Each object in `justification` has identical duty to `msg.duty`
- For each referenced non-zero hash in `msg` or `justifications`, a matching value exists in `values` and re-hashes to that hash

### Field Requirements by Message Type

**`PRE_PREPARE`:**

- MUST be sent by the leader of `(duty, round)`
- MUST set `value_hash` (non-zero)
- `prepared_round` and `prepared_value_hash` MUST be absent unless entering round via J2
  - J2 (prepared): MUST set `prepared_round=r*` and `prepared_value_hash=H(V*)` from the justified prepared value // Kalo: What is r* and V* here?
- `justification`:
  - J1 (null-prepared): MUST include quorum `ROUND_CHANGE` messages
  - J2 (prepared): MUST include quorum `PREPARE` messages for `(r*, V*)`

**`PREPARE`:**

- MUST set `value_hash` (non-zero) // Kalo: You mean to set a new `value_hash`? Or it's more like "Must have set"
- MUST NOT set `prepared_round` or `prepared_value_hash`
- `justification` SHOULD be empty

**`COMMIT`:**

- MUST set `value_hash` (non-zero)
- MUST NOT set `prepared_round` or `prepared_value_hash`
- `justification` MAY be empty (receivers MUST NOT require justification) // Kalo: What are the ocassions at which it's not empty?

**`ROUND_CHANGE`:**

- If null-prepared: MUST set `prepared_round=None` and `prepared_value_hash=None`; `justification` MAY be empty
- If prepared: MUST set `prepared_round=r*` and `prepared_value_hash=H(V*)`; `justification` MUST include quorum `PREPARE(r*, V*)`

**`DECIDED`:**

- Optional message type
- Receivers MUST tolerate presence/absence
- MUST NOT rely on `DECIDED` for safety or liveness

//Kalo: I think in general we can be more descriptive for each consensus message here
