"""Node signature exchange over the cluster lock hash.

The final wire-visible step of every DKG ceremony: each node signs the cluster
lock hash with its ENR (secp256k1) private key and reliably broadcasts that
signature, so every node writes an identical, fully-signed `cluster-lock.json`.

This step is algorithm-independent — FROST, Pedersen, and every operator-edit
protocol run it — and mirrors Charon's `dkg/nodesigs.go`.

Scope
-----
- The `MsgNodeSig` wire model and its reliable-broadcast message ID.
- The "none" sentinel used by protocols that exchange placeholder signatures.
- Receiver-side validation and the collection completion rule.

Out of scope
------------
- secp256k1 signing and recovery; see the cluster files spec for how the
  collected signatures are embedded in the lock file.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import Field

from dv_spec.types.base import StrictBaseModel
from dv_spec.types.uint32 import Uint32

NODE_SIG_MSG_ID = "/charon/dkg/node_sig"
"""Reliable-broadcast message ID carrying `MsgNodeSig`.

Note the absence of a version component: unlike the FROST and bcast IDs, this
message ID is unversioned in Charon.
"""

NONE_DATA = bytes([0xDE, 0xAD, 0xBE, 0xEF])
"""Sentinel standing in for "no signature".

Operator-edit protocols run this exchange even when a participant has nothing
to sign (for example an operator that is being removed). Such a participant
broadcasts this exact 4-byte value instead of a signature, and it is dropped
from the collected set rather than being verified.
"""

SIGNATURE_LENGTH = 65
"""Byte length of a secp256k1 signature in R || S || V form."""


class MsgNodeSig(StrictBaseModel):
    """A node's secp256k1 signature over the cluster lock hash."""

    signature: bytes = Field(
        description=(
            f"{SIGNATURE_LENGTH}-byte R||S||V signature over the lock hash, "
            "or the NONE_DATA sentinel"
        )
    )
    peer_index: Uint32 = Field(description="Sender's 0-based peer index in the cluster")


def verify_node_sig_msg(
    msg: MsgNodeSig,
    sender_peer_index: int,
    own_peer_index: int,
    num_peers: int,
) -> None:
    """Validate a received node signature message before verifying its bytes.

    The claimed `peer_index` is checked against the peer index resolved from the
    libp2p sender identity, so a peer cannot deposit a signature into another
    peer's slot.

    Deliberately absent: any check that `signature` is 65 bytes or the sentinel.
    Charon enforces the length only inside secp256k1 verification (out of scope
    here), and a node that itself holds no key accepts signature bytes of *any*
    length, recording them as the sentinel. Constraining the length at this
    layer would reject messages Charon accepts.

    Args:
        msg: The received message.
        sender_peer_index: Peer index resolved from the sender's libp2p peer ID.
        own_peer_index: This node's peer index.
        num_peers: Number of peers in the cluster.

    Raises:
        ValueError: If the claimed peer index is out of range, refers to this
            node, or does not match the sender's identity.
    """
    if msg.peer_index >= num_peers:
        raise ValueError("invalid peer index")

    if msg.peer_index == own_peer_index:
        raise ValueError("invalid peer index")

    if msg.peer_index != sender_peer_index:
        raise ValueError("sender peer ID does not match claimed peer index")


def collect_node_sigs(sigs: Dict[int, bytes], num_peers: int) -> Optional[List[bytes]]:
    """Return the ordered node signatures once every peer has contributed.

    Collection is complete only when all `n` slots are filled — there is no
    threshold here, because the lock file must carry one signature per operator.
    Sentinel entries are dropped from the result, which is why the returned list
    can be shorter than `num_peers`.

    Args:
        sigs: Signature bytes received so far, keyed by 0-based peer index and
            including this node's own.
        num_peers: Number of peers in the cluster.

    Returns:
        Signatures ordered by peer index with sentinels removed, or None if any
        peer has not contributed yet.
    """
    if any(index not in sigs for index in range(num_peers)):
        return None

    return [sigs[index] for index in range(num_peers) if sigs[index] != NONE_DATA]
