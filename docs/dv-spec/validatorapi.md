# ValidatorAPI: Validator Client Interface

## Overview

The ValidatorAPI component serves as a **reverse proxy** and **middleware layer** between the connected downstream Validator Client (VC) and upstream Beacon Nodes (BNs). It implements the [Ethereum Beacon Node API](https://ethereum.github.io/beacon-APIs/#/) while adding distributed validator logic for signing operations.

**Key Features:**

1. **Endpoint Interception**: Intercepts validator-specific endpoints to implement distributed validator logic
2. **Endpoint Proxying**: Forwards beacon chain queries directly to upstream beacon node unchanged
3. **Key Translation**: Maps between DV root public keys and share public keys bidirectionally
4. **Signature Verification**: Verifies partial signatures from VCs before accepting into signing workflow
5. **Consensus Coordination**: Blocks unsigned data requests until [consensus](consensus.md) completes

## Public Key Mapping

A critical aspect of the middleware is the bidirectional mapping between public keys. A DV instance typically manages **multiple distributed validators**, each with its own set of keys:

- **DV Root Public Keys**: Each distributed validator has its own aggregate BLS public key (one per validator managed by the cluster)
- **Public Shares**: For each distributed validator, each node has a threshold BLS public key share (N shares per validator, where N = number of nodes in cluster)

### Example: 3-node cluster with 2 validators

```
Validator 1 (DV Root Key: 0xabc...):
  - Node 1 share: 0x111...
  - Node 2 share: 0x222...
  - Node 3 share: 0x333...

Validator 2 (DV Root Key: 0xdef...):
  - Node 1 share: 0x444...
  - Node 2 share: 0x555...
  - Node 3 share: 0x666...
```

This mapping is configured during [DKG](pedersen-dkg.md) and stored in the [cluster lock file](cluster-files.md), with each node knowing:

- All DV root public keys for every validator in the cluster
- This node's public share for each validator (based on node index)
- The bidirectional mapping between shares and root keys

## Intercepted Endpoints

ValidatorAPI intercepts and handles the following validator API endpoints to implement distributed validator logic:

### Duty Endpoints

- `POST /eth/v1/validator/duties/attester/{epoch}` - Attester duties
- `GET /eth/v1/validator/duties/proposer/{epoch}` - Proposer duties
- `GET /eth/v1/validator/duties/sync/{epoch}` - Sync committee duties

**Request Transformation:**

- **Incoming request**: No modification to request body (validator indices remain unchanged)
- **Response transformation**: Replace all DV root public keys with this node's public shares in the duty response
  - For `AttesterDuty`: `duty.PubKey` (root) → `pubshare` (this node's share)
  - For `ProposerDuty`: `duty.PubKey` (root) → `pubshare` (this node's share, or skip if unknown validator since it may return all proposers if validator indices is empty)
  - For `SyncCommitteeDuty`: `duty.PubKey` (root) → `pubshare` (this node's share)

### Attestation Endpoints

- `GET /eth/v1/validator/attestation_data` - Unsigned attestation data
- `POST /eth/v2/validator/aggregate_attestation` - Aggregate attestation
- `POST /eth/v1/validator/aggregate_and_proofs` - Submit aggregated attestations (deprecated v1)
- `POST /eth/v2/validator/aggregate_and_proofs` - Submit aggregated attestations

**Request Transformation:**

**`GET /eth/v1/validator/attestation_data`:**

- **Request**: Query parameters unchanged (slot, committee_index)
- **Response**: No key transformation (attestation data contains no public keys)
- **Additional processing**: Blocks until nodes agree on attestation data via [consensus](consensus.md)

**`POST /eth/v2/validator/aggregate_attestation`:**

- **Request**: Query parameters unchanged (attestation_data_root, slot, committee_index)
- **Response**: No key transformation required
- **Additional processing**: Blocks until nodes agree on aggregate attestation data via [consensus](consensus.md)

**`POST /eth/v2/validator/aggregate_and_proofs` (submit):**

- **Request body transformation**:
  1. Extract aggregator public key from `AggregateAndProof.aggregator_index`
  2. Map public share → DV root public key 
  3. Verify selection proof signature (inner signature on contribution)
  4. Verify partial signature on outer against public share
- **No response** (204 on success)

### Block Proposal Endpoints

- `GET /eth/v1/validator/blinded_blocks/{slot}` - Unsigned blinded block (deprecated)
- `GET /eth/v2/validator/blinded_blocks/{slot}` - Unsigned blinded block (deprecated)
- `GET /eth/v3/validator/blocks/{slot}` - Unsigned block (current)
- `POST /eth/v1/beacon/blocks` - Submit signed block
- `POST /eth/v2/beacon/blocks` - Submit signed block
- `POST /eth/v1/beacon/blinded_blocks` - Submit signed blinded block
- `POST /eth/v2/beacon/blinded_blocks` - Submit signed blinded block

**Request Transformation:**

**`GET /eth/v3/validator/blocks/{slot}` (request unsigned block):**

- **Request query parameters**:
  - `randao_reveal`: Public share signature from VC (partial RANDAO)
  - `graffiti`: Unchanged
  - `builder_boost_factor`: Set to max if builder enabled
- **RANDAO processing**:
  1. Extract RANDAO reveal signature from query
  2. Create `ParSignedData` for `DutyRandao` with signature
  3. Verify partial RANDAO signature against public share
  4. Store RANDAO partial signature for aggregation
- **Response**: No key transformation in block body
- **Additional processing**: Blocks until nodes agree on proposal data via [consensus](consensus.md)

**`POST /eth/v2/beacon/blocks` (submit signed block):**

- **Request body transformation**:
  1. Extract proposer index from block
  2. Retrieve DV root public key from duty definitions
  3. Fetch unsigned block for anti-slashing check
  4. Verify signed block matches unsigned block (anti-slashing)
  5. Extract VC's partial signature on block
  6. Verify partial signature against this node's public share
- **No response** (204 on success)

**`POST /eth/v2/beacon/blinded_blocks` (submit signed blinded block):**

- Same transformation as regular blocks above

**Implementation Details:**

- RANDAO reveal is processed separately before block request
- Block matching prevents VCs from signing different block data

### Sync Committee Endpoints

- `GET /eth/v1/validator/sync_committee_contribution` - Unsigned sync committee contribution
- `POST /eth/v1/validator/contribution_and_proofs` - Submit sync committee contributions
- `POST /eth/v1/validator/sync_committee_messages` - Submit sync committee messages

**Request Transformation:**

**`POST /eth/v1/validator/sync_committee_messages` (submit sync messages):**

- **Request body transformation**:
  1. Extract validator index from each sync committee message
  2. Map validator index → DV root public key
  3. Create `ParSignedData` for sync committee message
  4. Verify partial signature against this node's public share
- **No response** (204 on success)

**`GET /eth/v1/validator/sync_committee_contribution`:**

- **Request**: Query parameters unchanged (slot, subcommittee_index, beacon_block_root)
- **Response**: No key transformation in contribution data
- **Additional processing**: Blocks until nodes agree on sync contribution data via [consensus](consensus.md)

**`POST /eth/v1/validator/contribution_and_proofs` (submit aggregated contributions):**

- **Request body transformation**:
  1. Extract aggregator public key from contribution
  2. Map public share → DV root public key using validator index
  3. Verify selection proof signature (inner signature on contribution) using public share
  4. Create `ParSignedData` for outer signature on `ContributionAndProof`
  5. Verify partial outer signature against public share
- **No response** (204 on success)

**Implementation Details:**

- Similar pattern to attestation aggregation (inner + outer signatures)

### Selection & Registration Endpoints

- `POST /eth/v1/validator/beacon_committee_selections` - Beacon committee selections
- `POST /eth/v1/validator/sync_committee_selections` - Sync committee selections
- `POST /eth/v1/validator/register_validator` - Builder registration (returns 200 OK, no processing)
- `POST /eth/v1/validator/prepare_beacon_proposer` - Fee recipient registration (returns 200 OK, no processing)

**Request Transformation:**

**`POST /eth/v1/validator/beacon_committee_selections`:**

- **Request body**: List of selections with public shares and slots
- **Processing**:
  1. For each selection, map public share → DV root public key
  2. Query duty definitions to verify eligibility
  3. Create `DutyPrepareAggregator` for each selection
  4. Sign selection proof with partial signature
  5. Exchange and aggregate selection proofs
- **Response transformation**: Return aggregated selection proofs to VC

**`POST /eth/v1/validator/sync_committee_selections`:**

- **Request body**: List of sync selections with public shares
- **Processing**:
  1. For each selection, map public share → DV root public key
  2. Create `DutyPrepareSyncContribution` for selection
  3. Sign selection proof with partial signature
  4. Exchange and aggregate selection proofs
- **Response transformation**: Return aggregated selection proofs to VC

**`POST /eth/v1/validator/register_validator`:**

- **Request**: Accepted but ignored (no processing)
- **Response**: Returns success (200) without processing
- **Rationale**: Builder registrations are scheduled and submitted automatically (not via VC requests). The endpoint returns 200 OK to maintain compatibility with VCs, but the submissions are ignored.
- **Actual submission**: Pre-generated builder registrations from cluster lock are scheduled for submission:
  - At startup (for all DVs in cluster)
  - At the first slot of every epoch

**`POST /eth/v1/validator/prepare_beacon_proposer`:**

- **Request**: Accepted but ignored (no processing)
- **Response**: Returns success (200) without processing
- **Rationale**: Fee recipients configured in cluster lock during DKG

**Implementation Details:**

- Selection proofs allow VCs to determine if they should aggregate
- Builder registrations are pre-generated in cluster lock and scheduled for automatic submission
- Fee recipient preparation is a no-op to prevent VC misconfiguration

### Metadata Endpoints

- `GET /eth/v1/node/version` - Node version (returns DV version)
- `GET /eth/v1/beacon/states/{state_id}/validators` - Get validators
- `GET /eth/v1/beacon/states/{state_id}/validators/{validator_id}` - Get validator

**Request Transformation:**

**`GET /eth/v1/node/version`:**

- **Request**: No parameters
- **Response**: Returns DV version string instead of beacon node version
- **No key transformation**

**`GET /eth/v1/beacon/states/{state_id}/validators`:**

- **Request parameters**:
  - Can specify validator IDs as public keys (public shares) or indices
  - Query parameters: `id` array with pubkeys or indices
  - POST body: `ids` array (alternative to query params)
- **Request transformation**:
  1. If IDs are public shares (0x-prefixed), map each share → DV root public key
  2. Query beacon node with DV root public keys
  3. Supports caching - checks validator cache before querying BN
- **Response transformation**:
  1. For each validator in response, check if it's a cluster validator
  2. If cluster validator: `validator.PublicKey` (root) → `pubshare` (this node's share)
  3. If not cluster validator: leave unchanged (ignoreNotFound=true for "all validators" queries)
- **Returns**: Modified validator set with public shares for cluster validators

**`GET /eth/v1/beacon/states/{state_id}/validators/{validator_id}`:**

- **Request**: Single validator ID (public share or index)
- **Request transformation**: Same as multi-validator endpoint above
- **Response transformation**: Replace validator public key with public share if cluster validator
- **Returns**: Single validator with public share

**Implementation Details:**

- Validator queries support both pubkey and index lookups
- Caching optimizes repeated validator queries
- Non-cluster validators pass through unchanged for compatibility

### Deprecated Endpoints (Return 404)

- `GET /eth/v1/validator/aggregate_attestation` - Use v2
- `GET /teku_proposer_config` - Teku-specific
- `GET /proposer_config` - Teku-specific

## Proxied Endpoints

All other beacon API endpoints are **reverse-proxied** directly to the upstream beacon node without modification, including:

- Chain state queries (`/eth/v2/beacon/blocks/*`, `/eth/v2/beacon/states/*`)
- Validator queries (`/eth/v1/beacon/states/{state_id}/validators`)
- Network information (`/eth/v1/node/syncing`, `/eth/v1/node/peers`)
- Configuration (`/eth/v1/config/spec`, `/eth/v1/config/fork_schedule`)
- Genesis information (`/eth/v1/beacon/genesis`)
- Event streams (`/eth/v1/events`)
- All other standard beacon node API endpoints

## Duty Workflows

### Attestation Duty Flow

```
┌──────────────┐
│ Validator    │
│ Client (VC)  │
└──────┬───────┘
       │
       │ 1. GET /eth/v1/validator/attestation_data
       │    ?slot=X&committee_index=Y
       │
       ▼
┌──────────────────────────────────────────────────────────────┐
│                      ValidatorAPI                            │
│                                                              │
│  ┌────────────────────────────────────────────────────┐      │
│  │ AttestationData(slot, commIdx)                     │      │
│  │   └─> AwaitAttestation(slot, commIdx) ─────────┐   │      │
│  └────────────────────────────────────────────────┼───┘      │
└─────────────────────────────────────────────────┬─┼──────────┘
                                                  │ │
                        Blocks until available    │ │
                                                  │ │
                                                  ▼ │
┌───────────────────────────────────────────────────┼──────────┐
│                      DutyDB                       │          │
│                                                   │          │
│  ┌───────────────────────────────────────────┐    │          │
│  │ Store(DutyAttester, UnsignedDataSet)      │◄───┘          │
│  │   - Stores attestation data per (slot,    │               │
│  │     committee_index)                      │               │
│  │   - Resolves pending queries              │               │
│  └───────────────────────────────────────────┘               │
└──────────────────────────────────────────────────────────────┘


   ┌──────────────┐
   │ Validator    │
   │ Client (VC)  │
   └──────┬───────┘
          │
          │ 2. POST /eth/v2/validator/attestations
          │    Body: [Attestation{data, signature, ...}]
          │
          ▼
   ┌─────────────────────────────────────────────────────────────┐
   │                      ValidatorAPI                           │
   │                                                             │
   │  ┌────────────────────────────────────────────────────┐     │
   │  │ SubmitAttestations(attestations)                   │     │
   │  │   1. Extract pubkey via pubKeyByAttestation()      │     │
   │  │   2. Create ParSignedData (partial signature)      │     │
   │  │   3. verifyPartialSig() with share public key      │─────┼──┐
   │  │   4. Call subscribers with ParSignedDataSet        │     │  │
   │  └────────────────────────────────────────────────────┘     │  │
   └───────────────────────────────────────────────┬─────────────┘  │
                                                   │                │
                                                   │ Stores         │ Verification
                                                   ▼                │ Failure
   ┌──────────────────────────────────────────────────────────┐     │
   │                    ParSigDB                              │     │
   │  - Stores partial signatures                             │     │
   │  - [ParSigEx](parsigex.md) exchanges signatures          │     │
   │  - SigAgg aggregates to full signature                   │     │
   │  - Broadcaster submits to beacon node                    │     │
   └──────────────────────────────────────────────────────────┘     │
                                                                    │
   ┌──────────────────────────────────────────────────────────┐     │
   │                 Error Response                           │◄────┘
   │  Returns 400/500 to VC if verification fails             │
   └──────────────────────────────────────────────────────────┘
```

### Block Proposal Duty Flow

```
┌──────────────┐
│ Validator    │
│ Client (VC)  │
└──────┬───────┘
       │
       │ 1. GET /eth/v3/validator/blocks/{slot}
       │    ?randao_reveal=0x...&graffiti=0x...
       │
       ▼
┌──────────────────────────────────────────────────────────────┐
│                      ValidatorAPI                            │
│                                                              │
│  ┌────────────────────────────────────────────────────┐      │
│  │ Proposal(slot, randao, graffiti)                   │      │
│  │                                                    │      │
│  │   A. Store RANDAO as ParSignedData                 │      │
│  │      (DutyRandao, partial signature)               │──────┼──┐
│  │                                                    │      │  │
│  │   B. AwaitProposal(slot) ──────────────────────┐   │      │  │
│  │      (blocks until block available)            │   │      │  │
│  └────────────────────────────────────────────────┼───┘      │  │
└─────────────────────────────────────────────────┬─┼──────────┘  │
                                                  │ │             │
                        Blocks until available    │ │             │
                                                  │ │             │
                                                  ▼ │             │
┌───────────────────────────────────────────────────┼────────┐    │
│                      DutyDB                       │        │    │
│  - Stores unsigned blocks                         │        │    │
│  - Retrieved after consensus completes            │◄───────┘    │
└───────────────────────────────────────────────────────────┘     │
                                                                  │
                                                  Stores RANDAO   │
                                                  partial sig     │
                                                        │         │
                                                        ▼         │
┌──────────────────────────────────────────────────────────┐      │
│  ParSigDB -> ParSigEx -> SigAgg -> AggSigDB              │      │
│  (RANDAO aggregation happens before block fetch)         │      │
└──────────────────────────────────────────────────────────┘      │
                                                                  │
   ┌──────────────┐                                               │
   │ Validator    │                                               │
   │ Client (VC)  │                                               │
   └──────┬───────┘                                               │
          │                                                       │
          │ 2. POST /eth/v2/beacon/blocks                         │
          │    Body: SignedBeaconBlock{message, signature}        │
          │                                                       │
          ▼                                                       │
   ┌──────────────────────────────────────────────────────────┐   │
   │                  ValidatorAPI                            │   │
   │                                                          │   │
   │  SubmitProposal(signedBlock)                             │   │
   │   1. Get pubkey from duty definitions                    │   │
   │   2. AwaitProposal(slot) to get unsigned block           │   │
   │   3. Verify signed matches unsigned (anti-slashing)      │───┼──┐
   │   4. Create ParSignedData (partial signature)            │   │  │
   │   5. verifyPartialSig() with share public key            │───┼──┼─┐
   │   6. Exchange, aggregate, broadcast                      │   │  │ │
   └──────────────────────────────────────────────────────────┘   │  │ │
                                                                  │  │ │
   ┌──────────────────────────────────────────────────────────┐   │  │ │
   │         Error Response (Mismatch)                        │◄──┘  │ │
   │  Returns error if signed block doesn't match unsigned    │      │ │
   └──────────────────────────────────────────────────────────┘      │ │
                                                                     │ │
   ┌──────────────────────────────────────────────────────────┐      │ │
   │         Error Response (Verification Failure)            │◄─────┘ │
   │  Returns 400/500 to VC if partial sig verification fails │        │
   └──────────────────────────────────────────────────────────┘        │
                                                                       │
   ┌──────────────────────────────────────────────────────────┐        │
   │         Error Response (RANDAO Verification)             │◄───────┘
   │  Returns error if RANDAO partial sig verification fails  │
   └──────────────────────────────────────────────────────────┘
```

### Sync Committee Duty Flow

```
┌──────────────┐
│ Validator    │
│ Client (VC)  │
└──────┬───────┘
       │
       │ 1. POST /eth/v1/validator/sync_committee_messages
       │    Body: [SyncCommitteeMessage{slot, beacon_block_root,
       │                                validator_index, signature}]
       │
       ▼
┌──────────────────────────────────────────────────────────────┐
│                      ValidatorAPI                            │
│                                                              │
│  SubmitSyncCommitteeMessages(messages)                       │
│   1. Extract pubkey from validator index                     │
│   2. Create ParSignedData (partial signature)                │
│   3. verifyPartialSig() with share public key                │──┐
│   4. Exchange, aggregate, broadcast                          │  │
└──────────────────────────────────────────────────────────────┘  │
                                                                  │
   ┌──────────────────────────────────────────────────────────┐   │
   │         Error Response (Verification Failure)            │◄──┘
   │  Returns 400/500 to VC if partial sig verification fails │
   └──────────────────────────────────────────────────────────┘


   ┌──────────────┐
   │ Validator    │
   │ Client (VC)  │
   └──────┬───────┘
          │
          │ 2. GET /eth/v1/validator/sync_committee_contribution
          │    ?slot=X&subcommittee_index=Y&beacon_block_root=0x...
          │
          ▼
   ┌──────────────────────────────────────────────────────────┐
   │                  ValidatorAPI                            │
   │                                                          │
   │  SyncCommitteeContribution(slot, subcommIdx, root)       │
   │   └─> AwaitSyncContribution(...) (blocks until ready)    │
   └──────────────────────────────────────────────────────────┘
          │
          ▼
   ┌──────────────────────────────────────────────────────────┐
   │                      DutyDB                              │
   │  - Stores unsigned sync committee contributions          │
   │  - Retrieved after consensus completes                   │
   └──────────────────────────────────────────────────────────┘


   ┌──────────────┐
   │ Validator    │
   │ Client (VC)  │
   └──────┬───────┘
          │
          │ 3. POST /eth/v1/validator/contribution_and_proofs
          │    Body: [SignedContributionAndProof{message, signature}]
          │
          ▼
   ┌──────────────────────────────────────────────────────────┐
   │                  ValidatorAPI                            │
   │                                                          │
   │  SubmitContributionAndProofs(contributions)              │
   │   1. Extract pubkey from contribution                    │
   │   2. Verify selection proof (inner signature)            │──┐
   │   3. Create ParSignedData (partial outer sig)            │  │
   │   4. verifyPartialSig() with share public key            │──┼─┐
   │   5. Exchange, aggregate, broadcast                      │  │ │
   └──────────────────────────────────────────────────────────┘  │ │
                                                                 │ │
   ┌─────────────────────────────────────────────────────────┐   │ │
   │         Error Response (Selection Proof Invalid)        │◄──┘ │
   │  Returns error if selection proof verification fails    │     │
   └─────────────────────────────────────────────────────────┘     │
                                                                   │
   ┌─────────────────────────────────────────────────────────┐     │
   │         Error Response (Verification Failure)           │◄────┘
   │  Returns 400/500 to VC if partial sig verification fails│
   └─────────────────────────────────────────────────────────┘
```

## Special Endpoints

### Builder Registration

**Endpoint:** `POST /eth/v1/validator/register_validator`

Builder registrations are handled automatically rather than through VC requests:

1. **VC Request Handling**: When VC submits a registration request, ValidatorAPI returns `200 OK` without processing
2. **Actual Submission**: Pre-generated builder registrations are scheduled for submission:
   - **At startup**: Registrations for all DVs in the cluster (from `cluster-lock.json`)
   - **Every epoch**: Resubmissions at the first slot of each epoch
3. **No Consensus**: Registrations bypass the consensus workflow entirely (no `DutyBuilderRegistration` duty)
4. **Pre-generated**: Registrations are created during DKG and stored in the cluster lock file

### Fee Recipient Preparation

**Endpoint:** `POST /eth/v1/validator/prepare_beacon_proposer`

This endpoint returns `200 OK` without processing:

- Fee recipients are configured in the cluster lock file during [DKG](pedersen-dkg.md)
- VCs don't need to specify fee recipients dynamically
- Prevents VC misconfiguration from affecting distributed validator
- Maintains compatibility with VCs that expect this endpoint to succeed

### Committee Selections

**Endpoints:**

- `POST /eth/v1/validator/beacon_committee_selections`
- `POST /eth/v1/validator/sync_committee_selections`

These return selection proofs:

1. VC requests selections for potential aggregator duties
2. ValidatorAPI queries duty definitions to check eligibility
3. For each validator, creates selection proof:
   - `DutyPrepareAggregator` or `DutyPrepareSyncContribution`
   - Goes through partial signing, exchange, aggregation
   - Returns aggregated selection proof to VC
4. VC uses selection proof when submitting aggregated duties

## Content Type Support

ValidatorAPI supports two content types for most endpoints:

### JSON (application/json)

- Default for most requests/responses
- Standard Ethereum Beacon API format

### SSZ (application/octet-stream)

- More efficient binary encoding
- Used for blocks and some large objects
- Requested via `Content-Type: application/octet-stream` header

## Error Handling

### Verification Failures

- **HTTP 400:** Invalid partial signature, bad request format
- **HTTP 500:** Internal errors (consensus failure, beacon node unreachable)

### Timeout Errors

- Unsigned data not available within timeout
- Occurs when consensus doesn't complete in time
- Returns context deadline exceeded error

### Beacon Node Errors

- Proxied endpoints return beacon node errors unchanged
- Intercepted endpoints may wrap beacon node errors with additional context
