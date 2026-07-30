"""DKG output artifacts shared by all DKG algorithms.

Every DKG ceremony — FROST or Pedersen, fresh generation or reshare — ends
with the same artifact per distributed validator: the aggregate validator
public key, this node's private share, and the public shares of all nodes.
Charon models this once as `dkg/share.Share`, and both algorithms produce it.

Scope
-----
- The per-validator output artifact of a DKG ceremony.

Out of scope
------------
- How the artifact is derived; see `frost.py` and `pedersen.py`.
- Keystore encryption and on-disk layout.
"""

from __future__ import annotations

from typing import Dict

from pydantic import Field

from dv_spec.types.base import StrictBaseModel


class PublicShares(StrictBaseModel):
    """Mapping from share index (1-based) to validator public key share bytes."""

    shares: Dict[int, bytes] = Field(
        default_factory=dict,
        description="Map[1..n] -> 48-byte compressed BLS12-381 G1 public share",
    )


class ValidatorShare(StrictBaseModel):
    """Resulting validator share after a successful DKG/reshare run."""

    validator_pubkey: bytes = Field(
        description="Validator aggregate public key (48-byte compressed G1)"
    )
    secret_share: bytes = Field(description="Private share for this node (32-byte scalar)")
    public_shares: PublicShares = Field(
        description="Public shares of all nodes in ascending share index order",
    )
