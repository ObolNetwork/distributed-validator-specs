"""Cluster edit protocols: reshare, add, remove, and replace operators.

An existing cluster is edited by re-running a DKG over the *same* validator
public keys, producing fresh private shares and a new cluster lock. All four
edit protocols share one framework — the same participant bootstrap, the same
four synchronised steps, the same lock update — and differ only in who takes
part, which share indices they hold, and what the new threshold is.

Because the steps are synchronised through the DKG sync protocol and the lock
hash signatures are exchanged over libp2p, the step count and the participant
ordering are wire-visible: a node that disagrees about either stalls the
ceremony. Mirrors Charon's `dkg/protocol.go`, `dkg/protocolsteps.go`, and
`dkg/protocol_*.go`.

Scope
-----
- The four-step sequence and its variant for departing operators.
- Participant set construction and share index preservation per protocol.
- The threshold rules, including the remove-operators override bounds.
- What the lock update rewrites.

Out of scope
------------
- Pedersen reshare internals; see `pedersen.py`.
- On-disk artifact layout and keystore encryption.
"""

from __future__ import annotations

from enum import Enum
from math import ceil
from typing import List, Optional, Sequence

LOCK_DEFINITION_FIELDS_RESET = ("creator", "operator_config_signature", "operator_enr_signature")
"""Definition fields the lock update clears, keeping only operator ENRs.

These fields all carry execution-layer or operator signatures over the *previous*
definition. An edit ceremony has no way to re-collect them — there is no
launchpad interaction and no operator wallet in the loop — so they are cleared
rather than carried forward, where they would be stale and fail verification.
"""

# ----------------------------
# Protocol steps
# ----------------------------


class EditProtocol(str, Enum):
    """A cluster edit protocol."""

    RESHARE = "reshare"
    """Refresh private shares; operators, validators and threshold unchanged."""

    ADD_OPERATORS = "add-operators"
    """Extend the operator set; threshold and validators unchanged."""

    REMOVE_OPERATORS = "remove-operators"
    """Shrink the operator set; threshold recomputed."""

    REPLACE_OPERATOR = "replace-operator"
    """Swap one operator for another at the same share index."""


class EditProtocolStep(str, Enum):
    """One step of an edit protocol.

    Steps run sequentially, and every node advances its DKG sync step counter
    between them, so all nodes are at the same step at the same time.
    """

    RESHARE = "reshare"
    """Run a Pedersen reshare DKG, producing new private shares."""

    UPDATE_LOCK = "update-lock"
    """Rewrite the lock, then sign, exchange and aggregate its hash."""

    UPDATE_NODE_SIGNATURES = "update-node-signatures"
    """Exchange secp256k1 node signatures over the new lock hash."""

    WRITE_ARTIFACTS = "write-artifacts"
    """Write the ENR key, key shares and new lock to the output directory."""

    NOOP = "noop"
    """Do nothing, but still synchronise with the other nodes."""

    IGNORE_NODE_SIGNATURES = "ignore-node-signatures"
    """Broadcast the sentinel node signature instead of a real one."""


EDIT_PROTOCOL_STEP_COUNT = 4
"""Every edit protocol runs exactly four synchronised steps."""


def edit_protocol_steps(departing: bool = False) -> List[EditProtocolStep]:
    """Return the four steps a node runs for any edit protocol.

    All four protocols share one step sequence; only a departing operator
    differs. A departing node still runs the reshare — the remaining nodes need
    its contribution to rebuild their shares — and still occupies all four sync
    steps, but it writes no artifacts and contributes no signature. It cannot
    simply stay silent: the node signature exchange is a reliable broadcast that
    requires every participant to take part, so it broadcasts the sentinel
    instead.

    Args:
        departing: True for an operator being removed that is participating in
            the ceremony.

    Returns:
        The steps in execution order.
    """
    if departing:
        return [
            EditProtocolStep.RESHARE,
            EditProtocolStep.NOOP,
            EditProtocolStep.IGNORE_NODE_SIGNATURES,
            EditProtocolStep.NOOP,
        ]

    return [
        EditProtocolStep.RESHARE,
        EditProtocolStep.UPDATE_LOCK,
        EditProtocolStep.UPDATE_NODE_SIGNATURES,
        EditProtocolStep.WRITE_ARTIFACTS,
    ]


# ----------------------------
# Threshold rules
# ----------------------------


def recommended_threshold(nodes: int) -> int:
    """Compute the default threshold for a node count.

    Args:
        nodes: Number of nodes `n`.

    Returns:
        `ceil(2n/3)`.

    Example:
        >>> [recommended_threshold(n) for n in (3, 4, 5, 6, 7)]
        [2, 3, 4, 4, 5]
    """
    return ceil(2 * nodes / 3)


def resolve_new_threshold(new_node_count: int, override: Optional[int] = None) -> int:
    """Resolve the threshold for a shrunk cluster.

    An override may only *raise* the threshold: allowing a lower one would let
    the old, larger-cluster shares reconstruct the key below the new threshold.
    It must also stay below the new node count, or no quorum could ever form.

    Args:
        new_node_count: Number of nodes `n'` remaining after removal.
        override: Explicitly requested threshold, or None for the default.

    Returns:
        The threshold to use.

    Raises:
        ValueError: If the override is below the recommended threshold or is not
            less than `new_node_count`.
    """
    recommended = recommended_threshold(new_node_count)

    if override is None:
        return recommended

    if override < recommended or override >= new_node_count:
        raise ValueError(
            f"new-threshold is invalid: recommended threshold {recommended}, "
            f"must be in [{recommended}, {new_node_count})"
        )

    return override


# ----------------------------
# Participant sets
# ----------------------------


def reshare_participants(operator_enrs: Sequence[str]) -> List[str]:
    """Build the participant list for a reshare.

    Args:
        operator_enrs: Operator ENRs in cluster lock order.

    Returns:
        All operators, in lock order.
    """
    return list(operator_enrs)


def add_operators_participants(
    operator_enrs: Sequence[str],
    new_enrs: Sequence[str],
) -> List[str]:
    """Build the participant list for adding operators.

    New operators are appended, never interleaved, so every existing operator
    keeps its share index and the new ones take the next indices in order.

    Args:
        operator_enrs: Existing operator ENRs in cluster lock order.
        new_enrs: ENRs of the operators being added, in the requested order.

    Returns:
        Existing operators followed by the new ones.
    """
    return [*operator_enrs, *new_enrs]


def remove_operators_participants(
    operator_enrs: Sequence[str],
    removing_enrs: Sequence[str],
    participating_enrs: Sequence[str] = (),
) -> List[str]:
    """Build the participant list for removing operators.

    By default the remaining operators run the ceremony. An explicit
    participating set overrides that and is used verbatim, in the order given —
    it MAY include operators that are being removed, which is how a cluster
    removes more operators than its fault tolerance allows: departing nodes stay
    long enough to contribute their shares to the reshare.

    Args:
        operator_enrs: Existing operator ENRs in cluster lock order.
        removing_enrs: ENRs of the operators being removed.
        participating_enrs: Explicit participant set, or empty for the default.

    Returns:
        The participants, in the order they are indexed for the ceremony.

    Raises:
        ValueError: If a requested participant or removal target is not a
            current operator.
    """
    for enr in removing_enrs:
        if enr not in operator_enrs:
            raise ValueError("removing ENR not found among lock operators")

    if participating_enrs:
        for enr in participating_enrs:
            if enr not in operator_enrs:
                raise ValueError("participating ENR not found among lock operators")

        return list(participating_enrs)

    return [enr for enr in operator_enrs if enr not in removing_enrs]


def replace_operator_participants(
    operator_enrs: Sequence[str],
    old_enr: str,
    new_enr: str,
) -> List[str]:
    """Build the participant list for replacing one operator.

    The replacement takes the departing operator's position, so it inherits that
    share index and every other operator's index is untouched. This is what
    makes a replacement a one-for-one swap rather than a removal followed by an
    addition.

    Args:
        operator_enrs: Existing operator ENRs in cluster lock order.
        old_enr: ENR of the operator being replaced.
        new_enr: ENR of the replacement operator.

    Returns:
        The operator ENRs with the replacement substituted in place.

    Raises:
        ValueError: If the old ENR is not a current operator.
    """
    if old_enr not in operator_enrs:
        raise ValueError("old operator not found in lock")

    index = list(operator_enrs).index(old_enr)

    participants = list(operator_enrs)
    participants[index] = new_enr

    return participants


# ----------------------------
# Share indices
# ----------------------------


def ceremony_share_index(operator_enrs: Sequence[str], enr: str) -> int:
    """Resolve the share index an operator uses *during* the ceremony.

    Share indices are read from the current cluster lock, not from the
    participant list, so removing an operator leaves a gap: the survivors of a
    four-operator cluster that drops its first operator sign as 2, 3 and 4. The
    gap is only closed when the new lock is written.

    For every protocol other than remove-operators the two coincide, because the
    participant list is the lock order with additions appended or a replacement
    substituted in place.

    Args:
        operator_enrs: Operator ENRs in current cluster lock order.
        enr: ENR of the operator to locate.

    Returns:
        The 1-based share index.

    Raises:
        ValueError: If the ENR is not a current operator.
    """
    if enr not in operator_enrs:
        raise ValueError("ENR not among the cluster lock operators")

    return list(operator_enrs).index(enr) + 1


def new_lock_share_index(remaining_enrs: Sequence[str], enr: str) -> int:
    """Resolve the share index an operator holds in the *new* cluster lock.

    Indices are compacted to `1..n'` in ascending current-lock order. This falls
    out of the lock format rather than being chosen: public shares are stored as
    an ordered list, so an operator's list position — not any index it carried
    before — determines the index it is read back at.

    The reshare assigns the surviving nodes' new shares in that same ascending
    order, so the two agree. Keying the new lock's public shares by the old,
    gapped indices instead produces a lock whose shares do not reconstruct the
    validator public key, and which every node rejects at load time.

    Args:
        remaining_enrs: ENRs remaining in the new lock, in current lock order.
        enr: ENR of the operator to locate.

    Returns:
        The 1-based share index in the new lock.

    Raises:
        ValueError: If the ENR does not remain in the new lock.
    """
    if enr not in remaining_enrs:
        raise ValueError("ENR does not remain in the new cluster lock")

    return list(remaining_enrs).index(enr) + 1
