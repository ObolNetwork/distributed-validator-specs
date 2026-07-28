# Duty Scheduling Protocol

This document describes how distributed validators schedule and execute beacon chain duties, including slot timing, deadline calculation, duty resolution, and barrier coordination.

Scope:

- Slot and epoch time calculations
- Duty resolution from the beacon node
- Deadline computation and duty gating logic
- Epoch-based caching and memory management
- Slot offset scheduling for different duty types

Out of scope: Beacon node API implementation, consensus protocol details, signature aggregation mechanics

## Terms and Notation

- `Slot`: time window during which a block may be proposed 
- `Epoch`: collection of slots
- `Duty`: assigned validator task (attestation, proposal, sync committee message, etc.)
- `Deadline`: timestamp after which the DV stops accepting inputs for a duty
- `Duty Gating`: validation logic that rejects invalid or expired duties
- `Slot Offset`: fractional delay within a slot before triggering a duty type (i.e.: 1/3 slot time for attestations)

## Time Structure

The beacon chain divides time into slots and epochs. These values are configurable per network and queried from the beacon node:

**Ethereum Mainnet:**
- **Slot Duration**: 12 seconds
- **Slots per Epoch**: 32
- **Epoch Duration**: 384 seconds (6.4 minutes)

**Genesis Time**: Network-specific start time queried from the beacon node

**Current Slot Calculation**:

```python
current_slot = (current_time - genesis_time) // slot_duration
slot_epoch = slot_number // slots_per_epoch
slot_start_time = genesis_time + (slot_number * slot_duration)
```

## Real-Time Slot Tracking

DVs track slots in real-time to trigger duties at precise moments:

1. Fetch genesis time and slot configuration from beacon node at startup
2. Compute current slot from wall clock
3. Emit slot tick events at each slot boundary (interval equals slot duration)
4. Handle clock skew and missed slots gracefully

**Skipped Slot Handling**: If the system pauses (garbage collection, suspend), multiple slots may pass. The DV should jump to the actual current slot rather than processing a backlog of stale duties.

## Duty Resolution

At the start of each epoch, the DV queries the beacon node for all duties assigned to its active validators, using the standard Beacon API endpoints.
However, some duties are derived from these responses.

### Derived Duties

Some duties are computed from beacon node responses:

**Aggregator Duty**: When an attester duty is scheduled, also schedule an aggregator duty for the same slot. Selection is determined later via selection proof calculation.

**Sync Contribution Duty**: For validators in sync committees, create contribution duties for all slots in the sync committee period (spans entire epoch).

## Slot Offset Scheduling

Duties trigger at specific fractions of the slot duration to allow time for block propagation and processing.

| Duty Type               | Offset | Timing Description                    |
| ----------------------- | ------ | ------------------------------------- |
| Proposer                | 0s     | Start of slot                         |
| Randao                  | 0s     | Start of slot                         |
| Attester                | **4s** | 1/3 into slot (wait for block)        |
| SyncMessage             | 0s     | Start of slot                         |
| PrepareAggregator       | 0s     | Start of slot                         |
| Aggregator              | **8s** | 2/3 into slot (collect attestations)  |
| SyncContribution        | **8s** | 2/3 into slot (collect sync messages) |
| PrepareSyncContribution | 0s     | Start of slot                         |
| InfoSync                | 0s     | Start of slot                         |
| BuilderRegistration     | 0s     | No specific timing constraint         |
| VoluntaryExit           | 0s     | No specific timing constraint         |

**Offset Calculation**:

```
attester_offset = slot_duration / 3           # 4 seconds
aggregator_offset = slot_duration * 2 / 3     # 8 seconds
sync_contribution_offset = slot_duration * 2 / 3
```

**Rationale**:

- **Attestations**: Allow 4 seconds for block propagation, validation, and fork choice update before attesting
- **Aggregations**: Wait 8 seconds for individual messages to arrive before aggregating
- **Proposals**: Must start immediately to maximize time for block creation, signing, and propagation

### Slot Offsets Feed the Consensus Round Timer

These offsets are not local to the scheduler. The [QBFT](consensus.md) eager double linear round timer derives its first-round deadline from the slot start time plus the **same** duty offset:

```
slot_start   = genesis_time + slot * slot_duration
duty_start   = slot_start + slot_offset(duty_type)
deadline(r)  = duty_start + linear_round_timeout(r)
```

The offsets used there are identical to the table above — `1/3` for attester, `2/3` for aggregator and sync contribution, `0` for everything else — precisely so that round deadlines line up with when consensus actually starts.

Two consequences follow, and both are interop-critical:

- Deadlines are derived from genesis time and the slot number, not from each node's local `now()`. Every node therefore computes the same absolute deadline for a given (slot, duty, round), independent of when it started its instance. A node that measures from local arrival time drifts out of round alignment with its peers, and the divergence grows with each round change.
- Changing a slot offset in the scheduler without changing it in the timer misaligns round deadlines by that difference. The two tables are one table.

An implementation that has not yet obtained genesis time and slot duration falls back to local-clock deadlines. That fallback is not interoperable and is only intended for tests.

## Duty Deadlines

Each duty type has a deadline after which rewards are severely diminished or zero.

Deadlines are computed from slot start time with a safety margin for network propagation:

```text
margin = slot_duration / 12  # Scales with slot duration
deadline = slot_start_time + duty_duration + margin
```

**Ethereum Mainnet Examples (12s slots):**

| Duty Type               | Duration | Total Deadline | Notes                               |
| ----------------------- | -------- | -------------- | ----------------------------------- |
| Proposer                | 4s       | ~5s            | 1/3 slot + margin                   |
| Randao                  | 4s       | ~5s            | Same as proposer (part of proposal) |
| Attester                | **24s**  | ~25s           | 2 slots + margin                    |
| Aggregator              | 24s      | ~25s           | 2 slots + margin (same as attest)   |
| PrepareAggregator       | 24s      | ~25s           | Must complete before aggregator     |
| SyncMessage             | **8s**   | ~9s            | 2/3 slot + margin                   |
| SyncContribution        | 12s      | ~13s           | 1 slot + margin                     |
| PrepareSyncContribution | 12s      | ~13s           | Must complete before contribution   |
| InfoSync                | 12s      | ~13s           | 1 slot + margin                     |
| BuilderRegistration     | **∞**    | Never expires  | Can be submitted anytime            |
| VoluntaryExit           | **∞**    | Never expires  | Can be submitted anytime            |

## Duty Gating

Duty gating prevents processing duties that are invalid, too far in the future, or already expired.

**Future Epoch Limit**: Only allow duties within current epoch and next 2 epochs. This prevents:

- Memory exhaustion from malicious far-future duties
- Processing duties from peers with incorrect clocks
- Unbounded cache growth

The 2-epoch window allows pre-fetching next epoch duties while maintaining safety bounds.

**Past Duty Handling**: Deadline tracking (separate from gating) checks if duties are already expired. This separation allows duties from slightly in the past (within same slot) while rejecting truly expired duties.

## Chain Reorganization Handling

If the beacon chain reorganizes to an earlier epoch, cached duties may become invalid. Implementations should:

1. Detect reorg event from beacon node
2. If reorg affects cached epochs, clear entire duty cache
3. Force re-resolution of current epoch duties
4. Log event for monitoring

This ensures validators don't attest or propose based on stale fork choice.

## Builder Registration

For validators using the builder API, the DV submits builder registrations itself rather than relaying the VC's — see the [ValidatorAPI conformance checklist](validatorapi.md#conformance-checklist), where `register_validator` is accepted and discarded. The registrations are pre-generated and signed by the whole cluster during the [DKG](dkg-frost.md) and stored in the [cluster lock](cluster-files.md), so no signing is needed at submission time.

Submission rules:

1. Only when the builder API is enabled.
2. At slot 0 of each epoch, and at most once per epoch — a successful submission records the epoch, and a failed one is retried at the next epoch boundary.
3. Delayed to 3/4 into that slot, and performed asynchronously, so it neither collides with duty triggering nor adds beacon node load at the slot boundary.
4. Take the pre-signed registration for each active validator from the cluster lock and submit them to `POST /eth/v1/validator/register_validator` on the beacon node.

This is independent of duty scheduling: registrations are not duties, have no deadline, and are not routed through consensus.
