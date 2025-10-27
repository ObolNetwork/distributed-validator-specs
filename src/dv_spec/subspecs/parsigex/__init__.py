"""Partial signature exchange (ParSigEx) message models and helpers.

This subpackage defines data models for the partial signature exchange protocol
used to broadcast and receive partially signed validator duty data among
distributed validator nodes.
"""

from dv_spec.types.duty import Duty, DutyType

from .helpers import (
    PROTOCOL_ID,
    count_shares,
    extract_pubkeys,
    is_duty_always_accepted,
    make_simple_gater,
    validate_share_indices,
)
from .message import (
    ParSigExMsg,
    ParSignedData,
    ParSignedDataSet,
)

__all__ = [
    "Duty",
    "DutyType",
    "ParSignedData",
    "ParSignedDataSet",
    "ParSigExMsg",
    "PROTOCOL_ID",
    "count_shares",
    "extract_pubkeys",
    "is_duty_always_accepted",
    "make_simple_gater",
    "validate_share_indices",
]
