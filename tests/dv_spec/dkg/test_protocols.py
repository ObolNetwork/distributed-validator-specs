import pytest

from dv_spec.subspecs.dkg.protocols import (
    EDIT_PROTOCOL_STEP_COUNT,
    EditProtocolStep,
    add_operators_participants,
    ceremony_share_index,
    edit_protocol_steps,
    new_lock_share_index,
    recommended_threshold,
    remove_operators_participants,
    replace_operator_participants,
    reshare_participants,
    resolve_new_threshold,
)

OPERATORS = ["enr:a", "enr:b", "enr:c", "enr:d"]


def test_every_protocol_runs_four_steps() -> None:
    assert len(edit_protocol_steps()) == EDIT_PROTOCOL_STEP_COUNT
    assert len(edit_protocol_steps(departing=True)) == EDIT_PROTOCOL_STEP_COUNT


def test_remaining_node_steps() -> None:
    assert edit_protocol_steps() == [
        EditProtocolStep.RESHARE,
        EditProtocolStep.UPDATE_LOCK,
        EditProtocolStep.UPDATE_NODE_SIGNATURES,
        EditProtocolStep.WRITE_ARTIFACTS,
    ]


def test_departing_node_still_reshares_and_broadcasts_sentinel() -> None:
    steps = edit_protocol_steps(departing=True)
    assert steps[0] == EditProtocolStep.RESHARE
    assert steps[2] == EditProtocolStep.IGNORE_NODE_SIGNATURES
    assert EditProtocolStep.UPDATE_LOCK not in steps
    assert EditProtocolStep.WRITE_ARTIFACTS not in steps


@pytest.mark.parametrize(
    ("nodes", "expected"),
    [(1, 1), (3, 2), (4, 3), (5, 4), (6, 4), (7, 5), (10, 7)],
)
def test_recommended_threshold(nodes: int, expected: int) -> None:
    assert recommended_threshold(nodes) == expected


def test_resolve_new_threshold_defaults_to_recommended() -> None:
    assert resolve_new_threshold(3) == 2


def test_resolve_new_threshold_allows_raising() -> None:
    # For n'=4 the recommended threshold is 3, so 3 is allowed and 4 is not.
    assert resolve_new_threshold(4, override=3) == 3

    with pytest.raises(ValueError, match="new-threshold is invalid"):
        resolve_new_threshold(4, override=4)


def test_resolve_new_threshold_rejects_lowering() -> None:
    with pytest.raises(ValueError, match="new-threshold is invalid"):
        resolve_new_threshold(4, override=2)


def test_reshare_participants_are_all_operators() -> None:
    assert reshare_participants(OPERATORS) == OPERATORS


def test_add_operators_appends_to_preserve_share_indices() -> None:
    participants = add_operators_participants(OPERATORS, ["enr:e", "enr:f"])
    assert participants == [*OPERATORS, "enr:e", "enr:f"]

    for enr in OPERATORS:
        assert ceremony_share_index(participants, enr) == ceremony_share_index(OPERATORS, enr)

    assert ceremony_share_index(participants, "enr:e") == 5


def test_remove_operators_defaults_to_survivors() -> None:
    assert remove_operators_participants(OPERATORS, ["enr:b"]) == ["enr:a", "enr:c", "enr:d"]


def test_remove_operators_honours_explicit_participants_verbatim() -> None:
    # A departing operator may participate, which is how a cluster removes more
    # operators than its fault tolerance allows.
    participating = ["enr:d", "enr:a", "enr:b"]
    assert remove_operators_participants(OPERATORS, ["enr:b"], participating) == participating


def test_remove_operators_rejects_unknown_enrs() -> None:
    with pytest.raises(ValueError, match="removing ENR not found"):
        remove_operators_participants(OPERATORS, ["enr:z"])

    with pytest.raises(ValueError, match="participating ENR not found"):
        remove_operators_participants(OPERATORS, ["enr:b"], ["enr:z"])


def test_replace_operator_reuses_the_share_index() -> None:
    participants = replace_operator_participants(OPERATORS, "enr:b", "enr:new")
    assert participants == ["enr:a", "enr:new", "enr:c", "enr:d"]
    assert ceremony_share_index(participants, "enr:new") == ceremony_share_index(OPERATORS, "enr:b")


def test_replace_operator_rejects_unknown_old_enr() -> None:
    with pytest.raises(ValueError, match="old operator not found in lock"):
        replace_operator_participants(OPERATORS, "enr:z", "enr:new")


def test_removal_gaps_ceremony_indices_and_compacts_new_lock_indices() -> None:
    remaining = remove_operators_participants(OPERATORS, ["enr:a"])
    assert remaining == ["enr:b", "enr:c", "enr:d"]

    # During the ceremony the survivors keep their gapped current-lock indices.
    assert [ceremony_share_index(OPERATORS, enr) for enr in remaining] == [2, 3, 4]

    # The new lock compacts them, in the same ascending order.
    assert [new_lock_share_index(remaining, enr) for enr in remaining] == [1, 2, 3]


def test_ceremony_share_index_rejects_unknown_operator() -> None:
    with pytest.raises(ValueError, match="not among the cluster lock operators"):
        ceremony_share_index(OPERATORS, "enr:z")


def test_new_lock_share_index_rejects_departed_operator() -> None:
    remaining = remove_operators_participants(OPERATORS, ["enr:a"])
    with pytest.raises(ValueError, match="does not remain"):
        new_lock_share_index(remaining, "enr:a")
