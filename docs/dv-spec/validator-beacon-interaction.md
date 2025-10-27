# Validator and Beacon Node Interaction

## Overview

Charon operates as a **middleware** between Validator Clients (VCs) and Beacon Nodes (BNs), implementing the [Ethereum Beacon Node API](https://ethereum.github.io/beacon-APIs/#/). This middleware architecture enables distributed validation by:

1. **Intercepting** validator-specific endpoints to implement distributed validator logic
2. **Proxying** standard beacon chain queries directly to the upstream beacon node
3. **Transforming** public keys between DV root keys and share keys
4. **Verifying** partial signatures before aggregation

The ValidatorAPI component serves as the entry point for all VC requests, acting as a reverse proxy that selectively handles certain endpoints while forwarding others to the beacon node.

## Public Key Mapping

A critical aspect of the middleware is the bidirectional mapping between public keys. A Charon instance typically manages **multiple distributed validators**, each with its own set of keys:

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

### GET Requests (Duties)

When returning duty data to VCs:

1. Beacon node returns duties with DV root public keys (e.g., 0xabc..., 0xdef...)
2. Charon replaces each root key with this node's corresponding public share (e.g., Node 1: 0x111..., 0x444...)
3. VC receives duties with share public keys for this specific node

### POST Requests (Submissions)

When receiving signed data from VCs:

1. VC signs with its share private key (from keystore - e.g., private key for 0x111...)
2. Charon receives data signed by share public key (e.g., 0x111...)
3. Charon maps share key back to DV root key (0x111... → 0xabc...)
4. Charon verifies partial signature using the share public key
5. After [consensus](consensus.md) and aggregation, full signature uses the DV root public key

This mapping is configured during [DKG](pedersen-dkg.md) and stored in the [cluster lock file](cluster-files.md), with each node knowing:

- All DV root public keys for every validator in the cluster
- This node's public share for each validator (based on node index)
- The bidirectional mapping between shares and root keys

## Intercepted Endpoints

Charon intercepts and handles the following validator API endpoints to implement distributed validator logic:

### Duty Endpoints

- `POST /eth/v1/validator/duties/attester/{epoch}` - Attester duties
- `GET /eth/v1/validator/duties/proposer/{epoch}` - Proposer duties
- `GET /eth/v1/validator/duties/sync/{epoch}` - Sync committee duties

### Attestation Endpoints

- `GET /eth/v1/validator/attestation_data` - Unsigned attestation data
- `POST /eth/v2/validator/aggregate_attestation` - Aggregate attestation
- `POST /eth/v1/validator/aggregate_and_proofs` - Submit aggregated attestations (deprecated v1)
- `POST /eth/v2/validator/aggregate_and_proofs` - Submit aggregated attestations

### Block Proposal Endpoints

- `GET /eth/v1/validator/blinded_blocks/{slot}` - Unsigned blinded block (deprecated)
- `GET /eth/v2/validator/blinded_blocks/{slot}` - Unsigned blinded block (deprecated)
- `GET /eth/v3/validator/blocks/{slot}` - Unsigned block (current)
- `POST /eth/v1/beacon/blocks` - Submit signed block
- `POST /eth/v2/beacon/blocks` - Submit signed block
- `POST /eth/v1/beacon/blinded_blocks` - Submit signed blinded block
- `POST /eth/v2/beacon/blinded_blocks` - Submit signed blinded block

### Sync Committee Endpoints

- `GET /eth/v1/validator/sync_committee_contribution` - Unsigned sync committee contribution
- `POST /eth/v1/validator/contribution_and_proofs` - Submit sync committee contributions
- `POST /eth/v1/validator/sync_committee_messages` - Submit sync committee messages

### Selection & Registration Endpoints

- `POST /eth/v1/validator/beacon_committee_selections` - Beacon committee selections
- `POST /eth/v1/validator/sync_committee_selections` - Sync committee selections
- `POST /eth/v1/validator/register_validator` - Builder registration (per-validator)
- `POST /eth/v1/validator/prepare_beacon_proposer` - Fee recipient registration (swallowed, not processed)

### Metadata Endpoints

- `GET /eth/v1/node/version` - Node version (returns Charon version)

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

## Duty Workflow Architecture

The following sections detail how the ValidatorAPI component integrates with Charon's core workflow for different duty types.

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
│                      ▲                                       │
└──────────────────────┼───────────────────────────────────────┘
                       │
                       │ Stores unsigned attestation data
                       │
┌──────────────────────┴──────────────────────────────────────┐
│                    Consensus                                │
│                                                             │
│  - Agrees on unsigned attestation data                      │
│  - Stores agreed value in DutyDB                            │
└─────────────────────▲───────────────────────────────────────┘
                      │
                      │ Proposes unsigned data
                      │
┌─────────────────────┴───────────────────────────────────────┐
│                    Fetcher                                  │
│                                                             │
│  1. Fetch(DutyAttester, defSet)                             │
│  2. Query Beacon Node:                                      │
│     eth2Cl.AttestationData(slot, commIdx)                   │
│  3. Returns UnsignedDataSet{pubkey -> AttestationData}      │
└─────────────────────▲───────────────────────────────────────┘
                      │
                      │ Triggered by scheduler
                      │
┌─────────────────────┴───────────────────────────────────────┐
│                   Scheduler                                 │
│                                                             │
│  1. Resolves attester duties from beacon node               │
│  2. Schedules DutyAttester for (slot, commIdx)              │
│  3. Triggers Fetcher.Fetch()                                │
└─────────────────────────────────────────────────────────────┘
       ▲
       │ Subscribes to slots
       │
   ┌───┴────┐
   │  Slot  │
   │ Ticker │
   └────────┘


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
   │                                                          │     │
   │  - Stores partial signatures per duty/pubkey/shareIdx    │     │
   │  - Triggers threshold event when enough collected        │     │
   │  - Calls subscribers (ParSigEx)                          │     │
   └──────────────────────────┬───────────────────────────────┘     │
                              │                                     │
                              │ Threshold reached                   │
                              ▼                                     │
   ┌──────────────────────────────────────────────────────────┐     │
   │                    ParSigEx                              │     │
   │                                                          │     │
   │  - Exchanges partial signatures with other peers         │     │
   │  - Returns when threshold signatures collected           │     │
   └──────────────────────────┬───────────────────────────────┘     │
                              │                                     │
                              │ All partial sigs collected          │
                              ▼                                     │
   ┌──────────────────────────────────────────────────────────┐     │
   │                     SigAgg                               │     │
   │                                                          │     │
   │  1. Aggregate(duty, map[PubKey][]ParSignedData)          │     │
   │  2. Verify each partial signature                        │     │
   │  3. ThresholdAggregate() -> full signature               │     │
   │  4. Call subscribers with SignedDataSet                  │     │
   └──────────────────────────┬───────────────────────────────┘     │
                              │                                     │
                              │ Aggregated signature                │
                              ▼                                     │
   ┌──────────────────────────────────────────────────────────┐     │
   │                  Broadcaster                             │     │
   │                                                          │     │
   │  - SubmitAttestations() to beacon node                   │     │
   │  - Includes aggregated signature                         │     │
   └──────────────────────────────────────────────────────────┘     │
                                                                    │
                                                                    │
   ┌──────────────────────────────────────────────────────────┐     │
   │                 Error Response                           │◄────┘
   │  Returns 400/500 to VC if verification fails             │
   └──────────────────────────────────────────────────────────┘
```

**Key Points:**

- VCs query unsigned attestation data which blocks until [consensus](consensus.md) agrees
- VCs submit signed attestations with partial signatures (signed by share key)
- Charon verifies partial signature before accepting
- After threshold signatures collected, they are exchanged via [ParSigEx](parsigex.md), aggregated by SigAgg, and broadcast

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
│                                                   │        │    │
│  ┌───────────────────────────────────────────┐    │        │    │
│  │ Store(DutyProposer, UnsignedDataSet)      │◄───┘        │    │
│  │   - Stores block per slot                 │             │    │
│  │   - Resolves pending queries              │             │    │
│  └───────────────────────────────────────────┘             │    │
│                      ▲                                     │    │
└──────────────────────┼─────────────────────────────────────┘    │
                       │                                          │
                       │ Stores unsigned block                    │
                       │                                          │
┌──────────────────────┴─────────────────────────────────────┐    │
│                    Consensus                               │    │
│                                                            │    │
│  - Agrees on unsigned block                                │    │
│  - Stores agreed value in DutyDB                           │    │
└─────────────────────▲──────────────────────────────────────┘    │
                      │                                           │
                      │ Proposes unsigned block                   │
                      │                                           │
┌─────────────────────┴──────────────────────────────────────┐    │
│                    Fetcher                                 │    │
│                                                            │    │
│  1. Fetch(DutyProposer, defSet)                            │    │
│  2. Get aggregated RANDAO from AggSigDB                    │    │
│  3. Query Beacon Node:                                     │    │
│     eth2Cl.Proposal(slot, randao, graffiti, ...)           │    │
│  4. Returns UnsignedDataSet{pubkey -> VersionedBlock}      │    │
└─────────────────────▲──────────────────────────────┬───────┘    │
                      │                              │            │
                      │                              │            │
                      │                              │            │
┌─────────────────────┴──────────┐    ┌──────────────▼──────┐     │
│       Scheduler                │    │     AggSigDB        │     │
│                                │    │                     │     │
│  1. Resolves proposer duties   │    │ - Stores aggregated │     │
│  2. Schedules DutyRandao first │    │   RANDAO signatures │     │
│  3. Then schedules DutyProposer│    │ - Queried by Fetcher│     │
│  4. Triggers Fetcher.Fetch()   │    │   before block fetch│     │
└────────────────────────────────┘    └─────────────────────┘     │
       ▲                                        ▲                 │     
       │                                        │                 │
       │ Subscribes to slots              Aggregated RANDAO       │ 
       │                                   from SigAgg after ◄────┘
   ┌───┴────┐                              threshold reached
   │  Slot  │
   │ Ticker │                          [ParSigDB -> ParSigEx
   └────────┘                           -> SigAgg -> AggSigDB]


   ┌──────────────┐
   │ Validator    │
   │ Client (VC)  │
   └──────┬───────┘
          │
          │ 2. POST /eth/v2/beacon/blocks
          │    Body: SignedBeaconBlock{message, signature}
          │
          ▼
   ┌──────────────────────────────────────────────────────────────┐
   │                      ValidatorAPI                            │
   │                                                              │
   │  ┌────────────────────────────────────────────────────┐      │
   │  │ SubmitProposal(signedBlock)                        │      │
   │  │   1. Get pubkey from duty definitions              │      │
   │  │   2. AwaitProposal(slot) to get unsigned block     │      │
   │  │   3. Verify signed matches unsigned (anti-slashing)│──────┼──┐
   │  │   4. Create ParSignedData (partial signature)      │      │  │
   │  │   5. verifyPartialSig() with share public key      │──────┼──┼─┐
   │  │   6. Call subscribers with ParSignedDataSet        │      │  │ │
   │  └────────────────────────────────────────────────────┘      │  │ │
   └───────────────────────────────────────────────┬──────────────┘  │ │
                                                   │                 │ │
                                                   │ Stores          │ │
                                                   ▼                 │ │
   ┌──────────────────────────────────────────────────────────┐      │ │
   │                    ParSigDB                              │      │ │
   │  (Same flow as attestations)                             │      │ │
   └──────────────────────────┬───────────────────────────────┘      │ │
                              │                                      │ │
                              ▼                                      │ │
   ┌──────────────────────────────────────────────────────────┐      │ │
   │  ParSigEx -> SigAgg -> Broadcaster                       │      │ │
   │                                                          │      │ │
   │  - SubmitProposal() or SubmitBlindedProposal()           │      │ │
   │    to beacon node with aggregated signature              │      │ │
   └──────────────────────────────────────────────────────────┘      │ │
                                                                     │ │
   ┌──────────────────────────────────────────────────────────┐      │ │
   │         Error Response (Mismatch)                        │◄─────┘ │
   │  Returns error if signed block doesn't match unsigned    │        │
   └──────────────────────────────────────────────────────────┘        │
                                                                       │
   ┌──────────────────────────────────────────────────────────┐        │
   │         Error Response (Verification Failure)            │◄───────┘
   │  Returns 400/500 to VC if partial sig verification fails │
   └──────────────────────────────────────────────────────────┘
```

**Key Points:**

- Proposal duty requires RANDAO reveal to be aggregated first (DutyRandao)
- VCs first submit RANDAO as GET parameter, stored as partial signature
- After RANDAO aggregated, Fetcher queries unsigned block from beacon node
- Unsigned block goes through [consensus](consensus.md), stored in DutyDB
- VCs submit signed blocks, Charon verifies:
  - Block data matches unsigned version (anti-slashing)
  - Partial signature is valid for share public key
- Supports both regular and blinded blocks (builder API)

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
│  ┌────────────────────────────────────────────────────┐      │
│  │ SubmitSyncCommitteeMessages(messages)              │      │
│  │   1. Extract pubkey from validator index           │      │
│  │   2. Create ParSignedData (partial signature)      │      │
│  │   3. verifyPartialSig() with share public key      │──────┼──┐
│  │   4. Call subscribers with ParSignedDataSet        │      │  │
│  └────────────────────────────────────────────────────┘      │  │
└───────────────────────────────────────────────┬──────────────┘  │
                                                │                 │
                                  [ParSigDB -> ParSigEx           │
                                   -> SigAgg -> Broadcaster]      │
                                                │                 │
                                                │                 │
   ┌────────────────────────────────────────────┼──────────────┐  │
   │                  Broadcaster               │              │  │
   │                                            ▼              │  │
   │  SubmitSyncCommitteeMessages() to beacon node             │  │
   │  with aggregated signatures                               │  │
   └───────────────────────────────────────────────────────────┘  │
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
   ┌──────────────────────────────────────────────────────────────┐
   │                      ValidatorAPI                            │
   │                                                              │
   │  ┌────────────────────────────────────────────────────┐      │
   │  │ SyncCommitteeContribution(slot, subcommIdx, root)  │      │
   │  │   └─> AwaitSyncContribution(...) ──────────────┐   │      │
   │  └────────────────────────────────────────────────┼───┘      │
   └─────────────────────────────────────────────────┬─┼──────────┘
                                                     │ │
                       Blocks until available        │ │
                                                     │ │
                                                     ▼ │
   ┌───────────────────────────────────────────────────┼─────────┐
   │                      DutyDB                       │         │
   │                                                   │         │
   │  ┌───────────────────────────────────────────┐    │         │
   │  │ Store(DutySyncContribution,               │◄───┘         │
   │  │       UnsignedDataSet)                    │              │
   │  │   - Stores contribution per (slot,        │              │
   │  │     subcommIdx, beacon_block_root)        │              │
   │  └───────────────────────────────────────────┘              │
   │                      ▲                                      │
   └──────────────────────┼──────────────────────────────────────┘
                          │
                          │ Stores unsigned contribution
                          │
   ┌──────────────────────┴─────────────────────────────────────┐
   │                    Consensus                               │
   │  - Agrees on unsigned sync committee contribution          │
   └─────────────────────▲──────────────────────────────────────┘
                         │
                         │ Proposes unsigned data
                         │
   ┌─────────────────────┴──────────────────────────────────────┐
   │                    Fetcher                                 │
   │                                                            │
   │  1. Fetch(DutySyncContribution, defSet)                    │
   │  2. Query Beacon Node:                                     │
   │     eth2Cl.SyncCommitteeContribution(slot, subcommIdx,     │
   │                                      beacon_block_root)    │
   │  3. Returns UnsignedDataSet{pubkey -> Contribution}        │
   └────────────────────────────────────────────────────────────┘


   ┌──────────────┐
   │ Validator    │
   │ Client (VC)  │
   └──────┬───────┘
          │
          │ 3. POST /eth/v1/validator/contribution_and_proofs
          │    Body: [SignedContributionAndProof{message, signature}]
          │
          ▼
   ┌──────────────────────────────────────────────────────────────┐
   │                      ValidatorAPI                            │
   │                                                              │
   │  ┌────────────────────────────────────────────────────┐      │
   │  │ SubmitContributionAndProofs(contributions)         │      │
   │  │   1. Extract pubkey from contribution              │      │
   │  │   2. Verify selection proof (inner signature)      │──────┼──┐
   │  │   3. Create ParSignedData (partial outer sig)      │      │  │
   │  │   4. verifyPartialSig() with share public key      │──────┼──┼─┐
   │  │   5. Call subscribers with ParSignedDataSet        │      │  │ │
   │  └────────────────────────────────────────────────────┘      │  │ │
   └───────────────────────────────────────────────┬──────────────┘  │ │
                                                   │                 │ │
                                  [ParSigDB -> ParSigEx              │ │
                                   -> SigAgg -> Broadcaster]         │ │
                                                   │                 │ │
   ┌───────────────────────────────────────────────┼──────────────┐  │ │
   │                  Broadcaster                  │              │  │ │
   │                                               ▼              │  │ │
   │  SubmitContributionAndProofs() to beacon node                │  │ │
   │  with aggregated signatures                                  │  │ │
   └──────────────────────────────────────────────────────────────┘  │ │
                                                                     │ │
   ┌─────────────────────────────────────────────────────────────┐   │ │
   │         Error Response (Selection Proof Invalid)            │◄──┘ │
   │  Returns error if selection proof verification fails        │     │
   └─────────────────────────────────────────────────────────────┘     │
                                                                       │
   ┌─────────────────────────────────────────────────────────────┐     │
   │         Error Response (Verification Failure)               │◄────┘
   │  Returns 400/500 to VC if partial sig verification fails    │
   └─────────────────────────────────────────────────────────────┘
```

**Key Points:**

- Three separate endpoints for sync committee duties
- Sync messages are submitted directly (DutySyncMessage)
- Sync contributions require fetching unsigned data first (DutySyncContribution)
- Contribution submission includes two signatures:
  - Inner selection proof (verified before acceptance)
  - Outer aggregated contribution signature (partial sig verified)

## Special Endpoints

### Builder Registration

**Endpoint:** `POST /eth/v1/validator/register_validator`

Builder registrations are handled specially:

1. VC submits signed validator registration with partial signature
2. ValidatorAPI verifies partial signature
3. Stores in ParSigDB, exchanges via [ParSigEx](parsigex.md), aggregates via SigAgg
4. **Rebroadcaster** component rebroadcasts registrations every epoch
5. Registrations cached in AggSigDB for rebroadcast
6. Pre-generated registrations from cluster lock used if available

### Fee Recipient Preparation

**Endpoint:** `POST /eth/v1/validator/prepare_beacon_proposer`

This endpoint is **swallowed** (returns success but does nothing):

- Fee recipients configured in cluster lock file during DKG
- VCs don't need to specify fee recipients
- Prevents VC misconfiguration from affecting distributed validator

### Committee Selections

**Endpoints:**

- `POST /eth/v1/validator/beacon_committee_selections`
- `POST /eth/v1/validator/sync_committee_selections`

These return selection proofs:

1. VC requests selections for potential aggregator duties
2. ValidatorAPI queries duty definitions to check eligibility
3. For each validator, creates selection proof:
   - DutyPrepareAggregator or DutyPrepareSyncContribution
   - Goes through partial signing, exchange, aggregation
   - Returns aggregated selection proof to VC
4. VC uses selection proof when submitting aggregated duties

## Content Type Support

ValidatorAPI supports two content types for most endpoints:

### JSON (application/json)

- Default for most requests/responses
- Human-readable, easier debugging
- Standard Ethereum Beacon API format

### SSZ (application/octet-stream)

- More efficient binary encoding
- Used for blocks and some large objects
- Requested via `Content-Type: application/octet-stream` header
- Charon supports both for maximum VC compatibility

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

## ValidatorAPI

The ValidatorAPI acts as the translation layer that:

1. Translates standard Ethereum Beacon API calls into distributed validator workflow
2. Maps between share keys (VC-facing) and root keys (internal/BN-facing)
3. Converts full signatures (VC-submitted) into partial signatures (internal)
4. Blocks VC requests until [consensus](consensus.md) completes on unsigned data
5. Verifies partial signatures before accepting into the signing workflow

The key insight is that from the VC's perspective, it's interacting with a normal beacon node, but Charon intercepts the critical signing operations to implement the distributed validator protocol, while proxying everything else to maintain full beacon chain functionality.
