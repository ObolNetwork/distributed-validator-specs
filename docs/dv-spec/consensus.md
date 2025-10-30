// Kalo: There are full stops and no full stop seemingly at random. Let's keep those consistent.
## Distributed validator consensus and QBFT interop

Use this to build a client that can participate in DV consensus over the QBFT wire protocol with other implementations.

## DV consensus model (protocol-agnostic)

Goals and invariants

- Safety: at most one value is decided per duty instance. //Kalo: debateable how you look at "value". For Attestations we agree on 1 value but for all validators that need to attest in that slot.
- Liveness: a value is eventually decided under partial synchrony with f < n/3 Byzantine faults.

Terms and parameters

- n: number of nodes in the cluster; `f < n/3`; `quorum = ceil(2n/3)`.
- Duty: consensus instance identifier `(slot, type)`. Exactly one consensus instance per `(slot, type)`.
- Round: 1-based counter used by the chosen consensus engine to coordinate progress.
- Membership: an ordered list of participants; `peer_idx` is a 0-based index into this list and maps to a configured public key.

Timing

- Each round runs under a timer. On timeout, the engine triggers a round change and increases the round.
- Timer/backoff strategy is implementation-defined; it must guarantee eventual progress without assuming synchrony.

Out of scope for this spec: cluster discovery/formation, storage, application-specific value encoding beyond the hashing contract, and any non-libp2p transport.

### Duty types

Implementations MUST use the following integer mapping for `duty.type`; 0 is reserved and invalid on wire.

- 1: proposer
- 2: attester
- 3: signature
- 4: exit
- 5: builder_proposer (deprecated)
- 6: builder_registration (deprecated)
- 7: randao
- 8: prepare_aggregator
- 9: aggregator
- 10: sync_message
- 11: prepare_sync_contribution
- 12: sync_contribution
- 13: info_sync

### Protocol identifiers (libpp2p)

All messages are sent under protocol ID prefix:

```
/charon/consensus/qbft/2.0.0
```

Messages are broadcasted to all peers except self; self-delivery is handled locally by the node.

### Leader selection

```
leader_index = (duty.slot + duty.type + round) % n
```

### Message schemas

The following structures are used over the wire.

The protobufs used by Charon are available [here](https://github.com/ObolNetwork/charon/tree/main/core/corepb/v1). // Kalo: not sure if it isn't better to copy them tbh. We don't really want references to Charon, we want to keep it implementation agnostic.

// Kalo: I'm not sure if that's the best way of mentioning constraints. Up to debate though, might be good enough. Also probably good to wrap each value with a backtick, probably will improve readability?
- QBFTMsg
  - type: int64 (1=pre_prepare, 2=prepare, 3=commit, 4=round_change, 5=decided)
  - duty: { slot:uint64, type:int32 } // Kalo: probably better to keep that in a separate schema and refer to it here?
  - peer_idx: int64 (0-based index in ordered membership)
  - round: int64 (>= 1)
  - value_hash: bytes[32] (optional; non-zero indicates presence)
  - prepared_round: int64 (>= 0; 0 means absent)
  - prepared_value_hash: bytes[32] (optional; non-zero indicates presence)
  - signature: bytes[65] (secp256k1 R||S||V over the hashed message without signature)

// Kalo: wouldn't it be better if we put arrays as []QBFTMsg?
- QBFTConsensusMsg
  - msg: QBFTMsg (the primary message)
  - justification: repeated QBFTMsg (flat list; nested graphs are rejected)
  - values: repeated Any (protobuf Any wrapping concrete value payloads)

### Value carriage

- The values array MUST contain an Any-wrapped payload for every non-zero hash referenced by `msg.value_hash`, `msg.prepared_value_hash`, and every `justification` object. // Kalo: "and all justifications" = for each justification, its .value_hash and .prepared_value_hash?
- Extra values MAY be included; order is irrelevant.

### Hashes and signature

- Hashes: a deterministic hash root for values from deterministic protobuf encodings - `HashRoot(deterministic_proto(value))`
  - sign HashRoot(deterministic_proto(QBFTMsg without signature))
- Signature: signature over the whole QBFT message - `secp256k1_sign(HashRoot(deterministic_proto(value)))`. The public key used for verifying can be obtained by matching the `peer_idx` from the message with the `peer_idx` in the lock file.

// Kalo: We should call that constraints and put everything that we have in parantheses in ### Message schemas here probably.
### Receiver validation rules (reject if any fails)

- `msg` and `msg.duty` are present;
- `msg.type` ∈ {1..5}
- `duty.type` is valid (see [Duty types](#duty-types))
- `msg.round` >= 1 and `msg.prepared_round` >= 0
- `peer_idx` maps to a known public key; signature recovery matches that key
- each object in `justification` has identical duty to `msg.duty`
- for each referenced non-zero hash in `msg` or `justifications`, a matching value exists in `values` and re-hashes to that hash

### Round mechanics (QBFT)

Phases per round

1. Pre-Prepare: leader proposes value `V` (value_hash set; prepared fields absent)
2. Prepare: quorum of `PREPARE(r, V)` establishes `prepared_round=r` and `prepared_value=V`
3. Commit: quorum of `COMMIT(r, V)` decides `V`; `DECIDED` may be emitted but is optional

Round-change justification

- J1 (null-prepared): quorum of `ROUND_CHANGE` for target round `R` with `prepared_round=0` and no `prepared_value_hash`
- J2 (prepared): quorum of `PREPARE(r*, V*)` proving a prepared value; leaders of `R` MUST carry `prepared_round=r*` and `prepared_value_hash=H(V*)` in `PRE_PREPARE`

Leader sending `PRE_PREPARE` in round `R` MUST include in `justification` the quorum set that justified entry into `R` (RC quorum for J1, or `PREPARE` quorum for J2).

`DECIDED` semantics

- `DECIDED` messages are optional; consensus is achieved upon a quorum of `COMMIT(r, V)`.

Transport notes

- Use libp2p protocol ID above; broadcast to all except self.
- The envelope may include multiple `Any` values to satisfy referenced hashes in `msg` and `justifications`. // Kalo: I know envelope is commonly used in libp2p, but I feel we are throwing in a lot of terms here without giving much explanation to any of them. Can we stick either to less terms or make them more descriptive?

// Kalo: I'm thinking if it won't be better to include those on top in order to be easier to grasp what each message is? I leave it up to you to decide.
### Field requirements by message type

- `PRE_PREPARE` (type=1)

  - MUST be sent by the leader of (duty, round)
  - MUST set `value_hash` (non-zero)
  - `prepared_round` and `prepared_value_hash` MUST be absent (0/zero-hash) unless entering `R` via `J2`; in that case, MUST set `prepared_round=r*` and `prepared_value_hash=H(V*)`
  - `justification` MUST include the quorum used to enter the round (`RC` quorum for `J1`, `PREPARE` quorum for `J2`)

- `PREPARE` (type=2)

  - MUST set `value_hash` (non-zero)
  - MUST NOT set `prepared_round` or `prepared_value_hash` (use 0/zero-hash)
  - `justification` SHOULD be empty

- `COMMIT` (type=3)

  - MUST set `value_hash` (non-zero)
  - `prepared_round` and `prepared_value_hash` MUST be absent (0/zero-hash)
  - `justification` MAY be empty; receivers MUST NOT require additional evidence beyond quorum of `COMMIT`s

- `ROUND_CHANGE` (type=4)

  - For null-prepared `J1`: MUST set `prepared_round=0` and omit `prepared_value_hash`; `justification` MAY be empty
  - For prepared `J2`: MUST set `prepared_round=r*` and `prepared_value_hash=H(V*)`; justification MUST include a quorum of `PREPARE(r*, V*)`

- `DECIDED` (type=5)
  - Optional;
  - Receivers MUST tolerate presence/absence and MUST NOT rely on it for safety or liveness
