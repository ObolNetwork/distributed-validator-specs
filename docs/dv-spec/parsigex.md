# Partial Signature Exchange Interoperability Spec

This document describes the Partial Signature Exchange protocol used for exchanging partially signed duty data among distributed validator nodes.

Scope:

- Over-the-wire message shapes and fields
- Protocol identifiers and exchange patterns
- Verification and validation flows

Out of scope: cryptographic signature routines, threshold aggregation logic, transport reliability;

## Terms and notation

- `n`: number of participating nodes in the cluster
- `t`: threshold required for signature aggregation (typically `ceil(2n/3)`)
- `Duty`: a validator's responsibility at a specific slot (e.g., attestation)
- `ParSignedData`: a partially signed duty data item containing a signature share from one node
- `ParSignedDataSet`: a mapping of validator public keys to their ParSignedData
- `ShareIndex`: the 1-indexed share index identifying which operator produced a partial signature
- `ParSigDB`: local database storing received partial signatures for duties

## Protocol identifiers (libp2p)

All messages are sent under protocol ID:

```text
/charon/parsigex/2.0.0
```

## Exchange pattern

`ParSigEx` implements a broadcast-and-subscribe pattern:

1. **Internal storage trigger**: When a node produces a partial signature (e.g.: from the validator API), it stores it in the partial signature database (`ParSigDB`).

2. **Broadcast phase**: The `ParSigDB` triggers the `ParSigEx` component to broadcast the partial signature set to all peers.

3. **Reception and verification**: Each peer receives the broadcast, verifies the partial signature(s), and stores them in its own `ParSigDB`.

4. **Threshold detection**: Once `ParSigDB` accumulates `t` valid partial signatures for a duty, it triggers the signature aggregation component.

The exchange ensures that all nodes eventually have access to all partial signatures, enabling any node to aggregate signatures when the threshold is reached.

## Message Schemas

The following protobuf definitions are used over the wire:

- [parsigex.proto](../../proto/parsigex.proto) - ParSigEx message definitions
- [core.proto](../../proto/core.proto) - Common core type definitions (Duty, ParSignedData, ParSignedDataSet)

See the Python reference implementation: [`ParSigExMsg`](../../src/dv_spec/subspecs/parsigex/message.py#L46-L56), [`ParSignedData`](../../src/dv_spec/subspecs/parsigex/message.py#L19-L31), [`ParSignedDataSet`](../../src/dv_spec/subspecs/parsigex/message.py#L33-L43), and [`Duty`](../../src/dv_spec/types/duty.py#L27-L40).

## Protocol flow

## 1. Broadcast

When a node has a new partial signature to share, it constructs a `ParSigExMsg` containing the duty and the `ParSignedDataSet` (typically containing just the new partial signature) and broadcasts it to all peers.

## 2. Reception and handling

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

## Verification

Partial signature verification follows the Ethereum consensus layer signature specification:

1. **Compute signing root**:

   - Extract the message root from the SignedData (duty-type specific)
   - Compute domain = compute_domain(domain_type, fork_version, genesis_validators_root)
   - Compute signing_root = compute_signing_root(message_root, domain)

2. **Verify BLS signature**:
   - Extract the public key share for the validator at the given share_idx
   - Verify: BLS_Verify(pubkey_share, signing_root, signature_share)

The verification function is provided at ParSigEx construction time and can be customized (e.g., for testing). In production, `NewEth2Verifier` is used.

## Duty gating

Not all duties are exchanged at all times. A gater function filters which duties are accepted:

- **Always accepted**: DutyExit, DutyBuilderRegistration (lifecycle operations)
- **Conditionally accepted**: Other duty types are accepted only if corresponding work has been scheduled (e.g., DutyRandao is only expected if DutyProposer was scheduled for the same slot)

This prevents nodes from processing or storing irrelevant partial signatures.

## Properties

- **All-to-all exchange**: Every node broadcasts to every other node
- **Idempotent**: Receiving the same partial signature multiple times is harmless (deduplicated in ParSigDB)
- **Best-effort delivery**: Uses libp2p direct streams with timeouts; retries are not automatic
- **Signature verification**: All received partial signatures are verified before acceptance
- **No equivocation protection**: ParSigEx itself does not prevent a node from sending different signatures for the same duty to different peers

## Interop notes

- **Protocol versioning**: The protocol ID `/charon/parsigex/2.0.0` identifies the version; future versions may use different IDs
- **Peer ordering**: Share indices and peer indices must be consistent across all nodes (typically derived from cluster lock operator order)
- **Public key encoding**: Validator public keys are BLS12-381 public keys encoded as 48-byte compressed G1 points
- **Signature encoding**: BLS signatures are 96-byte compressed G2 points
- **Message ordering**: No guaranteed ordering of messages; ParSigDB handles deduplication and threshold detection
