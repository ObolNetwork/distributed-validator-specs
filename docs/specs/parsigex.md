## Partial Signature Exchange (ParSigEx) interoperability spec

This document describes the Partial Signature Exchange protocol used for exchanging partially signed duty data among distributed validator nodes.

Scope:

- Over-the-wire message shapes and fields
- Protocol identifiers and exchange patterns
- Verification and validation flows

Out of scope: cryptographic signature routines, threshold aggregation logic, transport reliability;

### Terms and notation

- n: number of participating nodes in the cluster
- t: threshold required for signature aggregation (typically ceil(2n/3))
- Duty: a validator responsibility at a specific slot (e.g., attestation, block proposal)
- ParSignedData: a partially signed duty data item containing a signature share from one node
- ParSignedDataSet: a mapping of validator public keys to their ParSignedData
- Share Index: the 0-based or 1-based index identifying which operator produced a partial signature

### Protocol identifiers (libp2p)

All messages are sent under protocol ID:

```
/charon/parsigex/2.0.0
```

### Exchange pattern

ParSigEx implements a broadcast-and-subscribe pattern:

1. **Internal storage trigger**: When a node produces a partial signature (e.g., from the validator API), it stores it in the partial signature database (ParSigDB).

2. **Broadcast phase**: The ParSigDB triggers the ParSigEx component to broadcast the partial signature set to all peers.

3. **Reception and verification**: Each peer receives the broadcast, verifies the partial signature(s), and stores them in its own ParSigDB.

4. **Threshold detection**: Once ParSigDB accumulates _threshold_ valid partial signatures for a duty, it triggers the signature aggregation component.

The exchange ensures that all nodes eventually have access to all partial signatures, enabling any node to aggregate signatures when the threshold is reached.

### Message schemas (protobuf-equivalent)

The following structures are used over the wire. The protobufs used by Charon are available [here](https://github.com/ObolNetwork/charon/tree/main/core/corepb/v1).

- ParSigExMsg

  - duty: Duty
    - slot: uint64
    - type: DutyType (int32)
  - data_set: ParSignedDataSet
    - set: map[string -> ParSignedData] // keyed by validator public key bytes

- ParSignedData
  - data: bytes // serialized SignedData (duty-type specific)
  - signature: bytes // BLS signature share
  - share_idx: int32 // operator index (0-based in protocol)

### Protocol flow

#### 1. Broadcast

When a node has a new partial signature to share:

```
for each peer in peers:
  if peer != self:
    send ParSigExMsg to peer via libp2p
```

The message contains:

- The duty being performed (slot + duty type)
- A set of partial signatures (typically one per validator the node is responsible for)

#### 2. Reception and handling

Upon receiving a `ParSigExMsg`:

1. **Parse and validate message structure**:

   - Extract `duty` from the protobuf
   - Extract `data_set` from the protobuf
   - Verify message fields are non-nil

2. **Duty gating**: Validate the duty is expected/relevant using a gater function

3. **Convert from protobuf**: Transform `ParSignedDataSet` from wire format to internal representation

4. **Verify each partial signature**:

   - For each (pubkey, ParSignedData) pair in the set:
     - Look up the public share for this validator and share index
     - Verify the BLS partial signature against the expected signing root
     - Verify the signature using Ethereum consensus layer signing rules

5. **Invoke subscribers**: If all signatures verify, call all registered subscriber callbacks with the duty and partial signature set

### Verification

Partial signature verification follows the Ethereum consensus layer signature specification:

1. **Compute signing root**:

   - Extract the message root from the SignedData (duty-type specific)
   - Compute domain = compute_domain(domain_type, fork_version, genesis_validators_root)
   - Compute signing_root = compute_signing_root(message_root, domain)

2. **Verify BLS signature**:
   - Extract the public key share for the validator at the given share_idx
   - Verify: BLS_Verify(pubkey_share, signing_root, signature_share)

The verification function is provided at ParSigEx construction time and can be customized (e.g., for testing). In production, `NewEth2Verifier` is used.

### Duty gating

Not all duties are exchanged at all times. A gater function filters which duties are accepted:

- **Always accepted**: DutyExit, DutyBuilderRegistration (lifecycle operations)
- **Conditionally accepted**: Other duty types are accepted only if corresponding work has been scheduled (e.g., DutyRandao is only expected if DutyProposer was scheduled for the same slot)

This prevents nodes from processing or storing irrelevant partial signatures.

### Properties

- **All-to-all exchange**: Every node broadcasts to every other node (n^2 messages per duty)
- **Idempotent**: Receiving the same partial signature multiple times is harmless (deduplicated in ParSigDB)
- **Best-effort delivery**: Uses libp2p direct streams with timeouts; retries are not automatic
- **Signature verification**: All received partial signatures are verified before acceptance
- **No equivocation protection**: ParSigEx itself does not prevent a node from sending different signatures for the same duty to different peers

### Interop notes

- **Protocol versioning**: The protocol ID `/charon/parsigex/2.0.0` identifies the version; future versions may use different IDs
- **Peer ordering**: Share indices and peer indices must be consistent across all nodes (typically derived from cluster lock operator order)
- **Public key encoding**: Validator public keys are BLS12-381 public keys encoded as 48-byte compressed G1 points
- **Signature encoding**: BLS signatures are 96-byte compressed G2 points
- **Message ordering**: No guaranteed ordering of messages; ParSigDB handles deduplication and threshold detection
