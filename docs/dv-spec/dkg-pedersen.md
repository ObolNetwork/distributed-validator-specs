# Pedersen DKG Interoperability Spec

This document describes the Pedersen distributed key generation (DKG) protocol used for generating and resharing BLS validator keys.

Scope:

- Over-the-wire message shapes and fields
- Protocol identifiers, sequencing, and nonce derivation
- Output artifacts

Out of scope: cryptographic routines, Kyber DKG internals, transport reliability

**Note**: This document describes the cryptographic DKG protocol only. See [DKG Sync Protocol](dkg-sync.md) for ceremony management.

## Terms and Notation

- `n`: number of participating nodes in the ceremony
- `t`: threshold used by the DKG (default ceil(2n/3))
- `Session ID`: a 32-byte value known to all nodes; it is the cluster Definition hash
- `Suite`: BLS12-381, Kyber G1 for public points and scalars for shares

## Protocol Identifiers (libp2p)

All messages are sent under protocol ID prefix:

```
/charon/dkg/pedersen/1.0.0
```

The following message topics are appended to the prefix when routing on libp2p:

- node_pubkeys (reliable broadcast)
- val_pubkey_share (p2p to all peers)
- deal_bundle (p2p to all peers)
- resp_bundle (p2p to all peers)
- just_bundle (p2p to all peers)

## Reliable Broadcast for node_pubkeys

Why this matters: the ephemeral node public keys are a single-shot, invariant input required before anyone starts the DKG. If a malicious node could equivocate (send different pubkeys to different peers), the group view would diverge. Implementations therefore use a lightweight "signed broadcast" component for `node_pubkeys` instead of plain p2p fan-out. See the standalone Reliable Broadcast spec for generic details; this section documents the DKG-specific usage.

Two-phase signed broadcast (summary):

1. Signature collection phase

   - The broadcaster wraps the `NodePubKeyMessage` in an Any-like envelope and computes the hash:
     - hash = SHA256(type_url || value)
   - It sends `BCastSigRequest(Id=node_pubkeys, Message=Any(NodePubKeyMessage))` to all peers and collects `BCastSigResponse(signature)` from each.
   - The server validates type constraints via a registered `CheckMessage` for the message ID and applies anti-equivocation dedup per (requester PeerID, msgID): it stores the first hash seen for that requester+ID and refuses to sign a different hash under the same ID later.
   - Each response signature is a K1 (secp256k1) 65-byte R||S||V signature over the hash using the responder’s ENR private key.

2. Broadcast phase
   - The broadcaster verifies all collected signatures locally against the known peer list and then sends a single `BCastMessage(Id, Message=Any(NodePubKeyMessage), Signatures=[...])` to all peers.

- On receipt, the server re-verifies the whole signature set before invoking the registered callback that finally delivers the `NodePubKeyMessage` to the DKG board.

Reference

- Generic mechanism: `docs/specs/reliable-broadcast.md`
- Python models and helper: `dv_spec.subspecs.bcast`

Properties provided

- Anti-equivocation per broadcaster and message ID: a node cannot get the group to co-sign two different `node_pubkeys` payloads under the same ID because peers only sign one hash per (requester, ID).
- Group-level validation: receivers only accept a `node_pubkeys` message if it carries a full set of valid signatures (one per peer in the configured order) over the exact same hash.
- Dedup and type checks: the component rejects mismatched message types and duplicate signature requests with different hashes.

Contrast with regular libp2p p2p fan-out

- Plain p2p (used for DKG deals/responses/justifications and `val_pubkey_share`) is direct stream sends to each peer with per-stream timeouts. It doesn’t collect group signatures, doesn’t deduplicate across the group, and can’t prevent a sender from delivering divergent payloads to different peers if the application layer doesn’t defend against it.
- Using signed broadcast for `node_pubkeys` adds an all-peers endorsement that the exact same payload was observed and approved by the group before it is considered valid. This is heavier than direct p2p, so Charon limits it to the once-per-ceremony `node_pubkeys` step; the high-churn DKG rounds rely on Kyber's protocol phases instead.

## Nonce Derivation

All participants MUST derive the DKG nonce from the reliably broadcast ephemeral node public keys collected in step 1.

Algorithm:

1. Order all participants by the canonical peer order (cluster operator index / peer index).
2. For each participant i in order, take the exact byte encoding of `NodePubKeyMessage.public_key` (kyber.Point MarshalBinary form).
3. Concatenate these byte strings in order to form a single buffer `buf`.
4. Compute `nonce = SHA256(buf)`.

Notes:

- Deterministic ordering is critical; use the same ordered peer list used everywhere else in the ceremony.
- Implementations should expose a helper similar to `generate_nonce_from_node_pubkeys(node_pubkeys: List[bytes]) -> bytes`.

## Message Schemas

The following protobuf definitions are used over the wire:

- [pedersen.proto](../../proto/pedersen.proto) - Pedersen DKG message definitions

See the Python reference implementation: [`NodePubKeyMessage`](../../src/dv_spec/subspecs/dkg/message.py#L86-L103), [`ValidatorPubKeyShareMessage`](../../src/dv_spec/subspecs/dkg/message.py#L105-L112), [`PedersenDealBundle`](../../src/dv_spec/subspecs/dkg/message.py#L122-L132), [`PedersenResponseBundle`](../../src/dv_spec/subspecs/dkg/message.py#L141-L149), and [`PedersenJustificationBundle`](../../src/dv_spec/subspecs/dkg/message.py#L157-L164).

## Ceremony Sequencing

1. Ephemeral node keys broadcast

- Each node generates an ephemeral BLS key pair using the suite (BLS12-381) and broadcasts `NodePubKeyMessage`.
- For resharing, include `shares.public_key_shares`: one kyber.Point per validator index, encoding the old validator public share for that node.
- Nodes wait until they have collected all n `NodePubKeyMessage`s and then compute the DKG `nonce` by concatenating all `public_key` fields (in canonical order) and hashing with SHA256.

2. DKG rounds (per validator)

   - For each validator to produce/reshare, run one Kyber Pedersen DKG instance with config:
     - Suite: BLS12-381
     - Nonce: SHA256(concat(pubkey_i)) from step 1
     - Nodes: ordered by peer index
     - Threshold: t
     - FastSync: true (Kyber library optimization for skipping deal verification)
     - Auth: BDN BLS on G2 (signature scheme for authenticating DKG messages)
   - Exchanges occur by sending/receiving the following bundles to all peers:
     - PedersenDealBundle, PedersenResponseBundle, PedersenJustificationBundle
   - Each run yields a DistKeyShare (validator secret share + pub commitments).

3. Share of validator public key broadcast

   - After each DKG run, each node broadcasts their validator public key share via `ValidatorPubKeyShareMessage`.
   - For resharing where a node is removed, it MUST send an empty `public_key_share` to signal non-participation.
   - Nodes collect the announced shares and build the `public_shares` map ordered by share index (1-based).

4. Output artifacts
   - For each validator, the resulting artifact is:
     - validator_pubkey: kyber.Point (aggregate validator public key)
     - secret_share: kyber.Scalar (this node's private share)
     - public_shares: map[int->bytes], share indices 1..n for the nodes that will remain after resharing

## Indexing Rules

- Node/peer index: 0-based position in the peer list
- Share index in bundles: 0-based unless specified by library
- Public shares map used in cluster artifacts: 1-based index = PeerIdx + 1

## Resharing Notes

- The set of nodes in `oldNodes` and `newNodes` is determined by the rotation being performed; removed nodes must not contribute new shares and should broadcast an empty `ValidatorPubKeyShareMessage`.
- The threshold t' should not be increased in add-operator flows to avoid old shares enabling reconstruction below the new threshold.

## Edit Operations Powered by Pedersen DKG

This section maps cluster edit commands to concrete Pedersen DKG ceremonies. Each operation specifies who participates, how the nonce is derived, which messages are exchanged, and what artifacts are produced/updated.

General across all edit operations:

- Session: The session ID is the cluster Definition hash. A fresh nonce is computed per ceremony from the reliably-broadcast `node_pubkeys` of the set of peers participating in that ceremony.
- Transport: `node_pubkeys` uses reliable broadcast; all other exchanges use direct p2p to all participating peers.
- Indexing: Peer index is 0-based; share index used in artifacts is 1-based = PeerIdx + 1.
- Outputs: After a successful ceremony, the cluster lock and node signatures are updated as applicable, and a new data directory with validator key shares and metadata is written.

### Add Validators (append new DVs; operators unchanged)

Purpose

- Create and append N new validator keyshares for the existing operator set. Existing validators and operator set remain unchanged.

Participants

- All existing operators (as listed in the current cluster lock).

Threshold

- Unchanged. The existing threshold t is used for all new validators.

Nonce and sequencing

- One `node_pubkeys` broadcast phase across all existing operators, then run N Pedersen DKG instances (one per new validator) using the derived nonce.

Message flow per validator

- Deals, Responses, Justifications via p2p; after success, each node broadcasts `val_pubkey_share` for that validator.

Outputs

- Append N validators to the cluster artifacts (validator public keys, each node’s private share, updated public shares map) and update cluster lock accordingly. Deposit data for new validators is produced/merged if provided.

Operational constraints

- If a node lacks access to existing validator shares, the ceremony can proceed in an "unverified" mode (cluster lock signatures may be skipped by implementations); functionality remains intact but verification must be disabled when starting the cluster.

### Recreate Private Keys (reshare; same operators set)

Purpose

- Rotate/refresh validator private shares for all existing validators without changing validators or operators.

Participants

- All existing operators.

Threshold

- Unchanged (t remains the same).

Nonce and sequencing

- One `node_pubkeys` broadcast across all operators; then run a Pedersen DKG reshare instance for each existing validator using the derived nonce.

Message flow per validator

- Deals, Responses, Justifications via p2p; then `val_pubkey_share` broadcast per validator. Since the validator public key stays the same, `val_pubkey_share` communicates the refreshed per-operator public share.

Outputs

- New private shares for all validators; public commitments unchanged; cluster lock contents unchanged aside from updated node signatures and metadata.

### Add Operators (expand operator set; validators intact)

Purpose

- Add one or more new operators to the cluster while keeping all existing validators and their public keys unchanged.

Participants

- Existing operators plus the new operators being added. All of them participate in the nonce derivation and DKG resharing.

Threshold

- SHOULD remain unchanged to avoid reducing security with legacy shares. Implementations typically keep t constant while increasing n.

Nonce and sequencing

- One `node_pubkeys` reliable broadcast across the combined set (existing + new). For each existing validator, run one Pedersen reshare to expand the set of shares to include the new operators, using the derived nonce.

Message flow per validator

- Deals, Responses, Justifications via p2p among all participants; `val_pubkey_share` broadcast by each participant. The aggregate validator public key remains unchanged.

Outputs

- Updated operator list (existing + new), updated public shares map to cover the expanded operator set, unchanged validator public keys, and updated cluster lock and node signatures. New operators receive their private shares for all validators.

Constraints and validations

- New operator identities must not duplicate existing ones. Nodes that are new to the cluster need not have access to prior validator shares.

### Remove Operators (shrink operator set; validators intact)

Purpose

- Remove one or more operators from the cluster while keeping all validators and their public keys intact.

Participants

- By default, all remaining operators (those not being removed). Optionally, a “participating operators” subset may be specified when removing more than the fault tolerance F = n − t, provided at least t operators participate.
- Operators being removed MAY participate in the nonce phase and exchange to facilitate resharing but MUST NOT produce final signing artifacts; they effectively relinquish shares.

Threshold

- The recommended new threshold t' is ceil(2n'/3), where n' is the new operator count. An override MAY be provided if all participants agree, but must satisfy newT ≤ t' < n'.

Nonce and sequencing

- One `node_pubkeys` reliable broadcast among the participating set; for each existing validator, run one Pedersen reshare to the new operator set using the derived nonce.

Message flow per validator

- Deals, Responses, Justifications via p2p among participating peers; remaining operators broadcast non-empty `val_pubkey_share`. Operators being removed MUST send an empty `val_pubkey_share` (or none) to signal non-participation in the final set.

Outputs

- Updated operator list (remaining operators), new threshold t', updated public shares map restricted to the new set, and updated cluster lock and node signatures written by remaining operators. Removed operators do not write new artifacts.

Constraints and validations

- When removing more than F operators, at least t participants are required. Operators listed for removal must exist in the current lock; "participating operators" (if specified) must also be valid current operators. An operator being removed cannot participate unless explicitly included in the participating set.
