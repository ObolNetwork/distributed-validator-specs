# Beacon Broadcast Interoperability Spec

This document describes the final stage of the duty signing path: submitting the aggregated, fully signed duty data to the beacon node.

Scope:

- Which duty types are submitted to the beacon chain and which terminate locally
- The endpoint used per duty type
- Error handling that a conforming implementation must reproduce

Out of scope: the beacon node API itself, signature aggregation (see [Signature Aggregation](sigagg.md)), duty scheduling (see [Duty Scheduling](duty-scheduling.md)).

> **Naming note**: this is Charon's `core/bcast`, the last component of the duty
> workflow. It is **not** the same as `dkg/bcast`, the two-phase signed
> broadcast used during DKG ceremonies, which this spec calls
> [Reliable Broadcast](reliable-broadcast.md).

## Position in the Workflow

```
parsigdb ──(threshold)──▶ sigagg ──▶ bcast ──▶ beacon node
```

Broadcast is triggered by [signature aggregation](sigagg.md) completing for a duty. Its input is a set of fully signed duty objects keyed by validator public key — one entry per validator that reached the threshold for that duty.

Every node in the cluster runs this stage independently and submits the same aggregated signature. Duplicate submissions from `n` nodes are expected: the beacon node deduplicates them, and the resulting on-chain artifact is identical regardless of which node's submission arrived first. An implementation MUST NOT try to elect a single submitter — doing so introduces a single point of failure the design exists to avoid.

## Duty Types

| Duty type                | Destination                                            |
| ------------------------ | ------------------------------------------------------ |
| Attester                 | `POST /eth/v2/beacon/pool/attestations`                |
| Proposer                 | `POST /eth/v2/beacon/blocks` or `blinded_blocks`       |
| Aggregator               | `POST /eth/v2/validator/aggregate_and_proofs`          |
| SyncMessage              | `POST /eth/v1/beacon/pool/sync_committees`             |
| SyncContribution         | `POST /eth/v1/validator/contribution_and_proofs`       |
| VoluntaryExit            | `POST /eth/v1/beacon/pool/voluntary_exits`             |
| Randao                   | None — terminates locally                              |
| PrepareAggregator        | None — terminates locally                              |
| PrepareSyncContribution  | None — terminates locally                              |
| BuilderRegistration      | None — submitted by the scheduler instead              |
| BuilderProposer          | Rejected — deprecated by v3 block proposals            |

The four duty types with no destination are the ones whose aggregated signature is consumed *inside* the cluster rather than by the beacon chain:

- **Randao** is an input to block proposal, not an artifact of its own.
- **PrepareAggregator** and **PrepareSyncContribution** produce selection proofs, which are a DVT concept: the aggregated proof is returned to the VC through the [ValidatorAPI](validatorapi.md) selection endpoints so it can evaluate `is_aggregator()`. The beacon chain never sees them.
- **BuilderRegistration** is submitted by the [scheduler](duty-scheduling.md#builder-registration) from the pre-signed registrations in the cluster lock, on an epoch cadence, rather than from this path.

Reaching this stage with an unrecognised duty type is an error, not a no-op.

## Proposals

A proposal carries a blinded flag decided during consensus, and the flag selects the endpoint: a blinded proposal is converted to its blinded representation and submitted to the blinded endpoint, a full one to the normal endpoint. Which of the two the cluster produces is governed by the proposal types agreed through [InfoSync](infosync.md).

Unlike the other duty types, a proposal set contains exactly one validator — a slot has one proposer.

## Error Handling

- **Attestations**: a beacon node error containing `PriorAttestationKnown` is treated as success. Some beacon nodes are not idempotent about attestation submission, and because every node in the cluster submits, this response is the normal outcome for all but the first submitter. Treating it as a failure produces spurious duty failures on healthy clusters.
- **Voluntary exits**: submitted per validator, and every validator in the set is attempted even if one fails; the last error is returned. An exit is a one-shot, irreversible operation, so a single failure must not skip the others.
- **All other duty types**: an error from the beacon node fails the duty. There is no retry at this stage; the duty is failed and reported.

## Interop Notes

- **All nodes submit.** Expect and tolerate duplicate-submission responses from the beacon node rather than treating them as errors.
- **`PriorAttestationKnown` is success**, not failure.
- **Selection proofs never reach the beacon chain.** Submitting them is a protocol error, not a harmless extra.
- **Builder registrations do not flow through this path**, even though they are a duty type with a threshold signature.
