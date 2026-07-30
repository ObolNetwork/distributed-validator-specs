"""Tests for priority protocol message models and helpers."""

import pytest

from dv_spec.subspecs.priority import (
    LEGACY_PROTOCOL_ID,
    MAX_PRIORITIES,
    PROTOCOL_ID,
    PROTOCOLS,
    Duty,
    DutyType,
    PriorityMsg,
    PriorityResult,
    PriorityScoredResult,
    PriorityTopicProposal,
    PriorityTopicResult,
    calculate_priority_score,
    calculate_result,
    validate_messages,
)
from dv_spec.subspecs.priority.helpers import extract_priority_values


def test_protocol_id() -> None:
    """The preferred ID is spelled like every other protocol in the spec."""
    assert PROTOCOL_ID == "/charon/priority/2.0.0"
    assert PROTOCOL_ID.startswith("/charon/")


def test_legacy_protocol_id() -> None:
    """The original ID has no leading "/" and is still served.

    Every Charon release up to and including v1.11.0-rc1 speaks only this
    spelling, so an implementation that dropped it could not exchange priorities
    with any released Charon. See docs/dv-spec/priority.md.
    """
    assert LEGACY_PROTOCOL_ID == "charon/priority/2.0.0"
    assert not LEGACY_PROTOCOL_ID.startswith("/")

    # Same protocol, same version: the wire format is identical under either ID.
    assert LEGACY_PROTOCOL_ID == PROTOCOL_ID.removeprefix("/")


def test_protocols_precedence() -> None:
    """Both IDs are offered, the slash-prefixed one first."""
    assert PROTOCOLS == (PROTOCOL_ID, LEGACY_PROTOCOL_ID)


def test_max_priorities() -> None:
    """Test max priorities constant."""
    assert MAX_PRIORITIES == 1000


def test_priority_topic_proposal() -> None:
    """Test PriorityTopicProposal creation."""
    proposal = PriorityTopicProposal(topic="protocol", priorities=["A", "B", "C"])

    assert proposal.topic == "protocol"
    assert proposal.priorities == ["A", "B", "C"]


def test_priority_msg() -> None:
    """Test PriorityMsg creation."""
    duty = Duty(slot=123, type=DutyType.ATTESTER)
    topic = PriorityTopicProposal(topic="version", priorities=["v1.0.0", "v0.9.0"])

    msg = PriorityMsg(duty=duty, peer_id="peer1", topics=[topic], signature=b"sig")

    assert msg.duty.slot == 123
    assert msg.peer_id == "peer1"
    assert len(msg.topics) == 1
    assert msg.signature == b"sig"


def test_priority_scored_result() -> None:
    """Test PriorityScoredResult creation."""
    result = PriorityScoredResult(priority="A", score=5997)

    assert result.priority == "A"
    assert result.score == 5997


def test_priority_topic_result() -> None:
    """Test PriorityTopicResult creation."""
    scored1 = PriorityScoredResult(priority="A", score=5997)
    scored2 = PriorityScoredResult(priority="B", score=4000)

    result = PriorityTopicResult(topic="protocol", priorities=[scored1, scored2])

    assert result.topic == "protocol"
    assert len(result.priorities) == 2
    assert result.priorities[0].score == 5997


def test_priority_result() -> None:
    """Test PriorityResult creation."""
    duty = Duty(slot=1, type=DutyType.ATTESTER)
    msg1 = PriorityMsg(duty=duty, peer_id="peer1", topics=[])
    msg2 = PriorityMsg(duty=duty, peer_id="peer2", topics=[])

    topic_result = PriorityTopicResult(
        topic="test", priorities=[PriorityScoredResult(priority="A", score=2000)]
    )

    result = PriorityResult(msgs=[msg1, msg2], topics=[topic_result])

    assert len(result.msgs) == 2
    assert len(result.topics) == 1


def test_calculate_priority_score() -> None:
    """Test priority score calculation."""
    # Priority in 3 peers at positions [0, 1, 2]
    # position_scores = [1000, 999, 998]
    score1 = calculate_priority_score(3, [1000, 999, 998])
    assert score1 == 5997  # 3 * 1000 + (1000 + 999 + 998)

    # Priority in 2 peers at positions [0, 0]
    # position_scores = [1000, 1000]
    score2 = calculate_priority_score(2, [1000, 1000])
    assert score2 == 4000  # 2 * 1000 + (1000 + 1000)

    # Score1 should be higher (more peers)
    assert score1 > score2


def test_validate_messages_success() -> None:
    """Test message validation with valid messages."""
    duty = Duty(slot=1, type=DutyType.ATTESTER)
    msg1 = PriorityMsg(duty=duty, peer_id="peer1", topics=[])
    msg2 = PriorityMsg(duty=duty, peer_id="peer2", topics=[])

    valid, error = validate_messages([msg1, msg2])
    assert valid is True
    assert error == ""


def test_validate_messages_empty() -> None:
    """Test validation fails with empty messages."""
    valid, error = validate_messages([])
    assert valid is False
    assert "Not enough messages" in error


def test_validate_messages_mismatching_duties() -> None:
    """Test validation fails with mismatching duties."""
    msg1 = PriorityMsg(duty=Duty(slot=1, type=DutyType.ATTESTER), peer_id="peer1", topics=[])
    msg2 = PriorityMsg(duty=Duty(slot=2, type=DutyType.ATTESTER), peer_id="peer2", topics=[])

    valid, error = validate_messages([msg1, msg2])
    assert valid is False
    assert "Mismatching duties" in error


def test_validate_messages_duplicate_peer() -> None:
    """Test validation fails with duplicate peer IDs."""
    duty = Duty(slot=1, type=DutyType.ATTESTER)
    msg1 = PriorityMsg(duty=duty, peer_id="peer1", topics=[])
    msg2 = PriorityMsg(duty=duty, peer_id="peer1", topics=[])

    valid, error = validate_messages([msg1, msg2])
    assert valid is False
    assert "Duplicate peer" in error


def test_validate_messages_duplicate_topic() -> None:
    """Test validation fails with duplicate topics in same message."""
    duty = Duty(slot=1, type=DutyType.ATTESTER)
    topic1 = PriorityTopicProposal(topic="protocol", priorities=["A"])
    topic2 = PriorityTopicProposal(topic="protocol", priorities=["B"])
    msg = PriorityMsg(duty=duty, peer_id="peer1", topics=[topic1, topic2])

    valid, error = validate_messages([msg])
    assert valid is False
    assert "Duplicate topic" in error


def test_validate_messages_too_many_priorities() -> None:
    """Test validation fails when topic has too many priorities."""
    duty = Duty(slot=1, type=DutyType.ATTESTER)
    # Create topic with MAX_PRIORITIES priorities (should fail)
    priorities = [f"priority_{i}" for i in range(MAX_PRIORITIES)]
    topic = PriorityTopicProposal(topic="test", priorities=priorities)
    msg = PriorityMsg(duty=duty, peer_id="peer1", topics=[topic])

    valid, error = validate_messages([msg])
    assert valid is False
    assert "Too many priorities" in error


def test_validate_messages_duplicate_priority() -> None:
    """Test validation fails with duplicate priorities in topic."""
    duty = Duty(slot=1, type=DutyType.ATTESTER)
    topic = PriorityTopicProposal(topic="test", priorities=["A", "B", "A"])
    msg = PriorityMsg(duty=duty, peer_id="peer1", topics=[topic])

    valid, error = validate_messages([msg])
    assert valid is False
    assert "Duplicate priority" in error


def test_calculate_result_simple() -> None:
    """Test calculating result with simple inputs."""
    duty = Duty(slot=1, type=DutyType.ATTESTER)

    msg1 = PriorityMsg(
        duty=duty,
        peer_id="peer1",
        topics=[PriorityTopicProposal(topic="protocol", priorities=["A", "B"])],
    )
    msg2 = PriorityMsg(
        duty=duty,
        peer_id="peer2",
        topics=[PriorityTopicProposal(topic="protocol", priorities=["A", "C"])],
    )

    result = calculate_result([msg1, msg2], min_required=2)

    assert result is not None
    assert len(result.topics) == 1
    assert result.topics[0].topic == "protocol"
    # Only "A" appears in both messages
    assert len(result.topics[0].priorities) == 1
    assert result.topics[0].priorities[0].priority == "A"


def test_calculate_result_scoring() -> None:
    """Test that scoring correctly orders priorities."""
    duty = Duty(slot=1, type=DutyType.ATTESTER)

    # 3 peers, all include "A", "B", "C" in different orders
    msg1 = PriorityMsg(
        duty=duty,
        peer_id="peer1",
        topics=[PriorityTopicProposal(topic="test", priorities=["A", "B", "C"])],
    )
    msg2 = PriorityMsg(
        duty=duty,
        peer_id="peer2",
        topics=[PriorityTopicProposal(topic="test", priorities=["B", "A", "C"])],
    )
    msg3 = PriorityMsg(
        duty=duty,
        peer_id="peer3",
        topics=[PriorityTopicProposal(topic="test", priorities=["A", "B", "C"])],
    )

    result = calculate_result([msg1, msg2, msg3], min_required=2)

    assert result is not None
    assert len(result.topics) == 1

    # All three should be included
    priorities = [p.priority for p in result.topics[0].priorities]
    assert len(priorities) == 3

    # "A" should be first (appears at position 0 twice, position 1 once)
    # Score: 3*1000 + (1000 + 999 + 1000) = 5999
    assert priorities[0] == "A"


def test_calculate_result_multiple_topics() -> None:
    """Test calculating result with multiple topics."""
    duty = Duty(slot=1, type=DutyType.ATTESTER)

    msg1 = PriorityMsg(
        duty=duty,
        peer_id="peer1",
        topics=[
            PriorityTopicProposal(topic="protocol", priorities=["A"]),
            PriorityTopicProposal(topic="version", priorities=["v1.0"]),
        ],
    )
    msg2 = PriorityMsg(
        duty=duty,
        peer_id="peer2",
        topics=[
            PriorityTopicProposal(topic="protocol", priorities=["A"]),
            PriorityTopicProposal(topic="version", priorities=["v1.0"]),
        ],
    )

    result = calculate_result([msg1, msg2], min_required=2)

    assert result is not None
    assert len(result.topics) == 2

    # Check both topics are present (order may vary due to hash sorting)
    topics = {t.topic for t in result.topics}
    assert "protocol" in topics
    assert "version" in topics


def test_calculate_result_threshold_filtering() -> None:
    """Test that priorities below threshold are filtered out."""
    duty = Duty(slot=1, type=DutyType.ATTESTER)

    msg1 = PriorityMsg(
        duty=duty,
        peer_id="peer1",
        topics=[PriorityTopicProposal(topic="test", priorities=["A", "B"])],
    )
    msg2 = PriorityMsg(
        duty=duty,
        peer_id="peer2",
        topics=[PriorityTopicProposal(topic="test", priorities=["A", "C"])],
    )
    msg3 = PriorityMsg(
        duty=duty,
        peer_id="peer3",
        topics=[PriorityTopicProposal(topic="test", priorities=["A", "D"])],
    )

    # Require 3 peers to include a priority
    result = calculate_result([msg1, msg2, msg3], min_required=3)

    assert result is not None
    assert len(result.topics) == 1
    # Only "A" appears in all 3 messages
    assert len(result.topics[0].priorities) == 1
    assert result.topics[0].priorities[0].priority == "A"


def test_calculate_result_invalid_input() -> None:
    """Test that invalid inputs return None."""
    # Mismatching duties
    msg1 = PriorityMsg(duty=Duty(slot=1, type=DutyType.ATTESTER), peer_id="peer1", topics=[])
    msg2 = PriorityMsg(duty=Duty(slot=2, type=DutyType.ATTESTER), peer_id="peer2", topics=[])

    result = calculate_result([msg1, msg2], min_required=2)
    assert result is None


def test_extract_priority_values() -> None:
    """Test extracting priority values from result."""
    topic_result = PriorityTopicResult(
        topic="protocol",
        priorities=[
            PriorityScoredResult(priority="A", score=5000),
            PriorityScoredResult(priority="B", score=4000),
        ],
    )
    result = PriorityResult(msgs=[], topics=[topic_result])

    values = extract_priority_values(result, "protocol")
    assert values == ["A", "B"]

    # Non-existent topic
    values = extract_priority_values(result, "nonexistent")
    assert values == []


def test_json_serialization() -> None:
    """Test that models can be serialized to/from JSON."""
    duty = Duty(slot=123, type=DutyType.ATTESTER)
    topic = PriorityTopicProposal(topic="version", priorities=["v1.0.0"])
    msg = PriorityMsg(duty=duty, peer_id="peer1", topics=[topic], signature=b"test")

    # Serialize to JSON
    json_str = msg.model_dump_json()
    assert isinstance(json_str, str)

    # Deserialize from JSON
    msg2 = PriorityMsg.model_validate_json(json_str)
    assert msg2.duty.slot == 123
    assert msg2.peer_id == "peer1"
    assert len(msg2.topics) == 1
    assert msg2.topics[0].topic == "version"


def test_deterministic_ordering() -> None:
    """Test that result calculation is deterministic."""
    duty = Duty(slot=1, type=DutyType.ATTESTER)

    # Create messages in different orders
    msgs1 = [
        PriorityMsg(
            duty=duty,
            peer_id="peer1",
            topics=[PriorityTopicProposal(topic="test", priorities=["A", "B"])],
        ),
        PriorityMsg(
            duty=duty,
            peer_id="peer2",
            topics=[PriorityTopicProposal(topic="test", priorities=["B", "A"])],
        ),
    ]

    msgs2 = list(reversed(msgs1))

    result1 = calculate_result(msgs1, min_required=2)
    result2 = calculate_result(msgs2, min_required=2)

    # Results should be identical
    assert result1 is not None
    assert result2 is not None
    assert len(result1.topics) == len(result2.topics)
    assert result1.topics[0].priorities == result2.topics[0].priorities
