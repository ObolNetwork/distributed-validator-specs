"""InfoSync: cluster-wide agreement on versions, protocols, and proposal types.

InfoSync is the only production use of the [priority protocol]
(`dv_spec.subspecs.priority`). Once per epoch each node proposes what it
supports; the cluster agrees on the intersection, ordered by support; and the
agreed result selects the consensus protocol and block proposal types every node
uses for the following epoch. That makes it the mechanism by which a cluster
performs a rolling upgrade without a coordinated restart.

Mirrors Charon's `core/infosync` and the wiring in `app.wirePrioritise`.

Scope
-----
- The three topics and what each carries.
- The trigger cadence and the duty the exchange runs under.
- How a node orders its local priorities before proposing them.
- How the agreed result selects the consensus protocol and proposal types.

Out of scope
------------
- The priority protocol exchange, scoring, and consensus; see
  `dv_spec.subspecs.priority`.
- Consensus protocol switching mechanics inside a node.
"""

from __future__ import annotations

from enum import Enum
from typing import List, Optional, Sequence

from pydantic import Field

from dv_spec.types.base import StrictBaseModel
from dv_spec.types.duty import Duty, DutyType
from dv_spec.types.uint64 import Uint64

# ----------------------------
# Topics
# ----------------------------

TOPIC_VERSION = "version"
"""Topic carrying supported Charon minor versions, most recent first.

Advisory only: the agreed result is recorded and logged for upgrade visibility,
and no behaviour is selected from it.
"""

TOPIC_PROTOCOL = "protocol"
"""Topic carrying supported libp2p protocol IDs, most preferred first.

Load-bearing: the agreed result selects the cluster-wide consensus protocol.
"""

TOPIC_PROPOSAL = "proposal"
"""Topic carrying supported block proposal types, most preferred first.

Load-bearing: the agreed result selects which proposal types may be used.
"""

# ----------------------------
# Protocol constants
# ----------------------------

CONSENSUS_PROTOCOL_ID_PREFIX = "/charon/consensus/"
"""Prefix that distinguishes consensus protocol IDs from other protocol IDs.

The `protocol` topic carries every protocol a node supports — parsigex,
peerinfo, priority and consensus alike — so consensus selection filters on this
prefix.
"""

QBFT_V2_PROTOCOL_ID = "/charon/consensus/qbft/2.0.0"
"""The only consensus protocol currently implemented, and the fallback."""

MAX_RESULTS = 100
"""Number of past agreed results a node retains."""

EXCHANGE_TIMEOUT_SECONDS = 6
"""Priority exchange timeout used for InfoSync, half a 12-second slot."""


class ProposalType(str, Enum):
    """A block proposal strategy a node is willing to use.

    These strings are on the wire and MUST NOT be changed.
    """

    FULL = "full"
    """Normal full beacon block proposals."""

    BUILDER = "builder"
    """Builder API blinded beacon block proposals."""

    SYNTHETIC = "synthetic"
    """Synthetic block proposals, which may be full or builder."""


# ----------------------------
# Trigger
# ----------------------------


def is_infosync_slot(slot: int, slots_per_epoch: int) -> bool:
    """Report whether an InfoSync exchange is triggered at this slot.

    The exchange runs in the last slot of every epoch so that the result is
    agreed before the epoch it governs begins.

    Args:
        slot: The slot number.
        slots_per_epoch: Network `SLOTS_PER_EPOCH`.

    Returns:
        True if this is the last slot of an epoch.
    """
    return slot % slots_per_epoch == slots_per_epoch - 1


def infosync_duty(slot: int) -> Duty:
    """Build the duty the InfoSync exchange runs under.

    Args:
        slot: The triggering slot, i.e. the last slot of the current epoch.

    Returns:
        The `DutyType.INFO_SYNC` duty at that slot.
    """
    return Duty(slot=slot, type=DutyType.INFO_SYNC)


# ----------------------------
# Local priority ordering
# ----------------------------


def local_proposal_types(builder: bool, synthetic: bool) -> List[ProposalType]:
    """Order this node's supported proposal types by preference.

    `FULL` is always supported and always last, so a cluster whose nodes enable
    different features still agrees on something.

    Args:
        builder: Whether the builder API is enabled on this node.
        synthetic: Whether synthetic block proposals are enabled on this node.

    Returns:
        Proposal types in order of precedence.
    """
    types: List[ProposalType] = []

    if builder:
        types.append(ProposalType.BUILDER)

    if synthetic:
        types.append(ProposalType.SYNTHETIC)

    types.append(ProposalType.FULL)

    return types


def prioritize_protocols_by_name(name: str, protocols: Sequence[str]) -> List[str]:
    """Move every version of one consensus protocol to the front of the list.

    Matching is by name, so all versions of the named protocol are bumped
    together and their relative order — and that of the untouched remainder — is
    preserved.

    Args:
        name: Consensus protocol name, e.g. `"qbft"`.
        protocols: The node's protocol IDs in current order.

    Returns:
        The reordered protocol IDs.

    Example:
        >>> prioritize_protocols_by_name(
        ...     "qbft", ["/charon/parsigex/2.0.0", "/charon/consensus/qbft/2.0.0"]
        ... )
        ['/charon/consensus/qbft/2.0.0', '/charon/parsigex/2.0.0']
    """
    prefix = CONSENSUS_PROTOCOL_ID_PREFIX + name + "/"

    bumped = [p for p in protocols if p.startswith(prefix)]
    others = [p for p in protocols if not p.startswith(prefix)]

    return bumped + others


def local_protocol_priorities(
    protocols: Sequence[str],
    lock_preferred_protocol: str = "",
    configured_protocol: str = "",
) -> List[str]:
    """Order this node's protocol IDs before proposing them.

    Two bumps are applied to the implementation-defined base order, and the
    order of application decides the outcome: the cluster lock preference is
    applied first, then the node's own configuration, so an operator's explicit
    choice outranks the lock.

    Args:
        protocols: All protocol IDs this node supports, in implementation order.
        lock_preferred_protocol: Consensus protocol name from the cluster lock,
            or empty if unset.
        configured_protocol: Consensus protocol name from this node's
            configuration, or empty if unset.

    Returns:
        The protocol IDs in the order this node proposes them.
    """
    ordered = list(protocols)

    if lock_preferred_protocol:
        ordered = prioritize_protocols_by_name(lock_preferred_protocol, ordered)

    if configured_protocol:
        ordered = prioritize_protocols_by_name(configured_protocol, ordered)

    return ordered


# ----------------------------
# Agreed results
# ----------------------------


class InfoSyncResult(StrictBaseModel):
    """One cluster-wide agreed InfoSync result.

    Holds the priorities of each topic in agreed order, stripped of their
    scores.
    """

    slot: Uint64 = Field(description="Slot of the InfoSync duty that produced this result")
    versions: List[str] = Field(default_factory=list, description="Agreed versions")
    protocols: List[str] = Field(default_factory=list, description="Agreed protocol IDs")
    proposals: List[str] = Field(default_factory=list, description="Agreed proposal types")


def add_result(results: Sequence[InfoSyncResult], result: InfoSyncResult) -> List[InfoSyncResult]:
    """Append an agreed result to a node's retained history.

    A result is only recorded if the `version` topic produced priorities, which
    distinguishes a real agreement from an empty one.

    A result identical to the previous one is dropped. Note that the comparison
    includes the slot, and each exchange runs at a different slot, so in practice
    consecutive results are never identical and nothing is ever dropped. This is
    harmless — lookups select by slot, so a redundant entry cannot change which
    result governs a slot — and is documented only so implementations are not
    surprised by the dead branch.

    Args:
        results: Retained results, oldest first.
        result: The newly agreed result.

    Returns:
        The updated history, trimmed to stay below `MAX_RESULTS` entries.
    """
    if not result.versions:
        return list(results)

    if results and results[-1] == result:
        return list(results)

    updated = [*results, result]

    if len(updated) >= MAX_RESULTS:
        updated = updated[1:]

    return updated


def latest_result(results: Sequence[InfoSyncResult], slot: int) -> Optional[InfoSyncResult]:
    """Find the newest agreed result that governs the given slot.

    Results are consulted by slot rather than by recency so that a duty is
    always processed under the agreement that was in force for it, even if a
    newer agreement has since arrived.

    Args:
        results: Retained results, oldest first.
        slot: The slot being processed.

    Returns:
        The newest result whose slot is not after `slot`, or None if there is
        none.
    """
    found: Optional[InfoSyncResult] = None

    for result in results:
        if result.slot > slot:
            break

        found = result

    return found


def most_preferred_consensus_protocol(protocols: Sequence[str]) -> str:
    """Select the cluster-wide consensus protocol from an agreed protocol list.

    The agreed list mixes consensus protocol IDs with every other protocol the
    cluster supports, so selection takes the first entry under the consensus
    prefix. A list with no consensus protocol falls back to QBFT v2 rather than
    failing, which keeps a cluster running through a malformed agreement.

    Args:
        protocols: Agreed protocol IDs in preference order.

    Returns:
        The consensus protocol ID to use.

    Example:
        >>> most_preferred_consensus_protocol(
        ...     ["/charon/parsigex/2.0.0", "/charon/consensus/qbft/2.0.0"]
        ... )
        '/charon/consensus/qbft/2.0.0'
        >>> most_preferred_consensus_protocol([])
        '/charon/consensus/qbft/2.0.0'
    """
    for protocol_id in protocols:
        if protocol_id.startswith(CONSENSUS_PROTOCOL_ID_PREFIX):
            return protocol_id

    return QBFT_V2_PROTOCOL_ID


def selected_protocols(
    results: Sequence[InfoSyncResult],
    slot: int,
    local_protocols: Sequence[str],
) -> List[str]:
    """Resolve the protocol IDs in force at a slot.

    Args:
        results: Retained results, oldest first.
        slot: The slot being processed.
        local_protocols: This node's own protocol IDs, used before the first
            agreement is reached.

    Returns:
        The agreed protocol IDs, or the local ones if no agreement governs the
        slot.
    """
    result = latest_result(results, slot)

    return list(result.protocols) if result is not None else list(local_protocols)


def selected_proposal_types(results: Sequence[InfoSyncResult], slot: int) -> List[str]:
    """Resolve the proposal types in force at a slot.

    Before the first agreement, only `FULL` is used: a node must not assume its
    peers support builder or synthetic proposals until they have said so.

    Args:
        results: Retained results, oldest first.
        slot: The slot being processed.

    Returns:
        The agreed proposal types, or `["full"]` if no agreement governs the
        slot.
    """
    result = latest_result(results, slot)

    return list(result.proposals) if result is not None else [ProposalType.FULL.value]
