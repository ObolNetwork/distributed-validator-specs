"""Pedersen DKG specification models and constants.

This module defines the message shapes, constants, and a tiny amount of
validation logic.

Pedersen is the **opt-in** DKG algorithm, selected by setting the cluster
definition field `dkg_algorithm` to `pedersen`. The default algorithm is
FROST; see `frost.py`.

Scope
-----
- Message data models mirror the protobuf schema used on the wire.
- Constants capture protocol identifiers and versioning used on libp2p.
- Utility helpers document normative choices (e.g., nonce derivation).

Out of scope
------------
- Cryptographic operations, DKG state machine, and transport. These are
  implementation details in Charon and are documented in the spec docs.
"""

from __future__ import annotations

from hashlib import sha256
from typing import List, Optional

from pydantic import Field

from dv_spec.types.base import StrictBaseModel

# ----------------------------
# Protocol identifiers (libp2p)
# ----------------------------

PEDERSEN_DKG_PROTOCOL_ID = "/charon/dkg/pedersen/1.0.0"
"""Protocol ID prefix for libp2p message routing.

Messages are routed by joining this prefix with the following message IDs:
- node_pubkeys
- val_pubkey_share
- deal_bundle
- resp_bundle
- just_bundle
"""


# ----------------------------
# Utility helpers
# ----------------------------


def generate_nonce_from_node_pubkeys(node_pubkeys: List[bytes]) -> bytes:
    """Derive the Pedersen DKG nonce from the reliably broadcast node pubkeys.

    Nonce := SHA256(concat(marshal(node_i.Public))) over all participants' ephemeral
    BLS public keys collected in step 1 (node_pubkeys signed broadcast), ordered by
    the canonical peer order (cluster operator index / peer index).

    Args:
        node_pubkeys: The exact kyber.Point-encoded public keys as carried in
            `NodePubKeyMessage.public_key`, for all n participants, ordered by
            canonical peer order.

    Returns:
        A 32-byte nonce suitable for the Pedersen DKG configuration.
    """
    buf = b"".join(node_pubkeys)
    return sha256(buf).digest()


# ----------------------------
# Message models (wire schema)
# ----------------------------


class NodePubKeyShares(StrictBaseModel):
    """Optional bundle of BLS public key shares for resharing.

    Each entry is the byte-serialized form of a kyber Point (suite G1), one
    per validator index. Length is equal to the number of validators being
    reshared.
    """

    public_key_shares: List[bytes] = Field(
        default_factory=list,
        description="kyber.Point-encoded public shares for each validator",
    )


class NodePubKeyMessage(StrictBaseModel):
    """Ephemeral node public key announcement.

    Broadcast once per ceremony via reliable broadcast, prior to DKG.
    """

    session_id: bytes = Field(description="Opaque session identifier shared by all nodes")
    public_key: bytes = Field(
        description=(
            "kyber.Point-encoded ephemeral BLS public key; used as input to the "
            "nonce derivation by concatenation across all participants"
        )
    )
    shares: Optional[NodePubKeyShares] = Field(
        default=None,
        description="Optional, present during resharing to carry pub shares",
    )


class ValidatorPubKeyShareMessage(StrictBaseModel):
    """Validator public key share announcement after DKG/reshare.

    Sent once per validator per node via direct p2p.
    """

    session_id: bytes = Field(description="Opaque session identifier shared by all nodes")
    public_key_share: bytes = Field(description="kyber.Point-encoded public key share")


class PedersenDeal(StrictBaseModel):
    """Encrypted DKG deal destined to a specific share index."""

    share_index: int = Field(ge=0, description="Recipient share index (implementation-defined)")
    encrypted_share: bytes = Field(description="Opaque, authenticated ciphertext of the share")


class PedersenDealBundle(StrictBaseModel):
    """Bundle of deals from a dealer in a Pedersen round."""

    dealer_index: int = Field(ge=0, description="Dealer node index")
    deals: List[PedersenDeal] = Field(default_factory=list)
    public: List[bytes] = Field(
        default_factory=list, description="Dealer public commitments (kyber.Point)"
    )
    session_id: bytes = Field(description="Opaque session identifier shared by all nodes")
    signature: bytes = Field(description="Dealer authentication tag over the bundle")


class PedersenResponse(StrictBaseModel):
    """Recipient's response to a dealer's deal."""

    dealer_index: int = Field(ge=0, description="Dealer node index")
    status: bool = Field(description="True if the deal is accepted; False if rejected")


class PedersenResponseBundle(StrictBaseModel):
    """Bundle of per-dealer responses from a single recipient (share index)."""

    share_index: int = Field(ge=0, description="Recipient share index")
    responses: List[PedersenResponse] = Field(default_factory=list)
    session_id: bytes = Field(description="Opaque session identifier shared by all nodes")
    signature: bytes = Field(description="Recipient authentication tag over the bundle")


class PedersenJustification(StrictBaseModel):
    """Justification revealing the scalar for a specific share index."""

    share_index: int = Field(ge=0, description="Index for which the share is revealed")
    share: bytes = Field(description="kyber.Scalar-encoded revealed share")


class PedersenJustificationBundle(StrictBaseModel):
    """Bundle of justifications provided by a dealer for disputed deals."""

    dealer_index: int = Field(ge=0, description="Dealer node index")
    justifications: List[PedersenJustification] = Field(default_factory=list)
    session_id: bytes = Field(description="Opaque session identifier shared by all nodes")
    signature: bytes = Field(description="Dealer authentication tag over the bundle")


# ----------------------------
# Derived artifacts (output)
# ----------------------------

# A Pedersen run produces the same per-validator artifact as a FROST run:
# see `PublicShares` and `ValidatorShare` in `share.py`.
