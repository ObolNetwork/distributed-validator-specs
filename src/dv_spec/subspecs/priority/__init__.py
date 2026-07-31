"""Priority protocol specification.

This subpackage defines data models for the Priority protocol used to achieve
cluster-wide consensus on ordered lists of arbitrary priorities among distributed
validator nodes.
"""

from dv_spec.types.duty import Duty, DutyType

from .helpers import (
    LEGACY_PROTOCOL_ID,
    PROTOCOL_ID,
    PROTOCOLS,
)
from .message import (
    PriorityMsg,
    PriorityResult,
    PriorityScoredResult,
    PriorityTopicProposal,
    PriorityTopicResult,
)
from .scoring import (
    MAX_PRIORITIES,
    calculate_result,
    validate_msgs,
)

__all__ = [
    "Duty",
    "DutyType",
    "PriorityMsg",
    "PriorityTopicProposal",
    "PriorityResult",
    "PriorityTopicResult",
    "PriorityScoredResult",
    "PROTOCOL_ID",
    "LEGACY_PROTOCOL_ID",
    "PROTOCOLS",
    "MAX_PRIORITIES",
    "calculate_result",
    "validate_msgs",
]
