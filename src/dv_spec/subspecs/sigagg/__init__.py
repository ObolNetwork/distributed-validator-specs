"""Threshold signature aggregation specification.

Covers the trigger that decides when enough partial signatures have been
collected, and the BLS threshold aggregation that turns them into the group
signature broadcast to the beacon chain.
"""

from .aggregation import (
    BLS_MODULUS,
    aggregation_coefficients,
    lagrange_coefficient,
    select_aggregation_inputs,
    verify_share_idx,
)
from .threshold import (
    PUBKEY_LENGTH,
    SIGNATURE_LENGTH,
    PartialSignature,
    select_threshold_matching,
    store_partial_signature,
)

__all__ = [
    "BLS_MODULUS",
    "PUBKEY_LENGTH",
    "SIGNATURE_LENGTH",
    "PartialSignature",
    "aggregation_coefficients",
    "lagrange_coefficient",
    "select_aggregation_inputs",
    "select_threshold_matching",
    "store_partial_signature",
    "verify_share_idx",
]
