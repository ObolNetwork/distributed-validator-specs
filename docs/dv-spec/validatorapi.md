# ValidatorAPI: Validator Client Interface

## Overview

The ValidatorAPI component serves as a **reverse proxy** and **middleware layer** between the connected downstream Validator Client (VC) and upstream Beacon Nodes (BNs). It implements the [Ethereum Beacon Node API](https://ethereum.github.io/beacon-APIs/#/) while adding distributed validator logic for signing operations.

**Key Features:**

1. **Endpoint Interception**: Intercepts validator-specific endpoints to implement distributed validator logic.
2. **Endpoint Proxying**: Forwards beacon chain queries directly to upstream beacon node unchanged.
3. **Key Translation**: Maps between DV root public keys and share public keys bidirectionally.
4. **Signature Verification**: Verifies partial signatures from VCs before accepting into signing workflow.
5. **Consensus Coordination**: Blocks unsigned data requests until [consensus](consensus.md) completes.

## Public Key Mapping

A critical aspect of the middleware is the bidirectional mapping between public keys. A DV instance typically manages **multiple distributed validators**, each with its own set of keys:

- **DV Root Public Keys**: Each distributed validator has its own aggregate BLS public key (one per validator managed by the cluster)
- **Public Shares**: For each distributed validator, each node has a threshold BLS public key share (N shares per validator, where N = number of nodes in a cluster)

### Example: 3-node cluster with 2 validators

```text
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
- `POST /eth/v2/beacon/pool/attestations` - Submit attestations
- `POST /eth/v2/validator/aggregate_attestation` - Unsigned aggregate attestation
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
- **Prerequisites**: VCs only call this endpoint after determining aggregator selection:
  1. VC creates partial selection proofs (BLS signatures on slot with public share)
  2. VC calls `beacon_committee_selections` with these partial proofs
  3. DVs exchange partial proofs between nodes and aggregate them
  4. DV return aggregated selection proofs (threshold signatures with DV root key)
  5. VC evaluates `is_aggregator(committee_length, aggregated_selection_proof)`
  6. Only if selected, VC calls this endpoint to fetch the aggregate attestation

**`POST /eth/v2/validator/aggregate_and_proofs`:**

- **Request body transformation**:
  1. Extract aggregator public key from `AggregateAndProof.aggregator_index`
  2. Map public share → DV root public key (transforms key in message)
  3. Exchange partial signatures between nodes and aggregate → threshold signature with DV root key (transforms signature)
- **Request verifications**:
  1. Verify selection proof signature (inner signature on contribution)
  2. Verify partial signature on outer `SignedAggregateAndProof` against public share
- **No response** (204 on success)

### Block Proposal Endpoints

- `GET /eth/v3/validator/blocks/{slot}` - Unsigned block
- `POST /eth/v2/beacon/blocks` - Submit signed block
- `POST /eth/v2/beacon/blinded_blocks` - Submit signed blinded block

**Request Transformation:**

**`GET /eth/v3/validator/blocks/{slot}`:**

- **Request query parameters from VC**:
  - `randao_reveal`: Public share signature (partial RANDAO)
  - `graffiti`: Provided by VC (optional)
  - `builder_boost_factor`: Provided by VC (optional)
- **RANDAO processing** (prerequisite for block proposal):
  1. Extract RANDAO reveal signature from VC request
  2. Create `ParSignedData` for `DutyRandao` with partial signature
  3. Verify partial RANDAO signature against this node's public share
  4. Exchange partial RANDAO signatures between nodes via [ParSigEx](parsigex.md) and aggregate to threshold signature
  5. Store aggregated RANDAO to use in block request to beacon node
- **Request to beacon node**:
  - `randao_reveal`: Aggregated threshold RANDAO signature (retrieved from AggSigDB)
  - `graffiti`: Cluster-configured graffiti (replaces VC graffiti, can be set per-validator or default "charon/version-commit")
  - `builder_boost_factor`: Set to max if builder enabled (overrides VC value)
- **Response**: No key transformation in block body
- **Additional processing**: Unsigned block goes through [consensus](consensus.md) to ensure all nodes agree on the same block data

**`POST /eth/v2/beacon/blocks` and `POST /eth/v2/beacon/blinded_blocks`:**

- **Request body transformation**:
  1. Extract proposer index from block
  2. Retrieve DV root public key from duty definitions
  3. Fetch unsigned block for anti-slashing check
  4. Verify signed block matches unsigned block (anti-slashing)
  5. Extract VC's partial signature on block
  6. Verify partial signature against this node's public share
- **No response** (204 on success)

**Implementation Details:**

- RANDAO reveal is processed separately at the time of receiving `GET /eth/v3/validator/blocks/{slot}` from the VC but before `GET /eth/v3/validator/blocks/{slot}` is sent to the BN
- Block matching prevents VCs from signing different block data

### Sync Committee Endpoints

- `POST /eth/v1/beacon/pool/sync_committees` - Submit sync committee messages
- `GET /eth/v1/validator/sync_committee_contribution` - Unsigned sync committee contribution
- `POST /eth/v1/validator/contribution_and_proofs` - Submit sync committee contributions

**Note**: There is no GET endpoint for unsigned sync committee messages. VCs construct sync committee messages by querying the beacon block root from the standard Beacon API (`GET /eth/v1/beacon/blocks/head/root`), then signing a message with `{slot, beacon_block_root, validator_index, signature}`.

**Request Transformation:**

**`POST /eth/v1/validator/sync_committee_messages`:**

- **Request body transformation**:
  1. Extract validator index from each sync committee message
  2. Map validator index → DV root public key
  3. Create `ParSignedData` for sync committee message
  4. Verify partial signature against this node's public share
  5. Exchange partial signatures between nodes via [ParSigEx](parsigex.md) and aggregate to threshold signatures
- **No response** (204 on success)

**`GET /eth/v1/validator/sync_committee_contribution`:**

- **Prerequisite**: This endpoint requires sync contribution selection proofs from `POST /eth/v1/validator/sync_committee_selections`:
  1. VC determines which validators should aggregate sync messages for each subcommittee
  2. VC creates selection proofs (partial signatures on `SyncAggregatorSelectionData{slot, subcommittee_index}`)
  3. VC submits partial selection proofs to DV via POST sync_committee_selections
  4. DV verifies partial selection signatures
  5. DV exchanges and aggregates selection proofs between nodes
  6. DV returns aggregated selection proofs as the response to POST sync_committee_selections
  7. VC evaluates `is_sync_committee_aggregator()` using the aggregated selection proof
  8. Only validators selected as aggregators (based on the aggregated selection proof) will call this GET endpoint to fetch sync contribution
- **Request**: Query parameters unchanged (slot, subcommittee_index, beacon_block_root)
- **Response**: No key transformation in contribution data
- **Additional processing**: Blocks until nodes agree on sync contribution data via [consensus](consensus.md)

**`POST /eth/v1/validator/contribution_and_proofs`:**

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
- `POST /eth/v1/validator/register_validator` - Builder registration
- `POST /eth/v1/validator/prepare_beacon_proposer` - Fee recipient registration

**Request Transformation:**

**`POST /eth/v1/validator/beacon_committee_selections`:**

- **Request body**: List of selections with validator indices, slots, and partial BLS selection proof signatures from VC
- **Processing**:
  1. For each selection, look up DV root public key from active validator set using validator index
  2. Create `ParSignedData` for `DutyPrepareAggregator`
  3. Verify partial BLS selection proof signature against this node's public share
  4. Exchange selection proofs between nodes via [ParSigEx](parsigex.md) and aggregate to threshold signatures
- **Response transformation**: Return aggregated selection proofs (threshold BLS signatures) to VC

**`POST /eth/v1/validator/sync_committee_selections`:**

- **Request body**: List of sync selections with validator indices, slots, subcommittee indices, and partial BLS
- **Processing**:
  1. For each selection, look up DV root public key from active validator set using validator index
  2. Create `ParSignedData` for `DutyPrepareSyncContribution`
  3. Verify partial BLS selection proof signature against this node's public share
  4. Exchange selection proofs between nodes via [ParSigEx](parsigex.md) and aggregate to threshold signatures
- **Response transformation**: Return aggregated selection proofs (threshold BLS signatures) to VC

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
- **Rationale**: Fee recipient addresses are configured in the cluster lock, not via VC requests. The endpoint returns 200 OK to maintain compatibility with VCs, but the submissions are ignored.
- **Actual submission**: Charon automatically submits with cluster-configured fee recipients:
  - At Charon startup (for all active DVs in cluster)
  - At the first slot of every epoch (for all active DVs)

**Implementation Details:**

- Selection proofs allow VCs to determine if they should aggregate
- Builder registrations are pre-generated in cluster lock and scheduled for automatic submission
- Fee recipient preparation is a no-op to prevent VC misconfiguration

### Metadata Endpoints

- `GET /eth/v1/node/version` - Node version
- `GET /eth/v1/beacon/states/{state_id}/validators` - Get validators
- `GET /eth/v1/beacon/states/{state_id}/validators/{validator_id}` - Get validator

**Request Transformation:**

**`GET /eth/v1/node/version`:**

- **Request**: No parameters
- **Response**: Returns DV version string instead of beacon node version
- **No key transformation**

**`GET /eth/v1/beacon/states/{state_id}/validators`:**

- **Request transformation**:
  1. If IDs are public shares (0x-prefixed), map each share → DV root public key
  2. Query beacon node with DV root public keys
  3. Supports caching for this heavy request
- **Response transformation**:
  1. For each validator in response, check if it's a cluster validator
  2. If cluster validator: `validator.PublicKey` (DV root public key) → public share (this node's share)
  3. If not cluster validator: leave unchanged
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
- `POST /eth/v1/validator/aggregate_and_proofs` - Use v2
- `GET /eth/v1/validator/blinded_blocks/{slot}` - Use v3
- `GET /eth/v2/validator/blinded_blocks/{slot}` - Use v3
- `POST /eth/v1/beacon/blocks` - Use v2
- `POST /eth/v1/beacon/blinded_blocks` - Use v2
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

## Selection Endpoints: DV-Specific Design

The selection endpoints (`beacon_committee_selections` and `sync_committee_selections`) are unique to distributed validators and require special explanation:

### Why Selection Endpoints Exist

In standard Ethereum validators, a VC creates selection proofs by signing with its private key. In DVs, this process must be distributed:

1. **Partial Signatures**: Each node's VC signs with its public share (partial signature)
2. **Exchange & Aggregation**: Nodes exchange these partial signatures via [ParSigEx](parsigex.md) and aggregate them via [SigAgg](sigagg.md) to create a valid threshold signature
3. **Selection Evaluation**: The VC receives the aggregated threshold signature and evaluates the standard `is_aggregator()` function to determine if it should aggregate

## Content Type Support

DV must matches the Beacon API spec for both inbound and outbound requests, supporting JSON (`application/json`) and SSZ (`application/octet-stream`) content types as defined in the standard.

## Error Handling

### Verification Failures

- **HTTP 4XX:** Client errors including invalid partial signatures (400), bad request format (400), not found (404), unsupported media type (415)
- **HTTP 500:** Server errors including consensus failures (500), beacon node unreachable (500), internal errors (500)

### Timeout Errors

VCs can distinguish timeout errors by:

- **HTTP 408** (Request Timeout): Returned when client cancels the request or context deadline exceeded
- **Error message**: Contains "context deadline exceeded" or "client cancelled request" in the error response body

### Beacon Node Errors

- Proxied endpoints return beacon node errors unchanged
- Intercepted endpoints may wrap beacon node errors with additional context
