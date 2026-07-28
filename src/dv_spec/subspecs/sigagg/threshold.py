"""The threshold trigger that starts signature aggregation.

Partial signatures arrive from the validator client (locally) and from peers
(over ParSigEx), and are stored per (duty, validator public key). Aggregation
starts the moment exactly `threshold` *matching* partial signatures are held for
one validator, so this module pins down what "matching" means and when the
trigger fires. It mirrors Charon's `core/parsigdb`.

Only the trigger is specified here: the storage, trimming and metrics of the
partial signature database are internal and not wire-visible.

Scope
-----
- The per-share deduplication rule, including the mismatch error.
- The exact condition under which aggregation is triggered.

Out of scope
------------
- Deadline-driven trimming, exempt-duty caps, and memory bounds.
- Signature verification; see `dv_spec.subspecs.sigagg.aggregation`.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from pydantic import Field

from dv_spec.types.base import StrictBaseModel
from dv_spec.types.duty import DutyType
from dv_spec.types.hash import Bytes32

SIGNATURE_LENGTH = 96
"""Byte length of a BLS signature (compressed G2 point)."""

PUBKEY_LENGTH = 48
"""Byte length of a BLS public key or public share (compressed G1 point)."""


class PartialSignature(StrictBaseModel):
    """One node's partial signature over one validator's duty data.

    This is the spec-level projection of Charon's `core.ParSignedData` with the
    duty-specific message root already computed: the wire message carries the
    opaque `data` blob, and each duty type knows how to derive its root from it.
    """

    share_idx: int = Field(
        ge=1,
        description="Signer's share index, 1-based and equal to its peer index plus one",
    )
    signature: bytes = Field(
        min_length=SIGNATURE_LENGTH,
        max_length=SIGNATURE_LENGTH,
        description=f"BLS signature share ({SIGNATURE_LENGTH}-byte compressed G2)",
    )
    message_root: Bytes32 = Field(
        description="Root of the signed message, derived from the duty-specific data"
    )


def store_partial_signature(
    stored: Sequence[PartialSignature],
    incoming: PartialSignature,
) -> Optional[List[PartialSignature]]:
    """Apply the per-share deduplication rule for a newly received signature.

    A node gets exactly one slot per (duty, validator): resending the identical
    signature is harmless, but presenting a *different* one for the same share
    index is a protocol violation that MUST be rejected rather than silently
    overwritten. Charon compares the full JSON encoding of the stored data; this
    spec compares the projected fields, which is equivalent for interop
    purposes.

    Args:
        stored: Signatures already held for this (duty, validator).
        incoming: The newly received signature.

    Returns:
        The updated list including `incoming`, or None if it is an exact
        duplicate and was ignored.

    Raises:
        ValueError: If a different signature is already stored for the same
            share index.
    """
    for existing in stored:
        if existing.share_idx != incoming.share_idx:
            continue

        if existing == incoming:
            return None

        raise ValueError(f"mismatching partial signed data for share_idx {incoming.share_idx}")

    return [*stored, incoming]


def select_threshold_matching(
    duty_type: DutyType,
    sigs: Sequence[PartialSignature],
    threshold: int,
) -> Optional[List[PartialSignature]]:
    """Select the signatures to aggregate, or None if the threshold is not met.

    Two properties are worth calling out, because both are load-bearing:

    - Grouping by message root means `threshold` signatures over *different*
      data never aggregate. Honest nodes can legitimately disagree — for example
      when a peer proposes different block contents — so the count alone is not
      enough.
    - The comparison is `== threshold`, not `>= threshold`. Callers evaluate
      this after storing each signature, so the trigger fires exactly once, on
      the arrival of the threshold-th matching signature. Later signatures for
      the same duty are stored but do not re-trigger aggregation.

    A cluster uses `threshold = ceil(2n/3)`, so `2 * threshold > n` and two
    disjoint groups can never both reach the threshold; the selection is
    therefore unambiguous.

    Args:
        duty_type: Type of the duty the signatures belong to.
        sigs: All signatures held for one (duty, validator).
        threshold: Cluster signing threshold `t`.

    Returns:
        The matching signatures to aggregate, or None if no group has reached
        exactly `threshold` members.
    """
    if len(sigs) < threshold:
        return None

    if duty_type == DutyType.SIGNATURE:
        # DKG signature exchanges carry no message root, so every signature for
        # the duty counts towards the same group.
        return list(sigs) if len(sigs) == threshold else None

    by_root: Dict[bytes, List[PartialSignature]] = {}

    for sig in sigs:
        by_root.setdefault(sig.message_root, []).append(sig)

    for group in by_root.values():
        if len(group) == threshold:
            return group

    return None
