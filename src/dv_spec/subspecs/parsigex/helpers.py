"""Helper functions and utilities for ParSigEx protocol.

Provides verification helpers, encoding utilities, and protocol constants.
"""

from __future__ import annotations

from typing import Callable

from .message import Duty, DutyType, ParSignedDataSet

# Protocol constants
PROTOCOL_ID = "/charon/parsigex/2.0.0"


def is_duty_always_accepted(duty: Duty) -> bool:
    """Check if a duty type is always accepted (no gating required).

    DutyExit and DutyBuilderRegistration are lifecycle operations that
    are always relevant.
    """
    return duty.type in {DutyType.EXIT, DutyType.BUILDER_REGISTRATION}


def make_simple_gater(expected_duties: set[Duty]) -> Callable[[Duty], bool]:
    """Create a simple duty gater function that accepts only expected duties.

    Args:
        expected_duties: Set of duties that should be accepted

    Returns:
        A gater function that returns True if the duty is accepted
    """

    def gater(duty: Duty) -> bool:
        if is_duty_always_accepted(duty):
            return True
        return duty in expected_duties

    return gater


def extract_pubkeys(data_set: ParSignedDataSet) -> list[str]:
    """Extract all validator public keys from a ParSignedDataSet.

    Args:
        data_set: The partial signature data set

    Returns:
        List of validator public key strings
    """
    return list(data_set.set.keys())


def count_shares(data_set: ParSignedDataSet) -> int:
    """Count the number of partial signatures in a data set.

    Args:
        data_set: The partial signature data set

    Returns:
        Number of partial signatures
    """
    return len(data_set.set)


def validate_share_indices(data_set: ParSignedDataSet, expected_range: tuple[int, int]) -> bool:
    """Validate that all share indices are within expected range.

    Args:
        data_set: The partial signature data set
        expected_range: Tuple of (min_idx, max_idx) inclusive

    Returns:
        True if all share indices are valid
    """
    min_idx, max_idx = expected_range
    for par_sig in data_set.set.values():
        if not (min_idx <= par_sig.share_idx <= max_idx):
            return False
    return True
