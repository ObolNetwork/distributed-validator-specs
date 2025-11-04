# Duty Scheduling Protocol

This document describes how distributed validators schedule and execute beacon chain duties, including slot timing, deadline calculation, duty resolution, and barrier coordination.

Scope:

- Slot and epoch time calculations
- Duty resolution from beacon node APIs
- Deadline computation and duty gating logic
- Epoch-based caching and memory management
- Slot offset scheduling for different duty types

Out of scope: Beacon node API implementation, consensus protocol details, signature aggregation mechanics

## Terms and Notation

- `Slot`: 12-second window during which a block may be proposed
- `Epoch`: collection of 32 slots (384 seconds)
- `Duty`: assigned validator task (attestation, proposal, sync committee message, etc.)
- `Deadline`: timestamp after which duty rewards are severely diminished
- `Duty Gating`: validation logic that rejects invalid or expired duties
- `Slot Offset`: fractional delay within a slot before triggering a duty type

## Time Structure

The beacon chain divides time into slots and epochs:

**Slot Duration**: 12 seconds (fixed)  
**Slots per Epoch**: 32 (fixed)  
**Epoch Duration**: 384 seconds (6.4 minutes)  
**Genesis Time**: Network-specific start time

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
3. Emit slot tick events every 12 seconds
4. Handle clock skew and missed slots gracefully

**Skipped Slot Handling**: If the system pauses (garbage collection, suspend), multiple slots may pass. The scheduler should jump to the actual current slot rather than processing a backlog of stale duties.

## Duty Resolution

At the start of each epoch, query the beacon node for all duties assigned to active validators in that epoch.

### Beacon Node Queries

**Attester Duties**:

```
POST /eth/v1/validator/duties/attester/{epoch}
Body: [validator_index_1, validator_index_2, ...]

Response per validator:
- pubkey, validator_index
- committee_index (0-63)
- committee_length, validator_committee_index
- slot (assigned slot for attestation)
```

**Proposer Duties**:

```
GET /eth/v1/validator/duties/proposer/{epoch}

Response per validator:
- pubkey, validator_index
- slot (assigned slot for block proposal)
```

**Sync Committee Duties**:

```
POST /eth/v1/validator/duties/sync/{epoch}
Body: [validator_index_1, validator_index_2, ...]

Response per validator:
- pubkey, validator_index
- validator_sync_committee_indices (positions in committee)
```

Only query duties for validators with `status == "active_ongoing"`. Skip validators in pending, exiting, exited, or slashed states.

### Epoch-Based Caching

Minimize beacon node queries by caching duties per epoch:

**Cache Structure**:

- Map from `(slot, duty_type)` to `{pubkey -> duty_definition}`
- Map from `epoch` to list of `(slot, duty_type)` keys for trimming
- Track last resolved epoch

**Resolution Timing**:

- First slot of epoch: resolve duties for current epoch if not already resolved
- Last slot of epoch: pre-resolve duties for next epoch (reduces latency)

**Memory Management**: After resolving epoch E, trim epoch `E-3` and earlier. Keeping the last 3 epochs allows attestation inclusion delay checks while preventing unbounded memory growth.

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

## Duty Deadlines

Each duty type has a deadline after which rewards are severely diminished or zero.

Deadlines are computed from slot start time with a safety margin for network propagation:

```
margin = slot_duration / 12  # ~1 second
deadline = slot_start_time + duty_duration + margin
```

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

For validators using MEV-boost, builder registrations must be submitted at the start of each epoch:

1. Get pre-signed builder registration for each active validator
2. Submit registrations to beacon node via `/eth/v1/validator/prepare_beacon_proposer`
3. Handle independently of duty scheduling (typically once per epoch)

This allows validators to receive MEV blocks when assigned proposer duties.
