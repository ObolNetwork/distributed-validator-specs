import pytest

from dv_spec.subspecs.priority.message import PriorityMsg, PriorityTopicProposal
from dv_spec.subspecs.priority.scoring import (
    COUNT_WEIGHT,
    MAX_PRIORITIES,
    calculate_result,
    priority_hash,
    validate_msgs,
)
from dv_spec.types.duty import Duty, DutyType

DUTY = Duty(slot=1, type=DutyType.UNKNOWN)


def msg(peer_id: str, priorities: list[str], topic: str = "versions") -> PriorityMsg:
    return PriorityMsg(
        duty=DUTY,
        peer_id=peer_id,
        topics=[PriorityTopicProposal(topic=topic, priorities=priorities)],
    )


def test_count_weight_dominates_position() -> None:
    # One extra supporter must outweigh the worst possible position penalty.
    assert COUNT_WEIGHT > MAX_PRIORITIES - 1


def test_priority_hash_distinguishes_values() -> None:
    assert priority_hash("v1") != priority_hash("v2")
    assert priority_hash("v1") == priority_hash("v1")


def test_validate_msgs_rejects_empty_set() -> None:
    with pytest.raises(ValueError, match="messages empty"):
        validate_msgs([])


def test_validate_msgs_rejects_mismatching_duties() -> None:
    other = PriorityMsg(duty=Duty(slot=2, type=DutyType.UNKNOWN), peer_id="1", topics=[])

    with pytest.raises(ValueError, match="mismatching duties"):
        validate_msgs([msg("0", ["v1"]), other])


def test_validate_msgs_rejects_duplicate_peer() -> None:
    with pytest.raises(ValueError, match="duplicate peer"):
        validate_msgs([msg("0", ["v1"]), msg("0", ["v2"])])


def test_validate_msgs_rejects_duplicate_topic() -> None:
    duplicated = PriorityMsg(
        duty=DUTY,
        peer_id="0",
        topics=[
            PriorityTopicProposal(topic="versions", priorities=["v1"]),
            PriorityTopicProposal(topic="versions", priorities=["v2"]),
        ],
    )

    with pytest.raises(ValueError, match="duplicate topic"):
        validate_msgs([duplicated])


def test_validate_msgs_rejects_duplicate_priority() -> None:
    with pytest.raises(ValueError, match="duplicate priority"):
        validate_msgs([msg("0", ["v1", "v1"])])


def test_validate_msgs_rejects_too_many_priorities() -> None:
    with pytest.raises(ValueError, match="max priority reached"):
        validate_msgs([msg("0", [f"v{i}" for i in range(MAX_PRIORITIES)])])


def test_calculate_result_orders_topics_by_topic_hash() -> None:
    both = PriorityMsg(
        duty=DUTY,
        peer_id="0",
        topics=[
            PriorityTopicProposal(topic="versions", priorities=["v1"]),
            PriorityTopicProposal(topic="protocols", priorities=["p1"]),
        ],
    )

    topics = [topic.topic for topic in calculate_result([both], 1).topics]
    assert topics == sorted(topics, key=priority_hash)


def test_calculate_result_keeps_input_messages() -> None:
    msgs = [msg("0", ["v1"]), msg("1", ["v1"])]

    assert calculate_result(msgs, 1).msgs == msgs
