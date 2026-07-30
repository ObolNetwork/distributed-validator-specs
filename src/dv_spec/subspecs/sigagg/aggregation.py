"""BLS threshold aggregation of partial signatures.

Turns `threshold` partial signatures into the single group signature that gets
broadcast to the beacon chain. The group signature must verify under the
validator's aggregate public key, which pins the interpolation exactly: the
share indices are the evaluation points and the group signature is the value at
zero. Mirrors Charon's `core/sigagg` and `tbls.ThresholdAggregate`.

Scope
-----
- Partial signature verification rules applied before aggregation.
- Which signatures feed the aggregation and how they are keyed.
- The Lagrange coefficients that define the aggregate.
- Verification of the resulting group signature.

Out of scope
------------
- The BLS group arithmetic itself; see `dv_spec.crypto.bls`.
- Ethereum signing root and domain computation; see the ParSigEx spec.
"""

from __future__ import annotations

from typing import Dict, Iterable, Mapping, Sequence

from dv_spec.crypto.bls import BLS_MODULUS, lagrange_coefficient

from .threshold import PartialSignature

__all__ = [
    "BLS_MODULUS",
    "aggregation_coefficients",
    "lagrange_coefficient",
    "select_aggregation_inputs",
    "verify_share_idx",
]


def verify_share_idx(share_idx: int, public_shares: Mapping[int, bytes]) -> bytes:
    """Resolve the public share a partial signature must verify against.

    A partial signature is only meaningful against the public share of the node
    that produced it, so an unknown share index is rejected outright rather than
    being verified against some other node's key.

    Args:
        share_idx: The 1-based share index claimed by the partial signature.
        public_shares: Public shares of the validator, keyed by 1-based share
            index, as recorded in the cluster lock.

    Returns:
        The public share to verify the partial signature against.

    Raises:
        ValueError: If the share index is not present in the public shares.
    """
    pubshare = public_shares.get(share_idx)
    if pubshare is None:
        raise ValueError(f"invalid shareIdx {share_idx}")

    return pubshare


def aggregation_coefficients(indices: Sequence[int]) -> Dict[int, int]:
    """Compute the Lagrange coefficient of every participating share index.

    The group signature is then `sum(coefficient_i * signature_i)` in G2.

    Args:
        indices: All share indices participating in the aggregation.

    Returns:
        Mapping from share index to its coefficient.

    Example:
        >>> coefficients = aggregation_coefficients([1, 2, 3])
        >>> coefficients[1], coefficients[3]
        (3, 1)
        >>> coefficients[2] == BLS_MODULUS - 3
        True
    """
    return {index: lagrange_coefficient(index, indices) for index in indices}


def select_aggregation_inputs(
    sigs: Iterable[PartialSignature],
    threshold: int,
) -> Dict[int, bytes]:
    """Key the partial signatures by share index for aggregation.

    Keying by share index collapses any repeated share index, so the count is
    re-checked afterwards: `threshold` signatures from fewer than `threshold`
    distinct nodes do not authorise an aggregate.

    Args:
        sigs: The matching partial signatures selected by the threshold trigger.
        threshold: Cluster signing threshold `t`.

    Returns:
        Mapping from 1-based share index to signature bytes.

    Raises:
        ValueError: If fewer than `threshold` signatures were supplied, or if
            they come from fewer than `threshold` distinct share indices.
    """
    sigs = list(sigs)

    if len(sigs) < threshold:
        raise ValueError("require threshold signatures")

    by_share_idx = {sig.share_idx: sig.signature for sig in sigs}

    if len(by_share_idx) < threshold:
        raise ValueError(
            f"number of partial signatures less than threshold: "
            f"threshold {threshold}, got {len(by_share_idx)}"
        )

    return by_share_idx
