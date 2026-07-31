"""Cluster-wide priority scoring.

Each node broadcasts its own preference order per topic; every node then reduces
the collected messages to one cluster-wide order. The reduction MUST be a pure
function of the message set: nodes that disagree on the result disagree on which
protocol to speak, so any nondeterminism here is a split-brain bug rather than a
cosmetic one. Mirrors Charon's `core/priority/calculate.go`.

The score of a priority is `COUNT_WEIGHT - position`, summed over the nodes that
proposed it. Because `COUNT_WEIGHT` exceeds the largest possible position, this
orders by the number of supporting nodes first and by preference position only
within an equal count — a priority that many nodes rank last still beats one
that few nodes rank first.

Scope
-----
- Input validation, scoring, the inclusion threshold, and result ordering.

Out of scope
------------
- Message signing and exchange, and the priority instance lifecycle.
- Which topics and priorities a node proposes; see
  `dv_spec.subspecs.infosync.infosync`.
"""

from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

from dv_spec.encoding.proto import encode_any_string
from dv_spec.encoding.ssz import hash_proto
from dv_spec.subspecs.priority.message import (
    PriorityMsg,
    PriorityResult,
    PriorityScoredResult,
    PriorityTopicResult,
)

MAX_PRIORITIES = 1000
"""Maximum priorities a node may propose for one topic."""

COUNT_WEIGHT = MAX_PRIORITIES
"""Weight of one supporting node, in score units.

Equal to `MAX_PRIORITIES` so that supporting-node count always dominates
preference position: the largest position penalty a single node can apply is
`MAX_PRIORITIES - 1`, one less than the gain from a single extra supporter.
"""


def priority_hash(value: str) -> bytes:
    """Return the hash a topic or priority is identified by.

    Topics and priorities travel as `Any`-wrapped `google.protobuf.Value`
    strings, and are compared by the hash of that encoding rather than by the
    string itself.
    """
    return hash_proto(encode_any_string(value))


def validate_msgs(msgs: Sequence[PriorityMsg]) -> None:
    """Reject a message set that cannot be scored deterministically.

    Each rule closes off a way for one node to skew the result: duplicate peers
    or duplicate priorities would let a node vote more than once, mismatching
    duties would mix unrelated instances, and the priority cap bounds the work
    an unbounded list could impose.

    Raises:
        ValueError: If the set is empty, contains duplicate peers, mixes duties,
            or if any peer repeats a topic, repeats a priority within a topic, or
            proposes `MAX_PRIORITIES` or more priorities for one topic.
    """
    if not msgs:
        raise ValueError("messages empty")

    duty = msgs[0].duty
    seen_peers: set[str] = set()

    for msg in msgs:
        if msg.duty != duty:
            raise ValueError("mismatching duties")

        if msg.peer_id in seen_peers:
            raise ValueError("duplicate peer")

        seen_peers.add(msg.peer_id)

        seen_topics: set[bytes] = set()
        for topic in msg.topics:
            topic_hash = priority_hash(topic.topic)
            if topic_hash in seen_topics:
                raise ValueError("duplicate topic")

            seen_topics.add(topic_hash)

            if len(topic.priorities) >= MAX_PRIORITIES:
                raise ValueError("max priority reached")

            seen_priorities: set[bytes] = set()
            for priority in topic.priorities:
                priority_key = priority_hash(priority)
                if priority_key in seen_priorities:
                    raise ValueError("duplicate priority")

                seen_priorities.add(priority_key)


def calculate_result(msgs: Sequence[PriorityMsg], min_required: int) -> PriorityResult:
    """Reduce per-peer priorities to one cluster-wide result.

    Ties are broken by the peer that proposed the priority first, in ascending
    peer ID order — which is why the messages are sorted by peer ID up front and
    why the sort by score MUST be stable. Charon sorts stably as of `6054bcb2`.
    Releases up to and including `v1.11.0-rc1` used Go's `slices.SortFunc`, which
    is not stable, and agreed with this only because Go's pdqsort falls back to
    insertion sort below thirteen elements — true for any realistic number of
    priorities in a topic, but not something to rely on.

    Args:
        msgs: One message per participating peer.
        min_required: Minimum number of supporting peers for a priority to be
            included, typically the cluster threshold.

    Returns:
        The result, with topics ordered by topic hash and each topic's priorities
        ordered by descending score.

    Raises:
            ValueError: If `validate_msgs` rejects the message set.
    """
    validate_msgs(msgs)

    ordered_msgs = sorted(msgs, key=lambda msg: msg.peer_id)

    # Group proposals by topic, preserving peer order within each topic.
    proposals_by_topic: Dict[bytes, List[Tuple[str, List[str]]]] = {}
    for msg in ordered_msgs:
        for topic in msg.topics:
            key = priority_hash(topic.topic)
            proposals_by_topic.setdefault(key, []).append((topic.topic, list(topic.priorities)))

    # A priority is included only once its score exceeds what min_required - 1
    # peers ranking it first could produce.
    min_score = (min_required - 1) * COUNT_WEIGHT
    topic_results: List[Tuple[bytes, PriorityTopicResult]] = []

    for topic_hash, proposals in proposals_by_topic.items():
        scores: Dict[bytes, int] = {}
        seen_order: List[bytes] = []
        values: Dict[bytes, str] = {}

        for _, priorities in proposals:
            for position, priority in enumerate(priorities):
                key = priority_hash(priority)
                if key not in scores:
                    scores[key] = 0
                    seen_order.append(key)

                scores[key] += COUNT_WEIGHT - position
                values[key] = priority

        ranked = sorted(seen_order, key=lambda key: -scores[key])
        topic_results.append(
            (
                topic_hash,
                PriorityTopicResult(
                    topic=proposals[0][0],
                    priorities=[
                        PriorityScoredResult(priority=values[key], score=scores[key])
                        for key in ranked
                        if scores[key] > min_score
                    ],
                ),
            )
        )

    topic_results.sort(key=lambda item: item[0])

    return PriorityResult(msgs=list(msgs), topics=[result for _, result in topic_results])
