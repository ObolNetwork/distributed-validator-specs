## Distributed validator consensus and QBFT interop

Use this to build a client that can participate in DV consensus over the QBFT wire protocol with other implementations.

## DV consensus model (protocol-agnostic)

Goals and invariants

- Safety: at most one value is decided per duty instance.
- Liveness: a value is eventually decided under partial synchrony with f < n/3 Byzantine faults.

Terms and parameters

- n: number of nodes in the cluster; f < n/3; quorum = ceil(2n/3).
- Duty: consensus instance identifier (slot, type). Exactly one instance per (slot, type).
- Round: 1-based counter used by the chosen consensus engine to coordinate progress.
- Membership: an ordered list of participants; peer_idx is a 0-based index into this list and maps to a configured public key.

Timing

- Each round runs under a timer. On timeout, the engine triggers a round change and increases the round.
- Timer/backoff strategy is implementation-defined; it must guarantee eventual progress without assuming synchrony.

Out of scope for this spec: cluster discovery/formation, storage, application-specific value encoding beyond the hashing contract, and any non-libp2p transport.

## Duty types

Implementations MUST use the following integer mapping for duty.type; 0 is reserved and invalid on wire.

- 1: proposer
- 2: attester
- 3: signature
- 4: exit
- 5: builder_proposer (deprecated)
- 6: builder_registration
- 7: randao
- 8: prepare_aggregator
- 9: aggregator
- 10: sync_message
- 11: prepare_sync_contribution
- 12: sync_contribution
- 13: info_sync

## QBFT interop (wire protocol)

Protocol identifier (libp2p)

```
/charon/consensus/qbft/2.0.0
```

Messages are broadcast to all peers except self; self-delivery is handled locally by the node.

Leader selection

```
leader_index = (duty.slot + duty.type + round) % n
```

Message schemas (protobuf-equivalent)

- QBFTMsg

  - type: int64 (1=pre_prepare, 2=prepare, 3=commit, 4=round_change, 5=decided)
  - duty: { slot:uint64, type:int32 }
  - peer_idx: int64 (0-based index in ordered membership)
  - round: int64 (>= 1)
  - value_hash: bytes[32] (optional; non-zero indicates presence)
  - prepared_round: int64 (>= 0; 0 means absent)
  - prepared_value_hash: bytes[32] (optional; non-zero indicates presence)
  - signature: bytes[65] (secp256k1 R||S||V over the hashed message without signature)

- QBFTConsensusMsg
  - msg: QBFTMsg (the primary message)
  - justification: repeated QBFTMsg (flat list; nested graphs are rejected)
  - values: repeated Any (protobuf Any wrapping concrete value payloads)

Value carriage

- The values array MUST contain an Any-wrapped payload for every non-zero hash referenced by msg.value_hash, msg.prepared_value_hash, and all justifications.
- Extra values MAY be included; order is irrelevant.

Hashing and signatures

- Hashing: compute a deterministic hash root for values and messages from deterministic protobuf encodings.
  - value_hash = HashRoot(deterministic_proto(inner_value))
  - sign HashRoot(deterministic_proto(QBFTMsg without signature))
- Signatures: secp256k1 (65-byte R||S||V). Verify by recovering the public key and matching the configured key for peer_idx.

Receiver validation rules (reject if any fails)

- msg and msg.duty are present; msg.type ∈ {1..5}
- duty.type is valid (see Duty types appendix)
- msg.round >= 1 and msg.prepared_round >= 0
- peer_idx maps to a known public key; signature recovery matches that key
- every justification has identical duty to msg.duty
- for each referenced non-zero hash in msg or justifications, a matching value exists in values and re-hashes to that hash

Round mechanics (QBFT)

Phases per round

1. Pre-Prepare: leader proposes value V (value_hash set; prepared fields absent)
2. Prepare: quorum of PREPARE(r, V) establishes prepared_round=r and prepared_value=V
3. Commit: quorum of COMMIT(r, V) decides V; DECIDED may be emitted but is optional

Round-change justification

- J1 (null-prepared): quorum of ROUND_CHANGE for target round R with prepared_round=0 and no prepared_value_hash
- J2 (prepared): quorum of PREPARE(r*, V*) proving a prepared value; leaders of R MUST carry prepared_round=r* and prepared_value_hash=H(V*) in PRE_PREPARE

Leaders sending PRE_PREPARE in round R MUST include in justification the quorum set that justified entry into R (RC quorum for J1, or PREPARE quorum for J2).

DECIDED semantics

- DECIDED messages are optional; consensus is achieved upon a quorum of COMMIT(r, V).

Transport notes

- Use libp2p protocol ID above; broadcast to all except self.
- The envelope may include multiple Any values to satisfy referenced hashes in msg and justifications.

## Field requirements by message type

- PRE_PREPARE (type=1)

  - MUST be sent by the leader of (duty, round)
  - MUST set value_hash (non-zero)
  - prepared_round and prepared_value_hash MUST be absent (0/zero-hash) unless entering R via J2; in that case, MUST set prepared_round=r* and prepared_value_hash=H(V*)
  - justification MUST include the quorum used to enter the round (RC quorum for J1, PREPARE quorum for J2)

- PREPARE (type=2)

  - MUST set value_hash (non-zero)
  - MUST NOT set prepared_round or prepared_value_hash (use 0/zero-hash)
  - justification SHOULD be empty

- COMMIT (type=3)

  - MUST set value_hash (non-zero)
  - prepared_round and prepared_value_hash MUST be absent (0/zero-hash)
  - justification MAY be empty; receivers MUST NOT require additional evidence beyond quorum of COMMITs

- ROUND_CHANGE (type=4)

  - For null-prepared J1: MUST set prepared_round=0 and omit prepared_value_hash; justification MAY be empty
  - For prepared J2: MUST set prepared_round=r* and prepared_value_hash=H(V*); justification MUST include a quorum of PREPARE(r*, V*)

- DECIDED (type=5)
  - Optional;
  - Receivers MUST tolerate presence/absence and MUST NOT rely on it for safety or liveness
