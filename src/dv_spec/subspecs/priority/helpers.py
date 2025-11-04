"""Helper functions and utilities for Priority protocol.

Provides scoring calculation, result computation, and validation logic.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Hashable

from .message import (
    PriorityMsg,
    PriorityResult,
    PriorityScoredResult,
    PriorityTopicProposal,
    PriorityTopicResult,
)

# Protocol constants
PROTOCOL_ID = "/charon/priority/2.0.0"
MAX_PRIORITIES = 1000  # Maximum priorities per topic
COUNT_WEIGHT = 1000  # Weight for peer count in scoring


def calculate_priority_score(peer_count: int, position_scores: list[int]) -> int:
    """Calculate the overall score for a priority.

    The score is calculated as:
        overall_score = (peer_count * COUNT_WEIGHT) + sum(position_scores)

    where each position_score = COUNT_WEIGHT - position_index

    This ensures priorities are ordered by:
    1. Number of peers that included them (higher is better)
    2. Average position across peers (earlier is better)

    Args:
        peer_count: Number of peers that included this priority
        position_scores: List of position scores from each peer

    Returns:
        Overall score

    Example:
        >>> # Priority appears in 3 peers at positions [0, 1, 2]
        >>> calculate_priority_score(3, [1000, 999, 998])
        5997
        >>> # Priority appears in 2 peers at positions [0, 0]
        >>> calculate_priority_score(2, [1000, 1000])
        4000
    """
    return (peer_count * COUNT_WEIGHT) + sum(position_scores)


def _hash_value(value: Any) -> Hashable:
    """Create a hashable representation of a value for deduplication.

    Args:
        value: Value to hash (typically string or bytes)

    Returns:
        Hashable representation
    """
    if isinstance(value, (str, int, float, bool, type(None))):
        return value
    if isinstance(value, bytes):
        return value
    if isinstance(value, (list, tuple)):
        return tuple(_hash_value(v) for v in value)
    if isinstance(value, dict):
        return tuple(sorted((k, _hash_value(v)) for k, v in value.items()))
    # Fallback: convert to string
    return str(value)


def validate_messages(msgs: list[PriorityMsg], min_required: int = 1) -> tuple[bool, str]:
    """Validate a list of priority messages.

    Checks:
    - Messages are not empty
    - All messages have the same duty
    - No duplicate peer IDs
    - No duplicate topics per peer
    - No topic exceeds MAX_PRIORITIES
    - No duplicate priorities within a topic

    Args:
        msgs: List of priority messages to validate
        min_required: Minimum required messages (default: 1)

    Returns:
        Tuple of (is_valid, error_message)

    Example:
        >>> from dv_spec.types.duty import Duty, DutyType
        >>> msg1 = PriorityMsg(
                duty=Duty(slot=1, type=DutyType.ATTESTER),
                peer_id="peer1", topics=[]
            )
        >>> msg2 = PriorityMsg(
                duty=Duty(slot=1, type=DutyType.ATTESTER),
                peer_id="peer2", topics=[]
            )
        >>> validate_messages([msg1, msg2])
        (True, '')
    """
    if len(msgs) < min_required:
        return False, f"Not enough messages: {len(msgs)} < {min_required}"

    # Check all have same duty
    first_duty = msgs[0].duty
    for msg in msgs[1:]:
        if msg.duty != first_duty:
            return False, "Mismatching duties"

    # Check for duplicate peers
    peer_ids = set()
    for msg in msgs:
        if msg.peer_id in peer_ids:
            return False, f"Duplicate peer: {msg.peer_id}"
        peer_ids.add(msg.peer_id)

    # Validate each message's topics
    for msg in msgs:
        topic_hashes = set()
        for topic_proposal in msg.topics:
            # Check for duplicate topics
            topic_hash = _hash_value(topic_proposal.topic)
            if topic_hash in topic_hashes:
                return False, f"Duplicate topic in peer {msg.peer_id}"
            topic_hashes.add(topic_hash)

            # Check priority count limit
            if len(topic_proposal.priorities) >= MAX_PRIORITIES:
                return False, f"Too many priorities in topic: {len(topic_proposal.priorities)}"

            # Check for duplicate priorities within topic
            priority_hashes = set()
            for priority in topic_proposal.priorities:
                priority_hash = _hash_value(priority)
                if priority_hash in priority_hashes:
                    return False, "Duplicate priority in topic"
                priority_hashes.add(priority_hash)

    return True, ""


def calculate_result(msgs: list[PriorityMsg], min_required: int) -> PriorityResult | None:
    """Calculate cluster-wide priority result from peer messages.

    This is the deterministic function that all nodes execute to compute
    the same result from the same inputs.

    Algorithm:
    1. Validate all messages
    2. Group priority proposals by topic
    3. For each priority in each topic:
       - Count how many peers included it
       - Calculate position scores from each peer
       - Compute overall score
    4. Filter priorities that appear in fewer than min_required peers
    5. Sort priorities by score (descending)
    6. Sort topics deterministically by hash

    Args:
        msgs: List of priority messages from all peers
        min_required: Minimum number of peers required to include a priority

    Returns:
        PriorityResult with calculated scores, or None if validation fails

    Example:
        >>> from dv_spec.types.duty import Duty, DutyType
        >>> msg1 = PriorityMsg(
        ...     duty=Duty(slot=1, type=DutyType.ATTESTER),
        ...     peer_id="peer1",
        ...     topics=[PriorityTopicProposal(topic="protocol", priorities=["A", "B"])],
        ... )
        >>> msg2 = PriorityMsg(
        ...     duty=Duty(slot=1, type=DutyType.ATTESTER),
        ...     peer_id="peer2",
        ...     topics=[PriorityTopicProposal(topic="protocol", priorities=["A", "C"])],
        ... )
        >>> result = calculate_result([msg1, msg2], min_required=2)
        >>> result.topics[0].priorities[0].priority  # "A" should be first
        'A'
    """
    # Validate messages
    valid, error = validate_messages(msgs, min_required=min_required)
    if not valid:
        return None

    # Sort messages by peer_id for deterministic processing
    sorted_msgs = sorted(msgs, key=lambda m: m.peer_id)

    # Group proposals by topic
    proposals_by_topic: dict[Hashable, list[PriorityTopicProposal]] = defaultdict(list)
    for msg in sorted_msgs:
        for topic_proposal in msg.topics:
            topic_hash = _hash_value(topic_proposal.topic)
            proposals_by_topic[topic_hash] = proposals_by_topic[topic_hash] + [topic_proposal]

    # Calculate results for each topic
    topic_results: list[PriorityTopicResult] = []
    for proposals in proposals_by_topic.values():
        # Get the actual topic value from the first proposal
        topic_value = proposals[0].topic

        # Track scores and positions for each priority
        priority_data: dict[
            Hashable, dict[str, Any]
        ] = {}  # priority_hash -> {value, peer_count, position_scores}

        for proposal in proposals:
            for position, priority in enumerate(proposal.priorities):
                priority_hash = _hash_value(priority)

                if priority_hash not in priority_data:
                    priority_data[priority_hash] = {
                        "value": priority,
                        "peer_count": 0,
                        "position_scores": [],
                    }

                priority_data[priority_hash]["peer_count"] += 1
                position_score = COUNT_WEIGHT - position
                priority_data[priority_hash]["position_scores"].append(position_score)

        # Calculate final scores and filter by min_required
        scored_priorities: list[tuple[Any, int, Hashable]] = []  # (value, score, hash)
        for priority_hash, data in priority_data.items():
            if data["peer_count"] >= min_required:
                score = calculate_priority_score(data["peer_count"], data["position_scores"])
                scored_priorities.append((data["value"], score, priority_hash))

        # Sort by score (descending), then by hash (for deterministic tie-breaking)
        scored_priorities.sort(key=lambda x: (-x[1], str(x[2])))

        # Build result
        result_priorities = [
            PriorityScoredResult(priority=value, score=score)
            for value, score, _ in scored_priorities
        ]

        topic_results.append(PriorityTopicResult(topic=topic_value, priorities=result_priorities))

    # Sort topics by hash for deterministic output
    topic_results.sort(key=lambda t: str(_hash_value(t.topic)))

    return PriorityResult(msgs=sorted_msgs, topics=topic_results)


def extract_priority_values(result: PriorityResult, topic: Any) -> list[Any]:
    """Extract priority values (without scores) for a specific topic.

    Args:
        result: Priority result
        topic: Topic to extract priorities for

    Returns:
        List of priority values in order

    Example:
        >>> # Assuming result has topic "protocol" with priorities ["A", "B"]
        >>> extract_priority_values(result, "protocol")
        ['A', 'B']
    """
    topic_hash = _hash_value(topic)
    for topic_result in result.topics:
        if _hash_value(topic_result.topic) == topic_hash:
            return [p.priority for p in topic_result.priorities]
    return []
