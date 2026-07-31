# Partial Signature Exchange Interoperability Spec

This document describes the Partial Signature Exchange protocol used for exchanging partially signed duty data among distributed validator nodes.

Scope:

- Over-the-wire message shapes and fields
- Protocol identifiers and exchange patterns
- Verification and validation flows

Out of scope: cryptographic signature routines, transport reliability, and threshold aggregation — see [Signature Aggregation](sigagg.md) for the threshold trigger and aggregate construction.

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

4. **Threshold detection**: Once `ParSigDB` accumulates exactly `t` valid partial signatures over matching data for a duty, it triggers the signature aggregation component. See [Signature Aggregation](sigagg.md#threshold-trigger) for the precise condition.

The exchange ensures that all nodes eventually have access to all partial signatures, enabling any node to aggregate signatures when the threshold is reached.

## Message Schemas

The following protobuf definitions are used over the wire:

- [parsigex.proto](https://github.com/ObolNetwork/distributed-validator-specs/blob/main/proto/parsigex.proto) - ParSigEx message definitions
- [core.proto](https://github.com/ObolNetwork/distributed-validator-specs/blob/main/proto/core.proto) - Common core type definitions (Duty, ParSignedData, ParSignedDataSet)

See the Python reference implementation: [`ParSigExMsg`, `ParSignedData` and `ParSignedDataSet`](https://github.com/ObolNetwork/distributed-validator-specs/blob/main/src/dv_spec/subspecs/parsigex/message.py), and [`Duty`](https://github.com/ObolNetwork/distributed-validator-specs/blob/main/src/dv_spec/types/duty.py).

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

4. **Verify each partial signature**, passing the **authenticated libp2p sender** to the verifier along with the duty, pubkey and data:

   - For each (pubkey, ParSignedData) pair in the set:
     - Look up the public share for this validator and share index
     - Verify the BLS partial signature against the expected signing root
     - Verify the signature using Ethereum consensus layer signing rules

5. **Invoke subscribers**: If all signatures verify, call all registered subscriber callbacks with the duty and partial signature set

The verifier is supplied at construction time, and the two callers verify
differently — see [Sender binding](#sender-binding). The handler must pass the
sender regardless of which verifier is installed.

## Sender binding

The DKG lock-hash exchange binds every received partial signature to its
authenticated sender: **a peer may only contribute partial signatures under its
own assigned share index**, so it cannot deposit a signature into another
operator's slot. This is the same check the node signature exchange applies to
claimed peer indices ([`verify_node_sig_msg`](https://github.com/ObolNetwork/distributed-validator-specs/blob/main/src/dv_spec/subspecs/dkg/node_sigs.py)),
expressed over share indices — see [`verify_peer_share_idx`](https://github.com/ObolNetwork/distributed-validator-specs/blob/main/src/dv_spec/subspecs/parsigex/helpers.py).

The expected index comes from a **peer ID to assigned share index map**, not from
the sender's position in the peer list. Those differ: after operators are removed
the remaining ones keep their original share indices, so the assignment is no
longer contiguous (see [share index compaction](dkg-cluster-edits.md#remove-operators)).
An implementation that computed the expected index as *peer position + 1* would
reject valid signatures on any cluster that has had an operator removed.

Whether the binding applies depends on the caller, and the asymmetry is
deliberate:

| Caller | Binds to sender? | Why |
| ------ | ---------------- | --- |
| DKG lock-hash exchange | Yes | Signing roots are not known while the exchange runs, so cryptographic verification is deferred until aggregation. The authenticated sender is the only thing a receiver can check at reception time. |
| Core workflow (duties) | No | Partial signatures are already verified against the public share for the claimed share index, which binds them to a share cryptographically. A receiver that enforced the sender binding here would reject partial signatures Charon accepts. |

A participating peer with no valid assigned share index is a configuration
error, and it must be rejected when the exchange is constructed rather than at
reception. Such a peer's partial signatures are rejected as coming from an
unknown peer, which does not surface as a validation failure — the exchange
simply never reaches its threshold and times out.

[`test_vectors/parsigex_sender_binding.json`](https://github.com/ObolNetwork/distributed-validator-specs/blob/main/test_vectors/parsigex_sender_binding.json)
carries charon's own accept/reject table for both checks. Its peer map assigns
share index 4 to the *second* peer, which is the case that separates a
map-based implementation from a position-based one: a position-derived
expectation of 2 accepts what charon rejects and rejects what it accepts.

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

Not all duties are exchanged at all times. A gater function filters which duties are accepted based on timing:

- **Future epoch limit**: Duties are only accepted if they fall within the current epoch or the next 2 epochs (total 3-epoch window)
- **Invalid duty types**: Duties with invalid duty types are rejected
- **No past duty rejection**: The gater does not reject duties from past epochs (that is handled separately by the Deadliner)

This prevents nodes from processing or storing irrelevant partial signatures from the distant future, which could cause memory exhaustion or processing of duties from peers with incorrect clocks.

Note: `DutyExit` and `DutyBuilderRegistration` never expire (handled in Deadliner), but they are still subject to the same future epoch gating as other duty types.

## Properties

- **All-to-all exchange**: Every node broadcasts to every other node
- **Idempotent**: Receiving the same partial signature multiple times is harmless (deduplicated in ParSigDB)
- **Best-effort delivery**: Uses libp2p direct streams with timeouts; retries are not automatic
- **Signature verification**: All received partial signatures are verified before acceptance
- **Sender-bound share indices in DKG**: In the DKG lock-hash exchange a peer may only contribute under its own assigned share index (see [Sender binding](#sender-binding)); the core workflow relies on public-share verification instead
- **No equivocation protection**: ParSigEx itself does not prevent a node from sending different signatures for the same duty to different peers. Sender binding constrains *which share index* a peer may sign under, not how many different values it may send under that index

## Interop notes

- **Protocol versioning**: The protocol ID `/charon/parsigex/2.0.0` identifies the version; future versions may use different IDs
- **Peer ordering**: Share indices and peer indices must be consistent across all nodes (typically derived from cluster lock operator order). They are not interchangeable: a share index assignment can be non-contiguous after operator removal, so the DKG exchange's sender binding resolves the expected index through a peer map rather than by peer position
- **Public key encoding**: Validator public keys are BLS12-381 public keys encoded as 48-byte compressed G1 points
- **Signature encoding**: BLS signatures are 96-byte compressed G2 points
- **Message ordering**: No guaranteed ordering of messages; ParSigDB handles deduplication and threshold detection
