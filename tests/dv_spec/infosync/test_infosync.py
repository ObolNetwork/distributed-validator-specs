import pytest

from dv_spec.subspecs.infosync.infosync import (
    MAX_RESULTS,
    QBFT_V2_PROTOCOL_ID,
    TOPIC_PROPOSAL,
    TOPIC_PROTOCOL,
    TOPIC_VERSION,
    InfoSyncResult,
    ProposalType,
    add_result,
    infosync_duty,
    is_infosync_slot,
    latest_result,
    local_proposal_types,
    local_protocol_priorities,
    most_preferred_consensus_protocol,
    prioritize_protocols_by_name,
    selected_proposal_types,
    selected_protocols,
)
from dv_spec.types.duty import DutyType

SLOTS_PER_EPOCH = 32
PARSIGEX = "/charon/parsigex/2.0.0"
PEERINFO = "/charon/peerinfo/2.0.0"
QBFT = QBFT_V2_PROTOCOL_ID


def test_topic_names_are_on_the_wire() -> None:
    assert (TOPIC_VERSION, TOPIC_PROTOCOL, TOPIC_PROPOSAL) == ("version", "protocol", "proposal")


def test_proposal_type_values_are_on_the_wire() -> None:
    assert [t.value for t in ProposalType] == ["full", "builder", "synthetic"]


@pytest.mark.parametrize(
    ("slot", "expected"),
    [(0, False), (30, False), (31, True), (32, False), (63, True), (64, False)],
)
def test_is_infosync_slot(slot: int, expected: bool) -> None:
    assert is_infosync_slot(slot, SLOTS_PER_EPOCH) is expected


def test_infosync_duty() -> None:
    duty = infosync_duty(31)
    assert duty.slot == 31
    assert duty.type == DutyType.INFO_SYNC


@pytest.mark.parametrize(
    ("builder", "synthetic", "expected"),
    [
        (False, False, ["full"]),
        (True, False, ["builder", "full"]),
        (False, True, ["synthetic", "full"]),
        (True, True, ["builder", "synthetic", "full"]),
    ],
)
def test_local_proposal_types_always_end_with_full(
    builder: bool, synthetic: bool, expected: list[str]
) -> None:
    assert [t.value for t in local_proposal_types(builder, synthetic)] == expected


def test_prioritize_protocols_by_name_preserves_relative_order() -> None:
    protocols = [PARSIGEX, QBFT, PEERINFO]
    assert prioritize_protocols_by_name("qbft", protocols) == [QBFT, PARSIGEX, PEERINFO]


def test_prioritize_protocols_by_name_ignores_unknown_name() -> None:
    protocols = [PARSIGEX, QBFT]
    assert prioritize_protocols_by_name("other", protocols) == protocols


def test_local_protocol_priorities_applies_config_after_lock() -> None:
    fake_qbft3 = "/charon/consensus/qbft/3.0.0"
    other = "/charon/consensus/other/1.0.0"
    protocols = [QBFT, fake_qbft3, other, PARSIGEX]

    # Configuration is applied last, so it outranks the lock preference.
    assert local_protocol_priorities(
        protocols, lock_preferred_protocol="qbft", configured_protocol="other"
    ) == [other, QBFT, fake_qbft3, PARSIGEX]

    # All versions of the named protocol are bumped together, in original order.
    assert local_protocol_priorities(protocols, lock_preferred_protocol="qbft") == [
        QBFT,
        fake_qbft3,
        other,
        PARSIGEX,
    ]


def test_most_preferred_consensus_protocol_skips_non_consensus_ids() -> None:
    assert most_preferred_consensus_protocol([PARSIGEX, PEERINFO, QBFT]) == QBFT


def test_most_preferred_consensus_protocol_falls_back_to_qbft() -> None:
    assert most_preferred_consensus_protocol([]) == QBFT
    assert most_preferred_consensus_protocol([PARSIGEX]) == QBFT


def result_at(slot: int, protocols: list[str] | None = None) -> InfoSyncResult:
    return InfoSyncResult(
        slot=slot,
        versions=["v1.11"],
        protocols=protocols if protocols is not None else [QBFT],
        proposals=["full"],
    )


def test_add_result_requires_agreed_versions() -> None:
    empty = InfoSyncResult(slot=31, versions=[], protocols=[QBFT], proposals=["full"])
    assert add_result([], empty) == []


def test_add_result_appends_and_caps() -> None:
    results = [result_at(slot) for slot in range(MAX_RESULTS - 1)]
    assert len(results) == MAX_RESULTS - 1

    updated = add_result(results, result_at(MAX_RESULTS))
    assert len(updated) == MAX_RESULTS - 1
    assert updated[0].slot == 1
    assert updated[-1].slot == MAX_RESULTS


def test_add_result_drops_identical_previous_result() -> None:
    results = [result_at(31)]
    assert add_result(results, result_at(31)) == results


def test_latest_result_selects_by_slot_not_recency() -> None:
    results = [result_at(31), result_at(63), result_at(95)]

    assert latest_result(results, 30) is None

    for slot, expected in ((31, 31), (62, 31), (63, 63), (200, 95)):
        found = latest_result(results, slot)
        assert found is not None
        assert found.slot == expected


def test_selected_protocols_falls_back_to_local() -> None:
    local = [QBFT, PARSIGEX]
    assert selected_protocols([], 31, local) == local

    agreed = [result_at(31, protocols=[QBFT])]
    assert selected_protocols(agreed, 31, local) == [QBFT]
    assert selected_protocols(agreed, 30, local) == local


def test_selected_proposal_types_defaults_to_full() -> None:
    assert selected_proposal_types([], 31) == ["full"]

    agreed = [
        InfoSyncResult(slot=31, versions=["v1.11"], protocols=[QBFT], proposals=["builder", "full"])
    ]
    assert selected_proposal_types(agreed, 31) == ["builder", "full"]
    assert selected_proposal_types(agreed, 30) == ["full"]
