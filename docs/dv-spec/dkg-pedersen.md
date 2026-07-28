# Pedersen DKG Interoperability Spec

This document describes the Pedersen distributed key generation (DKG) protocol used for generating and resharing BLS validator keys.

Pedersen is the **opt-in** algorithm, selected by setting the cluster definition field `dkg_algorithm` to `pedersen`. The default is [FROST](dkg-frost.md).

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
- Python models and helper: `dv_spec.subspecs.reliable_bcast`

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

See the Python reference implementation: [`dv_spec.subspecs.dkg.pedersen`](../../src/dv_spec/subspecs/dkg/pedersen.py), covering `NodePubKeyMessage`, `ValidatorPubKeyShareMessage`, `PedersenDealBundle`, `PedersenResponseBundle`, and `PedersenJustificationBundle`.

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
   - For each validator, the resulting artifact is the same one a FROST run produces (see [`dv_spec.subspecs.dkg.share`](../../src/dv_spec/subspecs/dkg/share.py)):
     - validator_pubkey: aggregate validator public key (48-byte compressed G1)
     - secret_share: this node's private share (32-byte scalar)
     - public_shares: map[int->bytes], share indices 1..n for the nodes that will remain after resharing
   - The node signature exchange over the cluster lock hash that concludes the ceremony is shared with FROST; see [FROST DKG](dkg-frost.md#node-signature-exchange).

## Indexing Rules

- Node/peer index: 0-based position in the peer list
- Share index in bundles: 0-based unless specified by library
- Public shares map used in cluster artifacts: 1-based index = PeerIdx + 1

## Use in Cluster Edit Operations

Every [cluster edit protocol](dkg-cluster-edits.md) — reshare, add, remove and
replace operators — uses a Pedersen **reshare**, regardless of the cluster
definition's `dkg_algorithm`. A reshare requires participants to contribute
existing shares, which the FROST flow does not provide. That document specifies
who participates, the threshold rules, and the share index assignment; the
Pedersen-specific mechanics of a reshare are:

- Session and nonce: the session ID is the cluster definition hash of the lock
  being edited. A fresh nonce is derived per ceremony from the reliably
  broadcast `node_pubkeys` of the participating peers, so no two ceremonies
  share a nonce.
- Old shares are contributed by nodes that hold them. A node joining the cluster
  holds none, and instead restores the public polynomial commitments from the
  exchanged public key shares, validating that they recover the expected
  validator public key.
- Added and removed peer sets MUST be disjoint, and at least one node from the
  original cluster must remain.
- A node leaving the cluster receives no new share and MUST broadcast an empty
  `ValidatorPubKeyShareMessage` to signal non-participation. Assembling nodes
  skip empty entries when building the public shares map.
- Node public key exchange carries the public key shares of the node's existing
  shares (`NodePubKeyShares`), which is what lets joining nodes reconstruct the
  commitments.
