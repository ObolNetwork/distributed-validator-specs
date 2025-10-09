"""
QBFT Consensus Protocol - Single Instance Implementation

This module implements QBFT consensus with a single class per duty,
based purely on message history and upon rules.
"""

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from dv_spec.subspecs.consensus.cryptography import hash_value
from dv_spec.subspecs.consensus.qbft.definition import Definition
from dv_spec.subspecs.consensus.qbft.message import MsgType, QBFTConsensusMsg, QBFTMsg
from dv_spec.subspecs.consensus.qbft.transport import Transport
from dv_spec.subspecs.consensus.timer import RoundTimer, get_default_timer
from dv_spec.types import Duty


class UponRule(Enum):
    """UponRule defines the event based rules that are triggered when messages are received."""

    NOTHING = "nothing"
    JUSTIFIED_PRE_PREPARE = "justified_pre_prepare"
    QUORUM_PREPARES = "quorum_prepares"
    QUORUM_COMMITS = "quorum_commits"
    UNJUST_QUORUM_ROUND_CHANGES = "unjust_quorum_round_changes"
    F_PLUS_1_ROUND_CHANGES = "f_plus_1_round_changes"
    QUORUM_ROUND_CHANGES = "quorum_round_changes"
    JUSTIFIED_DECIDED = "justified_decided"
    ROUND_TIMEOUT = "round_timeout"


@dataclass
class QBFTConsensus:
    """
    QBFT consensus instance for a specific duty.

    Maintains all data needed for QBFT consensus including message history,
    state information, and timing for round changes.
    """

    d: Definition
    """QBFT system parameters."""

    t: Transport
    """Transport layer for sending/receiving messages."""

    duty: Duty
    """Current duty being agreed upon."""

    peer: int
    """Index of this peer in the cluster."""

    proposal_value: Any
    """Proposal value for this node."""

    round: int = 1
    """Current round number."""

    prepared_round: Optional[int] = None
    """Prepared round if any."""

    prepared_value: Optional[Any] = None
    """Prepared value if any."""

    prepared_value_hash: Optional[bytes] = None
    """Hash of the prepared value if any."""

    prepared_justification: List[QBFTMsg] = field(default_factory=list)
    """Justification for the prepared value if any."""

    q_commit: List[QBFTMsg] = field(default_factory=list)
    """Stored quorum of COMMIT messages."""

    buffer: Dict[int, List[QBFTConsensusMsg]] = field(default_factory=dict)
    """Storer for peer messages."""

    dedup_rules: Dict[Tuple[UponRule, int], bool] = field(default_factory=dict)
    """Deduplication for rules triggered per round."""

    round_start_time: float = field(default_factory=time.time)
    """Timestamp when the current round started."""

    timer: RoundTimer = field(init=False)
    """Round timer instance."""

    def __post_init__(self) -> None:
        """Initialize specific timer implementation."""
        self.timer = get_default_timer(self.duty)
        # Store proposal value in transport
        proposal_hash = hash_value(self.proposal_value)
        self.t.set_values({proposal_hash: self.proposal_value})

    def is_justified_pre_prepare(self, consensus_msg: QBFTConsensusMsg) -> bool:
        """Returns true if the PRE-PREPARE message is justified."""
        msg = consensus_msg.msg
        if msg.type != MsgType.PRE_PREPARE:
            return False

        if self.d.is_leader(self.duty, msg.round, msg.peer_idx) is False:
            return False

        # Round 1: no justification needed
        if msg.round == 1:
            return True

        # Further rounds: must have either (1) or (2)
        # - (1) must have a quorum of ROUND-CHANGE messages with nothing prepared
        # - (2) must have a quorum of ROUND-CHANGE messages with a prepared value
        #       and a quorum of PREPARE messages for the highest prepared round/value

        qrc = [
            j
            for j in consensus_msg.justification
            if j.type == MsgType.ROUND_CHANGE and j.round == msg.round
        ]
        if len(qrc) < self.d.quorum():
            return False

        # (1)
        all_none_prepared = all(
            rc.prepared_round is None and rc.prepared_value_hash is None for rc in qrc
        )
        if all_none_prepared:
            return True

        # (2)
        prepared_values: Dict[Tuple[int, bytes], int] = {}
        for rc in consensus_msg.justification:
            if rc.type != MsgType.PREPARE:
                continue
            if rc.value_hash is None:
                continue
            key = (rc.round, rc.value_hash)
            prepared_values[key] = prepared_values.get(key, 0) + 1

        highest_pr, highest_pv_hash = max(prepared_values.keys(), key=lambda x: x[0])

        # Ensure quorum of PREPAREs for highest prepared round/value
        if prepared_values[(highest_pr, highest_pv_hash)] < self.d.quorum():
            return False

        # Ensure no ROUND-CHANGE has higher prepared round
        if any(rc.prepared_round is not None and rc.prepared_round > highest_pr for rc in qrc):
            return False

        # Ensure at least one ROUND-CHANGE with the highest prepared round/value
        if not any(
            rc.prepared_round == highest_pr and rc.prepared_value_hash == highest_pv_hash
            for rc in qrc
        ):
            return False

        # Ensure PRE-PREPARE value matches value chosen from justifications
        return highest_pv_hash == msg.value_hash

    def is_justified_round_change(self, consensus_msg: QBFTConsensusMsg) -> bool:
        """Returns true if the ROUND-CHANGE message's prepared round/value is justified."""
        msg = consensus_msg.msg
        if msg.type != MsgType.ROUND_CHANGE:
            return False

        if (
            len(consensus_msg.justification) == 0
            and msg.prepared_round is None
            and msg.prepared_value_hash is None
        ):
            return True

        pr = msg.prepared_round
        pv_hash = msg.prepared_value_hash
        prepare_justifications = [
            j
            for j in consensus_msg.justification
            if j.type == MsgType.PREPARE and j.round == pr and j.value_hash == pv_hash
        ]

        if len(prepare_justifications) < self.d.quorum():
            return False

        return True

    def is_justified_decided(self, consensus_msg: QBFTConsensusMsg) -> bool:
        """Returns true if the DECIDED message is justified by quorum of COMMIT messages."""
        msg = consensus_msg.msg
        if msg.type != MsgType.DECIDED:
            return False

        commit_justifications = [
            j
            for j in consensus_msg.justification
            if j.type == MsgType.COMMIT and j.round == msg.round and j.value_hash == msg.value_hash
        ]

        if len(commit_justifications) < self.d.quorum():
            return False

        return True

    def is_justified(self, consensus_msg: QBFTConsensusMsg) -> bool:
        """Returns true if message is justified or if it does not need justification."""
        msg = consensus_msg.msg
        match msg.type:
            case MsgType.PRE_PREPARE:
                return self.is_justified_pre_prepare(consensus_msg)
            case MsgType.PREPARE | MsgType.COMMIT:
                return True
            case MsgType.ROUND_CHANGE:
                return self.is_justified_round_change(consensus_msg)
            case MsgType.DECIDED:
                return self.is_justified_decided(consensus_msg)

    def _buffer_message(self, consensus_msg: QBFTConsensusMsg) -> None:
        """Store message in buffer."""
        if consensus_msg.msg.peer_idx not in self.buffer:
            self.buffer[consensus_msg.msg.peer_idx] = []
        self.buffer[consensus_msg.msg.peer_idx].append(consensus_msg)

    def _flatten(self) -> List[QBFTConsensusMsg]:
        """
        Returns the buffer as a list containing all the buffered messages
        and their justifications.
        """
        res: List[QBFTConsensusMsg] = []
        for msgs in self.buffer.values():
            for msg in msgs:
                res.append(msg)
                for j in msg.justification:
                    # TODO: in Charon we have a buffer of Msg[I,V] interface
                    # it's neither QBFTMsg nor QBFTConsensusMsg
                    # here we are storing QBFTConsensusMsg, should we change ?
                    # maybe we could have a third message which would be the internal
                    # representation of a message, e.g. Msg

                    # Transform justification QBFTMsg into QBFTConsensusMsg with empty justification
                    j_msg = QBFTConsensusMsg(msg=j, justification=[], values=[])
                    res.append(j_msg)
        return res

    def _classify(self, consensus_msg: QBFTConsensusMsg) -> Tuple[UponRule, List[QBFTMsg]]:
        """
        Returns the rule triggered upon receipt of the last message and its justification.
        Should be called after is_justified() and buffer_message().
        """
        msg = consensus_msg.msg
        match msg.type:
            case MsgType.DECIDED:
                return UponRule.JUSTIFIED_DECIDED, consensus_msg.justification

            case MsgType.PRE_PREPARE:
                if msg.round < self.round:
                    return UponRule.NOTHING, []
                return UponRule.JUSTIFIED_PRE_PREPARE, []

            case MsgType.PREPARE:
                if msg.round != self.round:
                    return UponRule.NOTHING, []

                prepares = [
                    j.msg
                    for j in self._flatten()
                    if j.msg.type == MsgType.PREPARE
                    and j.msg.round == msg.round
                    and j.msg.value_hash == msg.value_hash
                ]
                if len(prepares) >= self.d.quorum():
                    return UponRule.QUORUM_PREPARES, prepares

            case MsgType.COMMIT:
                if msg.round != self.round:
                    return UponRule.NOTHING, []

                commits = [
                    j.msg
                    for j in self._flatten()
                    if j.msg.type == MsgType.COMMIT
                    and j.msg.round == msg.round
                    and j.msg.value_hash == msg.value_hash
                ]
                if len(commits) >= self.d.quorum():
                    return UponRule.QUORUM_COMMITS, commits

            case MsgType.ROUND_CHANGE:
                if msg.round < self.round:
                    return UponRule.NOTHING, []

                all_msg = self._flatten()
                if msg.round > self.round:
                    # Check if we have f+1 ROUND-CHANGE messages for rounds > current round
                    # peer -> highest ROUND-CHANGE message
                    highest_by_source: Dict[int, QBFTConsensusMsg] = {}
                    for m in all_msg:
                        if m.msg.type != MsgType.ROUND_CHANGE:
                            continue

                        if m.msg.round <= self.round:
                            continue

                        peer_in_highest = highest_by_source.get(m.msg.peer_idx)
                        if peer_in_highest and peer_in_highest.msg.round > m.msg.round:
                            continue

                        highest_by_source[m.msg.peer_idx] = m

                        if len(highest_by_source) == self.d.faulty() + 1:
                            break

                    if len(highest_by_source) < self.d.faulty() + 1:
                        return UponRule.NOTHING, []
                    else:
                        return (
                            UponRule.F_PLUS_1_ROUND_CHANGES,
                            [v.msg for v in highest_by_source.values()],
                        )

                # else msg.Round == round

                qrc = [
                    m
                    for m in all_msg
                    if m.msg.type == MsgType.ROUND_CHANGE and m.msg.round == msg.round
                ]
                if len(qrc) < self.d.quorum():
                    return UponRule.NOTHING, []

                # Get justified QRC (Algorithm 4:1)
                justified_qrc: List[QBFTMsg] = []
                found_justified = False

                # First check for quorum none prepared
                none_prepared_qrc = [
                    m
                    for m in all_msg
                    if (
                        m.msg.type == MsgType.ROUND_CHANGE
                        and m.msg.round == msg.round
                        and m.msg.prepared_round is None
                        and m.msg.prepared_value_hash is None
                    )
                ]

                if len(none_prepared_qrc) >= self.d.quorum():
                    justified_qrc = [m.msg for m in none_prepared_qrc]
                    found_justified = True
                else:
                    # Get all prepare quorums
                    # (round, value_hash) -> {peer_idx: msg}
                    prepare_sets: Dict[Tuple[int, bytes], Dict[int, QBFTMsg]] = {}

                    for m in all_msg:
                        if m.msg.type != MsgType.PREPARE:
                            continue
                        if m.msg.value_hash is None:
                            continue

                        key = (m.msg.round, m.msg.value_hash)
                        if key not in prepare_sets:
                            prepare_sets[key] = {}
                        prepare_sets[key][m.msg.peer_idx] = m.msg

                    # Check each prepare quorum
                    for msgs_dict in prepare_sets.values():
                        if len(msgs_dict) < self.d.quorum():
                            continue

                        prepares = list(msgs_dict.values())
                        qrc_candidates: List[QBFTConsensusMsg] = []
                        has_highest_prepared = False
                        pr = prepares[0].round
                        pv = prepares[0].value_hash
                        used_sources = set()

                        for rc in qrc:
                            if rc.msg.prepared_round is not None and rc.msg.prepared_round > pr:
                                continue

                            if rc.msg.peer_idx in used_sources:
                                continue

                            if rc.msg.prepared_round == pr and rc.msg.prepared_value_hash == pv:
                                has_highest_prepared = True

                            qrc_candidates.append(rc)
                            used_sources.add(rc.msg.peer_idx)

                        if len(qrc_candidates) >= self.d.quorum() and has_highest_prepared:
                            justified_qrc = [rc.msg for rc in qrc_candidates] + prepares
                            found_justified = True
                            break

                if not found_justified:
                    return UponRule.UNJUST_QUORUM_ROUND_CHANGES, []

                if not self.d.is_leader(self.duty, msg.round, self.peer):
                    return UponRule.NOTHING, []

                return UponRule.QUORUM_ROUND_CHANGES, justified_qrc

        return UponRule.NOTHING, []

    def _change_round(self, r: int) -> None:
        """Change to a new round if round is greater than current."""
        if r == self.round:
            return

        self.round = r
        self.dedup_rules = {}

    def handle_message(self, consensus_msg: QBFTConsensusMsg) -> List[QBFTConsensusMsg]:
        """Handle an incoming QBFT consensus message using upon rules."""
        msg = consensus_msg.msg

        # Store value mappings in transport only
        if consensus_msg.values:
            value_mappings = {}
            for value in consensus_msg.values:
                val_hash = hash_value(value)
                value_mappings[val_hash] = value
            self.t.set_values(value_mappings)

        # Only handle messages for our duty
        if msg.duty != self.duty:
            return []

        if len(self.q_commit) > 0:
            if msg.peer_idx != self.peer and msg.type == MsgType.ROUND_CHANGE:
                value_hash: Optional[bytes] = self.q_commit[0].value_hash
                if value_hash is None:
                    return []
                return self.t.broadcast_message(
                    MsgType.DECIDED,
                    self.duty,
                    self.peer,
                    self.round,
                    value_hash,
                    self.q_commit,
                )
            return []

        if not self.is_justified(consensus_msg):
            return []

        self._buffer_message(consensus_msg)

        rule, justification = self._classify(consensus_msg)
        if rule == UponRule.NOTHING:
            return []

        if (rule, self.round) in self.dedup_rules:
            return []
        self.dedup_rules[(rule, self.round)] = True
        match rule:
            case UponRule.JUSTIFIED_PRE_PREPARE:
                self._change_round(msg.round)

                # TODO stop previous timer and start new one

                if msg.value_hash is None:
                    return []
                return self.t.broadcast_message(
                    MsgType.PREPARE, self.duty, self.peer, self.round, msg.value_hash
                )

            case UponRule.QUORUM_PREPARES:
                self.prepared_round = msg.round
                self.prepared_value_hash = msg.value_hash
                self.prepared_justification = justification

                if msg.value_hash is None:
                    return []
                return self.t.broadcast_message(
                    MsgType.COMMIT, self.duty, self.peer, self.round, msg.value_hash
                )

            case UponRule.QUORUM_COMMITS:
                self._change_round(msg.round)

                self.q_commit = justification

                # TODO stop previous timer and start new one

                # TODO? Call external decide function here

            case UponRule.JUSTIFIED_DECIDED:
                self._change_round(msg.round)

                self.q_commit = justification

                # TODO stop previous timer and start new one

                # TODO? Call external decide function here

            case UponRule.F_PLUS_1_ROUND_CHANGES:
                # Find next minimum round from received round change messages
                if len(justification) < self.d.faulty() + 1:
                    raise ValueError("Frc too short")

                # Get the smallest round in the set
                rmin = float("inf")
                for j in justification:
                    if j.type != MsgType.ROUND_CHANGE:
                        raise ValueError("Frc contain non-round change")
                    elif j.round <= self.round:
                        raise ValueError("Frc round not in future")

                    if rmin > j.round:
                        rmin = j.round

                self._change_round(int(rmin))

                # TODO stop previous timer and start new one

                return self.t.broadcast_round_change(
                    self.duty,
                    self.peer,
                    self.round,
                    self.prepared_round,
                    self.prepared_value_hash,
                    self.prepared_justification,
                )

            case UponRule.QUORUM_ROUND_CHANGES:
                # Extracts the single justified Pr and Pv from quorum PREPARES in list of messages
                prepared_values: Dict[Tuple[int, bytes], int] = {}
                for rc in justification:
                    if rc.type != MsgType.PREPARE:
                        continue
                    if rc.prepared_round is not None and rc.prepared_value_hash is not None:
                        key = (rc.prepared_round, rc.prepared_value_hash)
                        prepared_values[key] = prepared_values.get(key, 0) + 1

                if prepared_values:
                    highest_pr, highest_pv_hash = max(prepared_values.keys(), key=lambda x: x[0])
                    # Ensure quorum of PREPAREs for highest prepared round/value
                    # or send own PRE-PREPARE
                    if prepared_values[(highest_pr, highest_pv_hash)] >= self.d.quorum():
                        return self.t.broadcast_message(
                            MsgType.PRE_PREPARE,
                            self.duty,
                            self.peer,
                            self.round,
                            highest_pv_hash,
                            justification,
                        )

                # Send own PRE-PREPARE
                return self.t.broadcast_pre_prepare(
                    self.duty, self.peer, self.round, hash_value(self.proposal_value), justification
                )

            case UponRule.UNJUST_QUORUM_ROUND_CHANGES:
                return []

            case _:
                raise ValueError("Unknown upon rule", rule)

        return []
