"""
QBFT Consensus Protocol - Single Instance Implementation

This module implements QBFT consensus with a single class per duty,
based purely on message history and upon rules.
"""

import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from dv_spec.subspecs.consensus.qbft.message import MsgType, QBFTConsensusMsg, QBFTMsg
from dv_spec.subspecs.consensus.timer import RoundTimer, get_default_timer
from dv_spec.types import Duty
from dv_spec.types.base import StrictBaseModel


class QBFTDefinition(StrictBaseModel):
    """
    QBFT consensus system parameters and computed properties.
    This remains constant across multiple instances of consensus.
    """

    nodes: int
    """Total number of nodes in the consensus cluster."""

    def quorum(self) -> int:
        """Calculate quorum size."""
        return int(math.ceil(float(self.nodes * 2) / 3))

    def faulty(self) -> int:
        """Calculate maximum number of faulty nodes."""
        return int(math.floor(float(self.nodes - 1) / 3))

    def is_leader(self, duty: Duty, round_num: int, peer: int) -> bool:
        """Deterministic leader election function"""
        return (duty.slot + duty.type + round_num) % self.nodes == peer

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

    d: QBFTDefinition
    """QBFT system parameters."""

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

    dedupRules: Dict[Tuple[UponRule, int], bool] = field(default_factory=dict)
    """Deduplication for rules triggered per round."""

    round_start_time: float = field(default_factory=time.time)
    """Timestamp when the current round started."""

    timer: RoundTimer = field(init=False)
    """Round timer instance."""

    # TODO Charon works a bit differently than this
    mapping: Dict[bytes, Any] = field(default_factory=dict)
    """Stores value mappings by their hash."""

    def __post_init__(self):
        """Initialize specific timer implementation."""
        self.timer = get_default_timer(self.duty)
        self._store_value_mapping([self.proposal_value])

    def _hash_value(self, value: Any) -> bytes:
        """Compute a simple hash of the value."""
        # TODO recreate hashing similar to Charon
        return hash(value).to_bytes(32, byteorder='big', signed=True)

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
        # - (2) must have a quorum of ROUND-CHANGE messages with a prepared value and a quorum of PREPARE messages
        # for the highest prepared round/value

        qrc = [j for j in consensus_msg.justification if j.type == MsgType.ROUND_CHANGE and j.round == msg.round]
        if len(qrc) < self.d.quorum():
            return False

        # (1)
        all_none_prepared = all(rc.prepared_round is None and rc.prepared_value_hash is None for rc in qrc)
        if all_none_prepared:
            return True

        # (2)
        prepared_values: Dict[Tuple[int, bytes], int] = {}
        for rc in consensus_msg.justification:
            if rc.type != MsgType.PREPARE:
                continue
            prepared_values[(rc.round, rc.value_hash)] = prepared_values.get((rc.round, rc.value_hash), 0) + 1

        highest_pr, highest_pv_hash = max(prepared_values.keys(), key=lambda x: x[0])

        # Ensure quorum of PREPAREs for highest prepared round/value
        if prepared_values[(highest_pr, highest_pv_hash)] < self.d.quorum():
            return False

        # Ensure no ROUND-CHANGE has higher prepared round
        if any(rc.prepared_round is not None and rc.prepared_round > highest_pr for rc in qrc):
            return False

        # Ensure at least one ROUND-CHANGE with the highest prepared round/value
        if not any(rc.prepared_round == highest_pr and rc.prepared_value_hash == highest_pv_hash for rc in qrc):
            return False

        # Ensure PRE-PREPARE value matches value chosen from justifications
        return highest_pv_hash == msg.value_hash

    def is_justified_round_change(self, consensus_msg: QBFTConsensusMsg) -> bool:
        """Returns true if the ROUND-CHANGE message's prepared round/value is justified."""
        msg = consensus_msg.msg
        if msg.type != MsgType.ROUND_CHANGE:
            return False

        if len(consensus_msg.justification) == 0 and msg.prepared_round is None and msg.prepared_value_hash is None:
            return True

        pr = msg.prepared_round
        pv_hash = msg.prepared_value_hash
        prepare_justifications = [j for j in consensus_msg.justification if j.type == MsgType.PREPARE and
                                j.round == pr and
                                j.value_hash == pv_hash]

        if len(prepare_justifications) < self.d.quorum():
            return False

        return True

    def is_justified_decided(self, consensus_msg: QBFTConsensusMsg) -> bool:
        """Returns true if the DECIDED message is justified by quorum of COMMIT messages."""
        msg = consensus_msg.msg
        if msg.type != MsgType.DECIDED:
            return False

        commit_justifications = [j for j in consensus_msg.justification
                                 if j.type == MsgType.COMMIT and
                                 j.round == msg.round and
                                 j.value_hash == msg.value_hash]

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
            case _:
                return False

    def _buffer_message(self, consensus_msg: QBFTConsensusMsg) -> None:
        """Store message in buffer."""
        if consensus_msg.msg.peer_idx not in self.buffer:
            self.buffer[consensus_msg.msg.peer_idx] = []
        self.buffer[consensus_msg.msg.peer_idx].append(consensus_msg)

    def _flatten(self) -> List[QBFTConsensusMsg]:
        """Returns the buffer as a list containing all the buffered messages and their justifications."""
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
                    jMsg = QBFTConsensusMsg(msg=j, justification=[], values=[])
                    res.append(jMsg)
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

                prepares = [j for j in self._flatten() if j.msg.type == MsgType.PREPARE and j.msg.round == msg.round and j.msg.value_hash == msg.value_hash]
                if len(prepares) >= self.d.quorum():
                    return UponRule.QUORUM_PREPARES, prepares

            case MsgType.COMMIT:
                if msg.round != self.round:
                    return UponRule.NOTHING, []

                commits = [j for j in self._flatten() if j.msg.type == MsgType.COMMIT and j.msg.round == msg.round and j.msg.value_hash == msg.value_hash]
                if len(commits) >= self.d.quorum():
                    return UponRule.QUORUM_COMMITS, commits

            case MsgType.ROUND_CHANGE:
                if msg.round < self.round:
                    return UponRule.NOTHING, []

                all = self._flatten()
                if msg.round > self.round:
                    # Check if we have f+1 ROUND-CHANGE messages for rounds > current round
                    highest_by_source = {} # peer -> highest ROUND-CHANGE message
                    for m in all:
                        if m.msg.type != MsgType.ROUND_CHANGE:
                            continue

                        if m.msg.round <= self.round:
                            continue

                        if m.msg.peer_idx in highest_by_source and highest_by_source[m.msg.peer_idx].round > m.msg.round:
                            continue

                        highest_by_source[m.msg.peer_idx] = m

                        if len(highest_by_source) == self.d.faulty() + 1:
                            break

                    if len(highest_by_source) < self.d.faulty() + 1:
                        return UponRule.NOTHING, []
                    else:
                        return UponRule.F_PLUS_1_ROUND_CHANGES, list(highest_by_source.values())

                # else msg.Round == round

                qrc = [m for m in all if m.msg.type == MsgType.ROUND_CHANGE and m.msg.round == msg.round]
                if len(qrc) < self.d.quorum():
                    return UponRule.NOTHING, []

                # Get justified QRC (Algorithm 4:1)
                justified_qrc: List[QBFTConsensusMsg] = []
                found_justified = False

                # First check for quorum none prepared
                none_prepared_qrc = [
                    m for m in all
                    if (m.msg.type == MsgType.ROUND_CHANGE and
                        m.msg.round == msg.round and
                        m.msg.prepared_round is None and
                        m.msg.prepared_value_hash is None)
                ]

                if len(none_prepared_qrc) >= self.d.quorum():
                    justified_qrc = none_prepared_qrc
                    found_justified = True
                else:
                    # Get all prepare quorums
                    # (round, value_hash) -> {peer_idx: msg}
                    prepare_sets: Dict[Tuple[int, bytes], Dict[int, QBFTMsg]] = {}

                    for m in all:
                        if m.msg.type != MsgType.PREPARE:
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
                        qrc_candidates = []
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
                            justified_qrc = qrc_candidates + prepares
                            found_justified = True
                            break

                if not found_justified:
                    return UponRule.UNJUST_QUORUM_ROUND_CHANGES, []

                if not self.d.is_leader(self.duty, msg.round, self.peer):
                    return UponRule.NOTHING, []

                return UponRule.QUORUM_ROUND_CHANGES, justified_qrc

            case _:
                raise ValueError("Unknown message type")

        return UponRule.NOTHING, []

    def _sign_message(self, msg: QBFTMsg) -> bytes:
        """Mock signing of a message"""
        # TODO: Implement real signing
        return b'\x00' * 65  # Mock signature

    def _broadcast_message(self, type: MsgType, value_hash: bytes, justification: Optional[List[QBFTMsg]] = None) -> List[QBFTConsensusMsg]:
        """Broadcast non-ROUND-CHANGE messages for current round"""
        res: List[QBFTConsensusMsg] = []
        for _ in range(self.d.nodes):
            msg = QBFTMsg(
                    type=type,
                    duty=self.duty,
                    round=self.round,
                    peer_idx=self.peer,
                    value_hash=value_hash
                )
            msg.signature = self._sign_message(msg)
            res.append(QBFTConsensusMsg(
                msg=msg,
                justification=justification or [],
                values=[self.mapping.get(value_hash)] if self.mapping.get(value_hash) else []
            ))
        return res

    def _broadcast_round_change(self) -> List[QBFTConsensusMsg]:
        """Broadcast ROUND_CHANGE message for current round"""
        res = []
        for _ in range(self.d.nodes):
            msg = QBFTMsg(
                    type=MsgType.ROUND_CHANGE,
                    duty=self.duty,
                    round=self.round,
                    peer_idx=self.peer,
                    prepared_round=self.prepared_round,
                    prepared_value_hash=self.prepared_value_hash,
                )
            msg.signature = self._sign_message(msg)
            res.append(QBFTConsensusMsg(
                msg=msg,
                justification=self.prepared_justification,
                values=[self.mapping.get(self.prepared_value_hash)] if self.mapping.get(self.prepared_value_hash) else []
            ))
        return res

    def _broadcast_own_pre_prepare(self, justification: List[QBFTMsg]) -> List[QBFTConsensusMsg]:
        if justification is None:
            raise ValueError("Justification cannot be None")

        return self._broadcast_message(MsgType.PRE_PREPARE, self._hash_value(self.proposal_value), justification)

    def _store_value_mapping(self, values: List[Any]):
        for v in values:
            self.mapping[self._hash_value(v)] = v

    def _change_round(self, round: int):
        """Change to a new round if round is greater than current."""
        if round == self.round:
            return

        self.round = round
        self.dedupRules = {}

    def handle_message(self, consensus_msg: QBFTConsensusMsg) -> List[QBFTConsensusMsg]:
        """Handle an incoming QBFT consensus message using upon rules."""
        msg = consensus_msg.msg

        # TODO In Charon this happens in the transport layer
        # What to do ?
        self._store_value_mapping(consensus_msg.values)

        # Only handle messages for our duty
        if msg.duty != self.duty:
            return []

        if len(self.q_commit) > 0:
            if msg.peer_idx != self.peer and msg.type == MsgType.ROUND_CHANGE:
                return self._broadcast_message(MsgType.ROUND_CHANGE, self.q_commit[0].value_hash,self.q_commit)
            return []

        if not self.is_justified(consensus_msg):
            return []

        self._buffer_message(consensus_msg)

        rule, justification = self._classify(consensus_msg)
        if rule == UponRule.NOTHING:
            return []

        if (rule, self.round) in self.dedupRules:
            return []
        self.dedupRules[(rule, self.round)] = True
        print(rule)
        match rule:
            case UponRule.JUSTIFIED_PRE_PREPARE:
                self._change_round(msg.round)

                # TODO stop previous timer and start new one

                return self._broadcast_message(MsgType.PREPARE, msg.value_hash, None)

            case UponRule.QUORUM_PREPARES:
                
                self.prepared_round = msg.round
                self.prepared_value_hash = msg.value_hash
                self.prepared_justification = justification

                return self._broadcast_message(MsgType.COMMIT, msg.value_hash, None)

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
                rmin = float('inf')
                for j in justification:
                    if j.type != MsgType.ROUND_CHANGE:
                        raise ValueError("Frc contain non-round change")
                    elif j.round <= self.round:
                        raise ValueError("Frc round not in future")

                    if rmin > j.round:
                        rmin = j.round

                self._change_round(int(rmin))

                # TODO stop previous timer and start new one

                return self._broadcast_round_change()

            case UponRule.QUORUM_ROUND_CHANGES:

                # Extracts the single justified Pr and Pv from quorum PREPARES in list of messages
                prepared_values: Dict[Tuple[int, bytes], int] = {}
                for rc in justification:
                    if rc.type != MsgType.PREPARE:
                        continue
                    if rc.prepared_round is not None and rc.prepared_value_hash is not None:
                        prepared_values[(rc.prepared_round, rc.prepared_value_hash)] = prepared_values.get((rc.prepared_round, rc.prepared_value_hash), 0) + 1

                highest_pr, highest_pv_hash = max(prepared_values.keys(), key=lambda x: x[0])

                # Ensure quorum of PREPAREs for highest prepared round/value or send own PRE-PREPARE
                if prepared_values[(highest_pr, highest_pv_hash)] >= self.d.quorum():
                    return self._broadcast_message(MsgType.PRE_PREPARE, highest_pv_hash, justification)
                else:
                    return self._broadcast_own_pre_prepare(justification)

            case UponRule.UNJUST_QUORUM_ROUND_CHANGES:
                return []

            case _:
                raise ValueError("Unknown upon rule", rule)

        return []
