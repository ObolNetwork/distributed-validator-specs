"""Regenerate the test vector suites this spec computes itself.

Run after changing anything the vectors cover:

    uv run python scripts/generate_test_vectors.py

`test_vectors/qbft_hashing.json` is deliberately *not* regenerated here. Its
values come from Charon rather than from this spec, via
`test_vectors/charon/hashproto_generator.go`; see `test_vectors/README.md`.

The priority suite's expected results are transcribed from Charon's own
`TestCalculateResults` table, so this script asserts the spec reproduces them
rather than recording whatever the spec happens to produce.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from dv_spec.subspecs.consensus.timer.timer import (
    NANOSECONDS_PER_SECOND,
    eager_double_linear_deadline_nanos,
    eager_double_linear_timeout,
    get_duty_start_delay_nanos,
)
from dv_spec.subspecs.priority.message import PriorityMsg, PriorityTopicProposal
from dv_spec.subspecs.priority.scoring import calculate_result
from dv_spec.types.duty import Duty, DutyType

REPO_ROOT = Path(__file__).resolve().parent.parent
VECTOR_ROOT = REPO_ROOT / "test_vectors"

CHARON_REF = "2eb6798e3091b09f3eb659076e044dfe404e46d7"

MAINNET_GENESIS = 1606824023
"""Ethereum mainnet genesis, in unix seconds."""


def write(suite: str, data: Dict[str, Any]) -> None:
    """Write one vector suite to disk."""
    path = VECTOR_ROOT / f"{suite}.json"
    path.write_text(json.dumps(data, indent=2) + "\n")
    print(f"wrote {path.relative_to(REPO_ROOT)}")


def timer_deadlines() -> Dict[str, Any]:
    """Round deadline table for the eager double linear timer."""
    # 12s mainnet, 5s Gnosis Chain (not divisible by three, so it pins the
    # integer division), and 1s to exercise a sub-second third.
    slot_durations = [12, 5, 1]
    duty_types = [
        DutyType.PROPOSER,
        DutyType.ATTESTER,
        DutyType.AGGREGATOR,
        DutyType.SYNC_CONTRIBUTION,
        DutyType.SYNC_MESSAGE,
        DutyType.RANDAO,
    ]
    slots = [0, 1, 7231]
    rounds = [1, 2, 3, 10]

    cases: List[Dict[str, Any]] = []
    for slot_duration in slot_durations:
        slot_duration_nanos = slot_duration * NANOSECONDS_PER_SECOND
        for duty_type in duty_types:
            for slot in slots:
                for round_num in rounds:
                    duty = Duty(slot=slot, type=duty_type)
                    delay = get_duty_start_delay_nanos(duty_type, slot_duration_nanos)
                    timeout = round(
                        eager_double_linear_timeout(duty_type, round_num) * NANOSECONDS_PER_SECOND
                    )
                    cases.append(
                        {
                            "name": f"{duty_type.name.lower()}_slot{slot}_round{round_num}"
                            f"_slotdur{slot_duration}s",
                            "input": {
                                "genesis_time_nanos": MAINNET_GENESIS * NANOSECONDS_PER_SECOND,
                                "slot_duration_nanos": slot_duration_nanos,
                                "slot": slot,
                                "duty_type": int(duty_type),
                                "duty_type_name": duty_type.name,
                                "round": round_num,
                            },
                            "duty_start_delay_nanos": delay,
                            "round_timeout_nanos": timeout,
                            "deadline_nanos": eager_double_linear_deadline_nanos(
                                duty,
                                round_num,
                                MAINNET_GENESIS * NANOSECONDS_PER_SECOND,
                                slot_duration_nanos,
                            ),
                        }
                    )

    return {
        "suite": "timer_deadlines",
        "description": (
            "First-expiry deadlines of the eager double linear consensus round "
            "timer. deadline_nanos = genesis + slot_duration * slot + "
            "duty_start_delay + round_timeout, all in integer nanoseconds."
        ),
        "provenance": {
            "source": "spec",
            "charon_ref": CHARON_REF,
            "generated_by": "scripts/generate_test_vectors.py",
            "note": (
                "Computed by this spec from Charon's core/consensus/timer/roundtimer.go. "
                "Integer nanoseconds are normative: Charon uses time.Duration, and a "
                "float cannot hold a unix timestamp to nanosecond resolution."
            ),
        },
        "cases": cases,
    }


PRIORITY_SETS = {
    "v1": ["v1"],
    "v2": ["v2", "v1"],
    "v3": ["v3", "v2"],
    "xy": ["x", "y"],
    "yx": ["y", "x"],
}

# Transcribed from charon core/priority/calculate_internal_test.go
# TestCalculateResults: (name, per-peer priority sets, expected order, expected
# scores, slot). N=5, Q=3. Scores are only asserted when a result is expected.
PRIORITY_TABLE = [
    ("1*v1", ["v1"], [], [], 0),
    ("Q-1*v1", ["v1", "v1"], [], [], 1),
    ("Q*v1", ["v1", "v1", "v1"], ["v1"], [3000], 2),
    ("N*v1", ["v1"] * 5, ["v1"], [5000], 3),
    ("N-1*v1,1*v2", ["v1", "v1", "v1", "v1", "v2"], ["v1"], [4999], 4),
    ("N-Q*v1,Q*v2", ["v1", "v1", "v2", "v2", "v2"], ["v1", "v2"], [4997, 3000], 5),
    ("N*v2", ["v2"] * 5, ["v2", "v1"], [5000, 4995], 6),
    ("N-1*v2,1*down", ["v2"] * 4, ["v2", "v1"], [4000, 3996], 7),
    ("Q-1*v2,3*down", ["v2", "v2"], [], [], 8),
    ("1*v1,N-1*v2", ["v1", "v2", "v2", "v2", "v2"], ["v1", "v2"], [4996, 4000], 9),
    ("1*v1,N-2*v2,1*down", ["v1", "v2", "v2", "v2"], ["v1", "v2"], [3997, 3000], 10),
    ("1*v1,Q-1*v2,2*down", ["v1", "v2", "v2"], ["v1"], [2998], 11),
    ("1*v1,N-2*v2,1*v3", ["v1", "v2", "v2", "v2", "v3"], ["v2", "v1"], [3999, 3997], 12),
    ("2*v1,N-3*v2,1*v3", ["v1", "v1", "v2", "v2", "v3"], ["v1", "v2"], [3998, 2999], 13),
    ("1*v1,1*v2,Q*v3", ["v1", "v2", "v3", "v3", "v3"], ["v2", "v3"], [3997, 3000], 14),
    ("2*v1,Q*v3", ["v1", "v1", "v3", "v3", "v3"], ["v3", "v2"], [3000, 2997], 15),
    ("deterministic ordering instance 1", ["xy", "xy", "yx", "yx"], ["x", "y"], [3998, 3998], 1),
    ("deterministic ordering instance 9", ["xy", "xy", "yx", "yx"], ["x", "y"], [3998, 3998], 9),
]

MIN_REQUIRED = 3
"""Quorum used by Charon's table. Not the real threshold formula, just its fixture."""

TOPIC = "versions"
IGNORED_TOPIC = "ignored"


def priority_msgs(sets: List[str], slot: int) -> List[PriorityMsg]:
    """Build one message per peer, mirroring Charon's fixture."""
    return [
        PriorityMsg(
            duty=Duty(slot=slot, type=DutyType.UNKNOWN),
            peer_id=str(index),
            topics=[
                PriorityTopicProposal(topic=TOPIC, priorities=PRIORITY_SETS[name]),
                PriorityTopicProposal(topic=IGNORED_TOPIC, priorities=[]),
            ],
        )
        for index, name in enumerate(sets)
    ]


def priority_scoring() -> Dict[str, Any]:
    """Priority scoring table, checked against Charon's expected values."""
    cases: List[Dict[str, Any]] = []

    for name, sets, expected_order, expected_scores, slot in PRIORITY_TABLE:
        msgs = priority_msgs(sets, slot)
        result = calculate_result(msgs, MIN_REQUIRED)

        topic_result = next(topic for topic in result.topics if topic.topic == TOPIC)
        order = [scored.priority for scored in topic_result.priorities]
        scores = [scored.score for scored in topic_result.priorities]

        assert order == expected_order, f"{name}: got {order}, charon expects {expected_order}"
        if expected_order:
            assert scores == expected_scores, (
                f"{name}: got {scores}, charon expects {expected_scores}"
            )

        cases.append(
            {
                "name": name,
                "input": {
                    "slot": slot,
                    "min_required": MIN_REQUIRED,
                    "topic": TOPIC,
                    "peers": [
                        {"peer_id": msg.peer_id, "priorities": PRIORITY_SETS[set_name]}
                        for msg, set_name in zip(msgs, sets, strict=True)
                    ],
                },
                "result": [
                    {"priority": priority, "score": score}
                    for priority, score in zip(order, scores, strict=True)
                ],
            }
        )

    return {
        "suite": "priority_scoring",
        "description": (
            "Cluster-wide priority results for a topic, given each peer's proposed "
            "order. Every peer also proposes an empty 'ignored' topic, which must "
            "appear in the result with no priorities."
        ),
        "provenance": {
            "source": "charon",
            "charon_ref": CHARON_REF,
            "generated_by": "scripts/generate_test_vectors.py",
            "note": (
                "Expected orders and scores are transcribed from charon's "
                "core/priority/calculate_internal_test.go TestCalculateResults table; "
                "this script fails if the spec does not reproduce them."
            ),
        },
        "cases": cases,
    }


def main() -> None:
    """Regenerate every spec-computed suite."""
    write("timer_deadlines", timer_deadlines())
    write("priority_scoring", priority_scoring())


if __name__ == "__main__":
    main()
