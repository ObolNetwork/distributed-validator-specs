## Pedersen DKG interoperability spec

This document describes the Pedersen distributed key generation (DKG) protocol used for generating and resharing BLS validator keys.

Scope:

- Over-the-wire message shapes and fields
- Protocol identifiers, sequencing, and nonce derivation
- Output artifacts

Out of scope: cryptographic routines, Kyber DKG internals, transport reliability;

### Terms and notation

- n: number of participating nodes in the ceremony
- t: threshold used by the DKG (default ceil(2n/3))
- Session ID: a 32-byte value known to all nodes; it is the cluster Definition hash
- Suite: BLS12-381, Kyber G1 for public points and scalars for shares

### Protocol identifiers (libp2p)

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

### Reliable broadcast for node_pubkeys

Why this matters: the ephemeral node public keys are a single-shot, invariant input required before anyone starts the DKG. If a malicious node could equivocate (send different pubkeys to different peers), the group view would diverge. Charon therefore uses a lightweight “signed broadcast” component for `node_pubkeys` instead of plain p2p fan-out.

How it works in Charon (two-phase signed broadcast):

1. Signature collection phase

   - The broadcaster wraps the `NodePubKeyMessage` in a protobuf Any and computes the hash:
     - hash = SHA256(type_url || value) of the Any payload
   - It sends `BCastSigRequest(Id=node_pubkeys, Message=Any(NodePubKeyMessage))` to all peers and collects `BCastSigResponse(signature)` from each.
   - The server validates type constraints via a registered `CheckMessage` for the message ID and applies anti-equivocation dedup per (requester PeerID, msgID): it stores the first hash seen for that requester+ID and refuses to sign a different hash under the same ID later.
   - Each response signature is a K1 (secp256k1) 65-byte R||S||V signature over the hash using the responder’s ENR private key.

2. Broadcast phase
   - The broadcaster verifies all collected signatures locally against the known peer list and then sends a single `BCastMessage(Id, Message=Any(NodePubKeyMessage), Signatures=[...])` to all peers.
   - On receipt, the server re-verifies the whole signature set before invoking the registered callback that finally delivers the `NodePubKeyMessage` to the DKG board.

Properties provided

- Anti-equivocation per broadcaster and message ID: a node cannot get the group to co-sign two different `node_pubkeys` payloads under the same ID because peers only sign one hash per (requester, ID).
- Group-level validation: receivers only accept a `node_pubkeys` message if it carries a full set of valid signatures (one per peer in the configured order) over the exact same hash.
- Dedup and type checks: the component rejects mismatched message types and duplicate signature requests with different hashes.

Contrast with regular libp2p p2p fan-out

- Plain p2p (used for DKG deals/responses/justifications and `val_pubkey_share`) is direct stream sends to each peer with per-stream timeouts. It doesn’t collect group signatures, doesn’t deduplicate across the group, and can’t prevent a sender from delivering divergent payloads to different peers if the application layer doesn’t defend against it.
- Using signed broadcast for `node_pubkeys` adds an all-peers endorsement that the exact same payload was observed and approved by the group before it is considered valid. This is heavier than direct p2p, so Charon limits it to the once-per-ceremony `node_pubkeys` step; the high-churn DKG rounds rely on Kyber’s protocol phases instead.

### Nonce derivation

All participants MUST derive the DKG nonce as:

```
nonce = SHA256(session_id)
```

The `session_id` MUST be identical across all participants for a given ceremony.

### Message schemas (protobuf-equivalent)

The following structures are used over the wire. Implementations must serialize bytes as the canonical encoding of kyber points/scalars in the chosen suite (BLS12-381). Field semantics mirror Charon's `dkg/dkgpb/v1/pedersen.proto`.

- NodePubKeyMessage

  - session_id: bytes
  - public_key: bytes // kyber.Point (ephemeral BLS public key)
  - shares (optional):
    - NodePubKeyShares
      - public_key_shares: repeated bytes // kyber.Point, one per validator index (reshare only)

- ValidatorPubKeyShareMessage

  - session_id: bytes
  - public_key_share: bytes // kyber.Point

- PedersenDealBundle

  - dealer_index: uint32
  - deals: repeated PedersenDeal
    - PedersenDeal
      - share_index: uint32
      - encrypted_share: bytes
  - public: repeated bytes // kyber.Point commitments
  - session_id: bytes
  - signature: bytes // authentication tag

- PedersenResponseBundle

  - share_index: uint32
  - responses: repeated PedersenResponse
    - PedersenResponse
      - dealer_index: uint32
      - status: bool
  - session_id: bytes
  - signature: bytes

- PedersenJustificationBundle
  - dealer_index: uint32
  - justifications: repeated PedersenJustification
    - PedersenJustification
      - share_index: uint32
      - share: bytes // kyber.Scalar
  - session_id: bytes
  - signature: bytes

Reference Python models are provided in `dv_spec.subspecs.dkg.pedersen`.

### Ceremony sequencing

1. Ephemeral node keys broadcast

   - Each node generates an ephemeral BLS key pair using the suite (BLS12-381) and broadcasts `NodePubKeyMessage`.
   - For resharing, include `shares.public_key_shares`: one kyber.Point per validator index, encoding the old validator public share for that node.
   - Nodes wait until they have collected all n `NodePubKeyMessage`s.

2. DKG rounds (per validator)

   - For each validator to produce/reshare, run one Kyber Pedersen DKG instance with config:
     - Suite: BLS12-381
     - Nonce: SHA256(session_id)
     - Nodes: ordered by peer index
     - Threshold: t
     - FastSync: true
     - Auth: BDN BLS on G2
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

### Indexing rules

- Node/peer index: 0-based position in the peer list
- Share index in bundles: 0-based unless specified by library
- Public shares map used in cluster artifacts: 1-based index = PeerIdx + 1

### Resharing notes

- The set of nodes in `oldNodes` and `newNodes` is determined by the rotation being performed; removed nodes must not contribute new shares and should broadcast an empty `ValidatorPubKeyShareMessage`.
- The threshold t' should not be increased in add-operator flows to avoid old shares enabling reconstruction below the new threshold.
