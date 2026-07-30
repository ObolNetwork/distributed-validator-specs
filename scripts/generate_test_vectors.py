"""Regenerate the test vector suites this spec computes itself.

Run after changing anything the vectors cover:

    uv run python scripts/generate_test_vectors.py

`test_vectors/qbft_hashing.json` is deliberately *not* regenerated here. Its
values come from Charon rather than from this spec, via
`test_vectors/charon/hashproto_generator.go`; see `test_vectors/README.md`.

The priority suite's expected results are transcribed from Charon's own
`TestCalculateResults` table, so this script asserts the spec reproduces them
rather than recording whatever the spec happens to produce. The rejection suites
work the same way: the expected verdicts come from Charon's rules, and this
script fails if the spec accepts something Charon rejects or vice versa.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

from dv_spec.subspecs.consensus.cryptography import hash_value
from dv_spec.subspecs.consensus.qbft.definition import Definition
from dv_spec.subspecs.consensus.qbft.message import (
    MAX_CONSENSUS_MSG_SIZE,
    MsgType,
    QBFTConsensusMsg,
    QBFTMsg,
    verify_msg_limits,
)
from dv_spec.subspecs.consensus.qbft.protocol import MAX_DECIDED_RESENDS, QBFTConsensus
from dv_spec.subspecs.consensus.qbft.transport import PeerInfo, Transport
from dv_spec.subspecs.consensus.timer.timer import (
    NANOSECONDS_PER_SECOND,
    eager_double_linear_deadline_nanos,
    eager_double_linear_timeout,
    get_duty_start_delay_nanos,
)
from dv_spec.subspecs.parsigex.helpers import validate_exchange_peers, verify_peer_share_idx
from dv_spec.subspecs.parsigex.message import ParSignedData
from dv_spec.subspecs.priority.message import PriorityMsg, PriorityTopicProposal
from dv_spec.subspecs.priority.scoring import calculate_result
from dv_spec.types.duty import Duty, DutyType

REPO_ROOT = Path(__file__).resolve().parent.parent
VECTOR_ROOT = REPO_ROOT / "test_vectors"

# Each suite records the Charon commit it was validated against, which is not
# necessarily the repository's current anchor: re-running this script recomputes
# spec values but does not re-verify them against Charon, so advancing an existing
# suite's ref would assert a check nobody performed (see plans/spec-completion.md,
# Phase 1.1).
CHARON_REF = "2eb6798e3091b09f3eb659076e044dfe404e46d7"
REJECTION_CHARON_REF = "6054bcb2dc9be9a2d4244564ffdd0f2d1b7a09fd"

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
                    # Every peer also proposes this topic with no priorities, and
                    # it must appear in the result with an empty list. Named in
                    # the input so a consumer does not have to read the prose.
                    "ignored_topic": IGNORED_TOPIC,
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


TOO_MANY_JUSTIFICATIONS = "too_many_justifications"
TOO_MANY_VALUES = "too_many_values"

# (name, nodes, justifications, values, expected reason or None to accept).
# Charon: maxJust = 2*nodes, maxValues = 2*(justifications+1), justifications
# checked first (core/consensus/qbft/qbft.go verifyMsgLimits).
MSG_LIMIT_TABLE: List[Tuple[str, int, int, int, str | None]] = [
    ("no_justifications_two_values", 4, 0, 2, None),
    ("no_justifications_three_values", 4, 0, 3, TOO_MANY_VALUES),
    ("justifications_at_limit", 4, 8, 0, None),
    ("justifications_one_over_limit", 4, 9, 0, TOO_MANY_JUSTIFICATIONS),
    ("values_at_limit_for_full_justification_set", 4, 8, 18, None),
    ("values_one_over_limit_for_full_justification_set", 4, 8, 19, TOO_MANY_VALUES),
    # Both limits exceeded: the justification count is reported, because it is
    # checked first. An implementation that reported the value count instead
    # would disagree with Charon on the rejection reason.
    ("both_limits_exceeded_reports_justifications", 4, 9, 100, TOO_MANY_JUSTIFICATIONS),
    ("three_node_cluster_at_limit", 3, 6, 0, None),
    ("three_node_cluster_over_limit", 3, 7, 0, TOO_MANY_JUSTIFICATIONS),
    ("seven_node_cluster_at_limit", 7, 14, 0, None),
    ("seven_node_cluster_over_limit", 7, 15, 0, TOO_MANY_JUSTIFICATIONS),
]

P2P_DEFAULT_READ_LIMIT = 128 * 1024 * 1024
"""Charon's default libp2p read limit (`p2p/sender.go` `maxMsgSize`).

Consensus deliberately overrides it with `p2p.WithReadLimit(maxConsensusMsgSize)`.
A receiver that left the default in place would accept messages four times the
size the protocol permits, so the vectors pin the override rather than the default.
"""


def limit_msg(nodes: int, justifications: int, values: int) -> QBFTConsensusMsg:
    """Build a consensus message with the given justification and value counts."""
    duty = Duty(slot=1, type=DutyType.ATTESTER)
    template = QBFTMsg(type=MsgType.PREPARE, duty=duty, peer_idx=0, round=1)

    return QBFTConsensusMsg(
        msg=template,
        justification=[template for _ in range(justifications)],
        values=[bytes([index % 256]) for index in range(values)],
    )


def qbft_msg_limits() -> Dict[str, Any]:
    """Justification, value and wire-size limits on an incoming consensus message."""
    counts = []
    for name, nodes, justifications, values, reason in MSG_LIMIT_TABLE:
        try:
            verify_msg_limits(limit_msg(nodes, justifications, values), nodes)
            got: str | None = None
        except ValueError as error:
            got = TOO_MANY_JUSTIFICATIONS if "justifications" in str(error) else TOO_MANY_VALUES

        assert got == reason, f"{name}: spec says {got}, charon's rules say {reason}"

        counts.append(
            {
                "name": name,
                "input": {
                    "nodes": nodes,
                    "justification_count": justifications,
                    "value_count": values,
                },
                "accepted": reason is None,
                "reason": reason,
                "max_justifications": 2 * nodes,
                "max_values": 2 * (justifications + 1),
            }
        )

    wire_size = [
        ("small_message", 1024, True),
        ("at_limit", MAX_CONSENSUS_MSG_SIZE, True),
        ("one_byte_over_limit", MAX_CONSENSUS_MSG_SIZE + 1, False),
        ("p2p_default_read_limit", P2P_DEFAULT_READ_LIMIT, False),
    ]
    sizes = []
    for name, size, accepted in wire_size:
        assert (size <= MAX_CONSENSUS_MSG_SIZE) == accepted, f"{name}: spec disagrees"
        sizes.append({"name": name, "input": {"wire_size_bytes": size}, "accepted": accepted})

    return {
        "suite": "qbft_msg_limits",
        "description": (
            "Limits a receiver MUST apply to an incoming QBFT consensus message before "
            "any per-element work: justifications <= 2*nodes, values <= "
            "2*(justifications+1), and a wire size of at most "
            f"{MAX_CONSENSUS_MSG_SIZE} bytes ({MAX_CONSENSUS_MSG_SIZE // (1024 * 1024)} MiB). "
            "Every case names the rejection reason, because agreeing on which limit "
            "fired is what makes the two checks distinguishable."
        ),
        "provenance": {
            "source": "spec",
            "charon_ref": REJECTION_CHARON_REF,
            "generated_by": "scripts/generate_test_vectors.py",
            "note": (
                "Derived from charon's core/consensus/qbft/qbft.go: verifyMsgLimits for "
                "the counts and maxConsensusMsgSize for the wire size. Charon has no "
                "table test for these, so the cases are the spec's own boundary pairs "
                "around charon's formulas; this script fails if the spec's verdict "
                "differs from the table."
            ),
        },
        "counts": counts,
        "wire_size": sizes,
    }


# (name, events, expected allow decisions). Transcribed from charon's
# core/qbft/qbft_internal_test.go TestDecidedRebroadcastLimits.
RESEND_CASES: List[Tuple[str, List[Tuple[int, int]], List[bool]]] = [
    (
        "dedup_duplicates_and_stale_rounds",
        [(2, 2), (2, 2), (2, 2), (3, 2), (3, 2), (2, 1), (2, 3)],
        [True, False, False, True, False, False, True],
    ),
    (
        "resend_cap_per_source",
        [(2, round_num) for round_num in range(2, 2 + MAX_DECIDED_RESENDS + 5)],
        [True] * MAX_DECIDED_RESENDS + [False] * 5,
    ),
]


def decided_consensus(nodes: int) -> QBFTConsensus:
    """A consensus instance that has already decided in round 1."""
    duty = Duty(slot=100, type=DutyType.ATTESTER)
    proposal_value = b"test_block"
    transport = Transport(
        private_key=b"test_key" * 4,
        peers=[
            PeerInfo(peer_idx=index, public_key=b"test_key", peer_id=f"peer_{index}")
            for index in range(nodes)
        ],
    )
    consensus = QBFTConsensus(
        d=Definition(nodes=nodes),
        t=transport,
        duty=duty,
        peer=0,
        proposal_value=proposal_value,
    )
    consensus.q_commit = [
        QBFTMsg(
            type=MsgType.COMMIT,
            duty=duty,
            peer_idx=index,
            round=1,
            signature=b"0" * 65,
            value_hash=hash_value(proposal_value),
        )
        for index in range(nodes - 1)
    ]
    return consensus


def qbft_decided_resends() -> Dict[str, Any]:
    """Rate limit on DECIDED rebroadcasts triggered by post-decision ROUND-CHANGEs."""
    nodes = 4
    cases = []
    for name, events, expected in RESEND_CASES:
        consensus = decided_consensus(nodes)
        allowed = []
        for source, round_num in events:
            responses = consensus.handle_message(
                QBFTConsensusMsg(
                    msg=QBFTMsg(
                        type=MsgType.ROUND_CHANGE,
                        duty=consensus.duty,
                        peer_idx=source,
                        round=round_num,
                        signature=b"0" * 65,
                    )
                )
            )
            allowed.append(bool(responses))

        assert allowed == expected, f"{name}: spec allowed {allowed}, charon expects {expected}"

        cases.append(
            {
                "name": name,
                "input": {
                    "nodes": nodes,
                    "decided_round": 1,
                    "events": [
                        {"source": source, "round": round_num} for source, round_num in events
                    ],
                },
                "rebroadcast": expected,
                "total_rebroadcasts": sum(expected),
            }
        )

    return {
        "suite": "qbft_decided_resends",
        "description": (
            "Once an instance has decided, a post-decision ROUND-CHANGE triggers at most "
            "one DECIDED rebroadcast per source per strictly-increasing round, capped at "
            f"{MAX_DECIDED_RESENDS} per source. `rebroadcast[i]` is whether event i "
            "triggers one. Counted as rebroadcast events, not messages, since a "
            "rebroadcast reaches every peer."
        ),
        "provenance": {
            "source": "charon",
            "charon_ref": REJECTION_CHARON_REF,
            "generated_by": "scripts/generate_test_vectors.py",
            "note": (
                "Event sequences and expected counts are transcribed from charon's "
                "core/qbft/qbft_internal_test.go TestDecidedRebroadcastLimits "
                "subtests; this script fails if the spec does not reproduce them."
            ),
        },
        "cases": cases,
    }


UNKNOWN_PEER = "unknown_peer"
SHARE_IDX_MISMATCH = "share_idx_mismatch"

# (name, sender, share_idx, expected reason or None). Transcribed from charon's
# dkg/exchanger_internal_test.go TestVerifyPeerShareIdx. "other" is the second
# peer but keeps share index 4, as it would after operators with lower indices
# were removed.
SENDER_BINDING_PEER_MAP = {"self": 1, "other": 4}
SENDER_BINDING_TABLE: List[Tuple[str, str, int, str | None]] = [
    ("own_share_index_accepted", "self", 1, None),
    ("assigned_non_contiguous_share_index_accepted", "other", 4, None),
    ("mismatched_share_index_rejected", "other", 2, SHARE_IDX_MISMATCH),
    ("another_peers_share_index_rejected", "self", 4, SHARE_IDX_MISMATCH),
    ("non_positive_share_index_rejected", "self", 0, SHARE_IDX_MISMATCH),
    ("unknown_sender_rejected", "unknown", 1, UNKNOWN_PEER),
]


def parsigex_sender_binding() -> Dict[str, Any]:
    """Binding of a claimed share index to the authenticated libp2p sender."""
    cases = []
    for name, sender, share_idx, reason in SENDER_BINDING_TABLE:
        # model_construct bypasses validation: ParSignedData constrains share_idx
        # to >= 1, but charon's type does not, and the non-positive case has to
        # reach the verifier to prove it is rejected there too.
        data = ParSignedData.model_construct(data=b"", signature=b"\x00" * 65, share_idx=share_idx)
        try:
            verify_peer_share_idx(SENDER_BINDING_PEER_MAP, sender, data)
            got: str | None = None
        except ValueError as error:
            got = UNKNOWN_PEER if "unknown peer" in str(error) else SHARE_IDX_MISMATCH

        assert got == reason, f"{name}: spec says {got}, charon expects {reason}"

        cases.append(
            {
                "name": name,
                "input": {
                    "share_idx_by_peer": SENDER_BINDING_PEER_MAP,
                    "sender": sender,
                    "share_idx": share_idx,
                },
                "accepted": reason is None,
                "reason": reason,
            }
        )

    peer_map_cases = []
    for name, peers, share_idx_by_peer, accepted in [
        ("complete_peer_map_accepted", ["self", "other"], SENDER_BINDING_PEER_MAP, True),
        ("peer_missing_from_map_rejected", ["self", "missing"], {"self": 1}, False),
        (
            "peer_with_non_positive_index_rejected",
            ["self", "other"],
            {"self": 1, "other": 0},
            False,
        ),
    ]:
        try:
            validate_exchange_peers(peers, share_idx_by_peer, 0)
            rejected = False
        except ValueError:
            rejected = True

        assert rejected != accepted, f"{name}: spec disagrees"

        peer_map_cases.append(
            {
                "name": name,
                "input": {"peers": peers, "share_idx_by_peer": share_idx_by_peer, "peer_idx": 0},
                "accepted": accepted,
                "reason": None if accepted else "missing_share_idx",
            }
        )

    return {
        "suite": "parsigex_sender_binding",
        "description": (
            "A peer may only contribute a partial signature under the share index the "
            "cluster assigned it, resolved through a peer map rather than the peer's "
            "position: removing an operator leaves survivors with gapped indices, which "
            "is what breaks a position-derived implementation. Construction rejects a "
            "participant with no assigned index, since otherwise its signatures are "
            "dropped as unknown and the exchange silently times out."
        ),
        "provenance": {
            "source": "charon",
            "charon_ref": REJECTION_CHARON_REF,
            "generated_by": "scripts/generate_test_vectors.py",
            "note": (
                "The sender cases are transcribed from charon's "
                "dkg/exchanger_internal_test.go TestVerifyPeerShareIdx table, and the "
                "peer map cases from TestNewExchangerRejectsIncompletePeerMap; this "
                "script fails if the spec does not reproduce them."
            ),
        },
        "cases": cases,
        "peer_map": peer_map_cases,
    }


def main() -> None:
    """Regenerate every spec-computed suite."""
    write("timer_deadlines", timer_deadlines())
    write("priority_scoring", priority_scoring())
    write("qbft_msg_limits", qbft_msg_limits())
    write("qbft_decided_resends", qbft_decided_resends())
    write("parsigex_sender_binding", parsigex_sender_binding())


if __name__ == "__main__":
    main()
