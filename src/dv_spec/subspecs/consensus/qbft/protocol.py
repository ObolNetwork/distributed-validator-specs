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


class UponRule(Enum):
    """Upon rules that trigger events in QBFT."""
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
    
    Each instance is identified by its duty (type + slot) and handles
    consensus for that specific duty.
    """
    duty: Duty
    cluster_size: int
    peer_idx: int
    current_round: int = 1

    # Proposal value for this node (what we want to propose when leader)
    proposal_value: Optional[Any] = None
    proposal_value_hash: Optional[bytes] = None

    # Current consensus value and hash
    current_value: Optional[Any] = None
    current_value_hash: Optional[bytes] = None

    # Preparation tracking
    prepared_round: Optional[int] = None
    prepared_value: Optional[Any] = None
    prepared_value_hash: Optional[bytes] = None

    # Message storage for each round
    received_pre_prepares: Dict[int, QBFTMsg] = field(default_factory=dict)
    received_prepares: Dict[int, List[QBFTMsg]] = field(default_factory=lambda: {})
    received_commits: Dict[int, List[QBFTMsg]] = field(default_factory=lambda: {})
    received_round_changes: Dict[int, List[QBFTMsg]] = field(default_factory=lambda: {})
    received_decided: List[QBFTMsg] = field(default_factory=list)

    # Timing for round changes
    round_start_time: float = field(default_factory=time.time)
    timer: RoundTimer = field(init=False)  # Round timer implementation

    # Byzantine fault tolerance properties
    max_byzantine_faults: int = field(init=False)
    quorum_size: int = field(init=False)

    def __post_init__(self):
        """Calculate Byzantine fault tolerance parameters after initialization."""
        self.max_byzantine_faults = self._compute_faulty(self.cluster_size)
        self.quorum_size = self._compute_quorum(self.cluster_size)
        self.timer = get_default_timer(self.duty)

    def _compute_quorum(self, nodes: int) -> int:
        """Quorum calculation using standard Byzantine fault tolerant formula: ceil(2n/3)."""
        return int(math.ceil(float(nodes * 2) / 3))

    def _compute_faulty(self, nodes: int) -> int:
        """Faulty nodes calculation using standard Byzantine fault tolerant formula: floor((n-1)/3)."""
        return int(math.floor(float(nodes - 1) / 3))

    def compute_leader(self, round_num: int) -> int:
        """Compute the leader for a given round using round-robin."""
        return (self.duty.slot + self.duty.type + round_num) % self.cluster_size

    def has_pre_prepare_for_round(self, round_num: int) -> bool:
        """Check if we have a PRE-PREPARE for the given round."""
        return round_num in self.received_pre_prepares

    def has_quorum_prepares_for_round_value(self, round_num: int, value_hash: bytes) -> bool:
        """Check if we have quorum PREPARE messages for given round and value."""
        if round_num not in self.received_prepares:
            return False

        matching_prepares = [
            msg for msg in self.received_prepares[round_num]
            if msg.value_hash == value_hash
        ]

        # Count our own implicit PREPARE if we have sent/would send one for this value
        count = len(matching_prepares)
        if (self.has_pre_prepare_for_round(round_num) and
            self.received_pre_prepares[round_num].value_hash == value_hash):
            count += 1  # Add our own implicit PREPARE

        return count >= self.quorum_size

    def has_quorum_commits_for_round_value(self, round_num: int, value_hash: bytes) -> bool:
        """Check if we have quorum COMMIT messages for given round and value."""
        if round_num not in self.received_commits:
            return False

        matching_commits = [
            msg for msg in self.received_commits[round_num]
            if msg.value_hash == value_hash
        ]

        # Count our own implicit COMMIT if we have the prerequisites
        count = len(matching_commits)
        if (self.has_pre_prepare_for_round(round_num) and
            self.received_pre_prepares[round_num].value_hash == value_hash and
            self._count_matching_prepares(round_num, value_hash) >= self.quorum_size):
            count += 1  # Add our own implicit COMMIT

        return count >= self.quorum_size

    def _count_matching_prepares(self, round_num: int, value_hash: bytes) -> int:
        """Count PREPARE messages for given round and value, including our own implicit one."""
        if round_num not in self.received_prepares:
            return 0

        matching_prepares = [
            msg for msg in self.received_prepares[round_num]
            if msg.value_hash == value_hash
        ]

        count = len(matching_prepares)
        # Add our own implicit PREPARE if we have the PRE-PREPARE for this value
        if (self.has_pre_prepare_for_round(round_num) and
            self.received_pre_prepares[round_num].value_hash == value_hash):
            count += 1

        return count

    def is_decided(self) -> bool:
        """Check if consensus has been decided (we have a DECIDED message)."""
        return len(self.received_decided) > 0

    def can_prepare_for_round_value(self, round_num: int, value_hash: bytes) -> bool:
        """Check if we can send PREPARE for given round and value."""
        # Can prepare if we have the PRE-PREPARE and haven't prepared yet
        return (self.has_pre_prepare_for_round(round_num) and
                self.received_pre_prepares[round_num].value_hash == value_hash)

    def can_commit_for_round_value(self, round_num: int, value_hash: bytes) -> bool:
        """Check if we can send COMMIT for given round and value."""
        # Can commit if we have quorum PREPARE
        return self.has_quorum_prepares_for_round_value(round_num, value_hash)

    def can_decide_for_round_value(self, round_num: int, value_hash: bytes) -> bool:
        """Check if we can decide for given round and value."""
        # Can decide if we have quorum COMMIT (regardless of current decision state)
        return self.has_quorum_commits_for_round_value(round_num, value_hash)

    def is_justified(self, consensus_msg: QBFTConsensusMsg) -> bool:
        """Check if a message is justified or if it does not need justification."""
        msg = consensus_msg.msg
        justifications = consensus_msg.justification

        if msg.type == MsgType.PRE_PREPARE:
            return self.verify_pre_prepare_justification(msg, justifications)
        elif msg.type == MsgType.PREPARE:
            # PREPARE messages don't need separate justification beyond structural validation
            return True
        elif msg.type == MsgType.COMMIT:
            # COMMIT messages don't need separate justification beyond structural validation
            return True
        elif msg.type == MsgType.ROUND_CHANGE:
            return self.verify_round_change_justification(msg, justifications)
        elif msg.type == MsgType.DECIDED:
            return self.verify_decided_justification(msg, justifications)
        else:
            # Unknown message type - reject
            return False

    def verify_pre_prepare_justification(self, msg: QBFTMsg, justifications: List[QBFTMsg]) -> bool:
        """Verify PRE-PREPARE justification according to JustifyPrePrepare predicate."""
        if msg.round == 1:
            # Round 1: no justification needed
            return len(justifications) == 0

        # Round > 1: must have quorum of ROUND-CHANGE messages
        round_changes = [j for j in justifications if j.type == MsgType.ROUND_CHANGE]
        expected_round = msg.round - 1
        valid_rcs = [rc for rc in round_changes
                    if rc.duty == msg.duty and rc.round == expected_round]

        if len(valid_rcs) < self.quorum_size:
            return False

        # Check if proposed value is justified
        no_prepared = all(rc.prepared_round is None for rc in valid_rcs)

        if no_prepared:
            # Leader can propose any value
            return True

        # Must propose value with highest prepared round
        prepared_values = [(rc.prepared_round, rc.prepared_value_hash)
                          for rc in valid_rcs
                          if rc.prepared_round is not None and rc.prepared_value_hash is not None]

        if not prepared_values:
            return True

        highest_pr, highest_pv_hash = max(prepared_values, key=lambda x: x[0])
        if msg.value_hash != highest_pv_hash:
            return False

        # Must include quorum of PREPARE messages for (highest_pr, highest_pv_hash)
        prepare_qc = [j for j in justifications if j.type == MsgType.PREPARE and
                     j.round == highest_pr and j.value_hash == highest_pv_hash]

        return len(prepare_qc) >= self.quorum_size

    def verify_round_change_justification(self, msg: QBFTMsg, justifications: List[QBFTMsg]) -> bool:
        """Verify ROUND-CHANGE justification according to JustifyRoundChange predicate."""
        if msg.prepared_round is None:
            # No prepared value: no justification needed
            return len(justifications) == 0

        # Has prepared value: must have quorum of PREPARE messages
        prepare_justifications = [j for j in justifications if j.type == MsgType.PREPARE and
                                j.duty == msg.duty and
                                j.round == msg.prepared_round and
                                j.value_hash == msg.prepared_value_hash]

        if len(prepare_justifications) < self.quorum_size:
            return False

        # All PREPARE messages must be for the same round and value
        for prep in prepare_justifications:
            if prep.round != msg.prepared_round or prep.value_hash != msg.prepared_value_hash:
                return False

        return True

    def verify_commit_justification(self, msg: QBFTMsg, justifications: List[QBFTMsg]) -> bool:
        """Verify COMMIT message has quorum of PREPARE justifications."""
        prepare_count = sum(1 for j in justifications if j.type == MsgType.PREPARE and
                           j.duty == msg.duty and j.round == msg.round and j.value_hash == msg.value_hash)
        return prepare_count >= self.quorum_size

    def verify_decided_justification(self, msg: QBFTMsg, justifications: List[QBFTMsg]) -> bool:
        """Verify DECIDED message has quorum of COMMIT justifications."""
        commit_count = sum(1 for j in justifications if j.type == MsgType.COMMIT and
                          j.duty == msg.duty and j.round == msg.round and j.value_hash == msg.value_hash)
        return commit_count >= self.quorum_size

    def handle_message(self, consensus_msg: QBFTConsensusMsg) -> List[QBFTMsg]:
        """Handle an incoming QBFT consensus message using upon rules system."""
        msg = consensus_msg.msg

        # Only handle messages for our duty
        if msg.duty != self.duty:
            return []

        # Filter out unjustified messages early
        if consensus_msg.justification and not self.is_justified(consensus_msg):
            return []

        # Store the message first
        self._store_message(msg)

        # Extract the value from the consensus message if available
        extracted_value = None
        if consensus_msg.values:
            extracted_value = consensus_msg.values[0]

        # Classify message and get triggered rule
        rule, justification = self._classify_message(msg)

        # Process based on upon rule
        return self._process_upon_rule(rule, msg, justification, extracted_value)

    def _store_message(self, msg: QBFTMsg) -> None:
        """Store message in appropriate buffer."""
        if msg.type == MsgType.PRE_PREPARE:
            self.received_pre_prepares[msg.round] = msg
        elif msg.type == MsgType.PREPARE:
            if msg.round not in self.received_prepares:
                self.received_prepares[msg.round] = []
            # Avoid duplicates from same peer
            if not any(p.peer_idx == msg.peer_idx for p in self.received_prepares[msg.round]):
                self.received_prepares[msg.round].append(msg)
        elif msg.type == MsgType.COMMIT:
            if msg.round not in self.received_commits:
                self.received_commits[msg.round] = []
            # Avoid duplicates from same peer
            if not any(c.peer_idx == msg.peer_idx for c in self.received_commits[msg.round]):
                self.received_commits[msg.round].append(msg)
        elif msg.type == MsgType.ROUND_CHANGE:
            if msg.round not in self.received_round_changes:
                self.received_round_changes[msg.round] = []
            # Avoid duplicates from same peer
            if not any(rc.peer_idx == msg.peer_idx for rc in self.received_round_changes[msg.round]):
                self.received_round_changes[msg.round].append(msg)
        elif msg.type == MsgType.DECIDED:
            # Only store if not already decided
            if not self.is_decided():
                self.received_decided.append(msg)

    def _classify_message(self, msg: QBFTMsg) -> Tuple[UponRule, List[QBFTMsg]]:
        """Classify message and return triggered rule with justification."""
        if msg.type == MsgType.DECIDED:
            return UponRule.JUSTIFIED_DECIDED, [msg]

        elif msg.type == MsgType.PRE_PREPARE:
            # Only ignore old rounds, since PRE-PREPARE is justified we may jump ahead
            if msg.round < self.current_round:
                return UponRule.NOTHING, []
            return UponRule.JUSTIFIED_PRE_PREPARE, []

        elif msg.type == MsgType.PREPARE:
            # Ignore other rounds, since PREPARE isn't justified
            if msg.round != self.current_round:
                return UponRule.NOTHING, []

            # Check if we now have quorum prepares for this round and value
            if self.has_quorum_prepares_for_round_value(msg.round, msg.value_hash):
                prepares = self._filter_by_round_and_value(
                    self.received_prepares.get(msg.round, []),
                    msg.round,
                    msg.value_hash
                )
                return UponRule.QUORUM_PREPARES, prepares

        elif msg.type == MsgType.COMMIT:
            # Ignore other rounds, since COMMIT isn't justified
            if msg.round != self.current_round:
                return UponRule.NOTHING, []

            # Check if we now have quorum commits for this round and value
            if self.has_quorum_commits_for_round_value(msg.round, msg.value_hash):
                commits = self._filter_by_round_and_value(
                    self.received_commits.get(msg.round, []),
                    msg.round,
                    msg.value_hash
                )
                return UponRule.QUORUM_COMMITS, commits

        elif msg.type == MsgType.ROUND_CHANGE:
            # Only ignore old rounds
            if msg.round < self.current_round:
                return UponRule.NOTHING, []

            if msg.round > self.current_round:
                # Check for F+1 higher round changes
                if self._has_f_plus_1_round_changes(msg.round):
                    return UponRule.F_PLUS_1_ROUND_CHANGES, []
                return UponRule.NOTHING, []

            # msg.round == current_round
            round_changes = self.received_round_changes.get(msg.round, [])
            if len(round_changes) >= self.quorum_size:
                # Check if justified
                if self._is_justified_quorum_round_changes(round_changes):
                    return UponRule.QUORUM_ROUND_CHANGES, round_changes
                else:
                    return UponRule.UNJUST_QUORUM_ROUND_CHANGES, []

        return UponRule.NOTHING, []

    def _filter_by_round_and_value(self, msgs: List[QBFTMsg], round_num: int, value_hash: bytes) -> List[QBFTMsg]:
        """Filter messages by round and value hash, ensuring unique sources."""
        seen_sources = set()
        result = []
        for msg in msgs:
            if (msg.round == round_num and
                msg.value_hash == value_hash and
                msg.peer_idx not in seen_sources):
                seen_sources.add(msg.peer_idx)
                result.append(msg)
        return result

    def _has_f_plus_1_round_changes(self, target_round: int) -> bool:
        """Check if we have F+1 round changes for the target round or higher."""
        count = 0
        seen_sources = set()
        for round_num, msgs in self.received_round_changes.items():
            if round_num >= target_round:
                for msg in msgs:
                    if msg.peer_idx not in seen_sources:
                        seen_sources.add(msg.peer_idx)
                        count += 1
                        if count >= self.max_byzantine_faults + 1:
                            return True
        return False

    def _is_justified_quorum_round_changes(self, round_changes: List[QBFTMsg]) -> bool:
        """Check if quorum of round changes is justified."""
        # Simplified justification check - in real implementation would validate
        # that prepared rounds/values are properly justified
        return len(round_changes) >= self.quorum_size

    def _process_upon_rule(
        self,
        rule: UponRule,
        msg: QBFTMsg,
        value: Optional[Any] = None
    ) -> List[QBFTMsg]:
        """Process upon rule and return messages to send."""
        if rule == UponRule.NOTHING:
            return []

        elif rule == UponRule.JUSTIFIED_PRE_PREPARE:
            if msg.round > self.current_round:
                # Jump to higher round
                self.current_round = msg.round
                self.round_start_time = time.time()

            # Send PREPARE if we can prepare for this value
            if self.can_prepare_for_round_value(msg.round, msg.value_hash):
                self.current_value = value
                self.current_value_hash = msg.value_hash

                prepare = self.create_prepare(
                    value_hash=msg.value_hash,
                    round_num=msg.round
                )
                return [prepare]

        elif rule == UponRule.QUORUM_PREPARES:
            # Update prepared state when we reach quorum of prepares
            if msg.round > (self.prepared_round or -1):
                self.prepared_round = msg.round
                self.prepared_value = value  # Use the value if provided
                self.prepared_value_hash = msg.value_hash

            # Send COMMIT if we can commit for this value
            if self.can_commit_for_round_value(msg.round, msg.value_hash):
                commit = self.create_commit(
                    value_hash=msg.value_hash,
                    round_num=msg.round,
                    prepared_round=msg.round
                )
                return [commit]

        elif rule == UponRule.QUORUM_COMMITS:
            # Mark as decided when we have quorum commits (even if already decided)
            if self.has_quorum_commits_for_round_value(msg.round, msg.value_hash):
                if not self.is_decided():
                    decided = self.create_decided(
                        value_hash=msg.value_hash,
                        round_num=msg.round
                    )
                    # Mark ourselves as decided by storing our own DECIDED message
                    self.received_decided.append(decided)
                    return [decided]
                else:
                    # Already decided, but we still need to mark this state
                    # (in case we received commits after being decided by other means)
                    pass

        elif rule == UponRule.F_PLUS_1_ROUND_CHANGES:
            # Jump to higher round when we see F+1 round changes
            highest_round = max(
                round_num for round_num in self.received_round_changes.keys()
                if round_num > self.current_round
            )
            if highest_round > self.current_round:
                self.current_round = highest_round
                self.round_start_time = time.time()

                round_change = self.create_round_change(
                    new_round=self.current_round
                )
                return [round_change]

        elif rule == UponRule.QUORUM_ROUND_CHANGES:
            # Start new round
            if msg.round >= self.current_round:
                self.current_round = msg.round
                self.round_start_time = time.time()

                # If we're the leader, send PRE-PREPARE
                if self.compute_leader(self.current_round) == self.peer_idx:
                    value, value_hash = self._determine_proposal_value(self.current_round)
                    preprepare = self.create_pre_prepare(
                        value=value,
                        value_hash=value_hash,
                        round_num=self.current_round
                    )
                    return [preprepare]

        elif rule == UponRule.UNJUST_QUORUM_ROUND_CHANGES:
            pass

        elif rule == UponRule.JUSTIFIED_DECIDED:
            # Accept justified decided message - mark consensus as complete
            if not self.is_decided():
                # Store the received DECIDED message to mark ourselves as decided
                self.received_decided.append(msg)
            # Consensus is complete - no further messages needed

        return []

    def _determine_proposal_value(self, round_num: int) -> Tuple[Any, bytes]:
        """Determine value to propose"""
        # Step 1: Find the highest prepared round from round change messages
        highest_prepared_round = -1
        highest_prepared_value = None
        highest_prepared_value_hash = None

        # Check round change messages for prepared values
        for rc_round, round_changes in self.received_round_changes.items():
            if rc_round <= round_num:  # Only consider round changes for current or past rounds
                for rc_msg in round_changes:
                    if (rc_msg.prepared_round is not None and
                        rc_msg.prepared_value_hash is not None and
                        rc_msg.prepared_round > highest_prepared_round):

                        highest_prepared_round = rc_msg.prepared_round
                        highest_prepared_value_hash = rc_msg.prepared_value_hash
                        # TODO find real value
                        highest_prepared_value = f"prepared_value_round_{rc_msg.prepared_round}".encode()

        # Step 2: Check our own prepared state
        if (self.prepared_round is not None and
            self.prepared_value_hash is not None and
            self.prepared_round > highest_prepared_round):

            highest_prepared_round = self.prepared_round
            highest_prepared_value = self.prepared_value
            highest_prepared_value_hash = self.prepared_value_hash

        # Step 3: Return the highest prepared value or propose new value
        if highest_prepared_value is not None:
            return highest_prepared_value, highest_prepared_value_hash

        # Step 4: No prepared values found, propose our own value
        if self.proposal_value is not None and self.proposal_value_hash is not None:
            return self.proposal_value, self.proposal_value_hash

        # TODO get real value
        new_value = f"new_proposal_round_{round_num}".encode()
        new_value_hash = self._compute_value_hash(new_value)
        return new_value, new_value_hash

    def _compute_value_hash(self, value: Any) -> bytes:
        """Compute a mock 32-byte hash for the given value."""
        if isinstance(value, bytes):
            value_str = value.decode('utf-8', errors='ignore')
        else:
            value_str = str(value)

        # TODO
        hash_input = value_str.encode('utf-8')
        hash_bytes = hash_input[:32] if len(hash_input) >= 32 else hash_input
        return hash_bytes.ljust(32, b'\x00')

    def set_proposal_value(self, value: Any) -> None:
        """Set the value this node wants to propose when it becomes leader."""
        self.proposal_value = value
        self.proposal_value_hash = self._compute_value_hash(value)

    def create_pre_prepare(self, value: Any, value_hash: bytes, round_num: int) -> QBFTMsg:
        """Create a PRE_PREPARE message."""
        return QBFTMsg(
            type=MsgType.PRE_PREPARE,
            duty=self.duty,
            peer_idx=self.peer_idx,
            round=round_num,
            prepared_round=None,
            signature=self._sign_message(round_num, value_hash),
            value_hash=value_hash,
            prepared_value_hash=None
        )

    def create_prepare(self, value_hash: bytes, round_num: int) -> QBFTMsg:
        """Create a PREPARE message."""
        return QBFTMsg(
            type=MsgType.PREPARE,
            duty=self.duty,
            peer_idx=self.peer_idx,
            round=round_num,
            prepared_round=None,
            signature=self._sign_message(round_num, value_hash),
            value_hash=value_hash,
            prepared_value_hash=None
        )

    def create_commit(self, value_hash: bytes, round_num: int, prepared_round: int) -> QBFTMsg:
        """Create a COMMIT message."""
        return QBFTMsg(
            type=MsgType.COMMIT,
            duty=self.duty,
            peer_idx=self.peer_idx,
            round=round_num,
            prepared_round=prepared_round,
            signature=self._sign_message(round_num, value_hash),
            value_hash=value_hash,
            prepared_value_hash=value_hash
        )

    def create_round_change(
        self,
        new_round: int,
        prepared_round: Optional[int] = None,
        prepared_value_hash: Optional[bytes] = None
    ) -> QBFTMsg:
        """Create a ROUND_CHANGE message."""
        return QBFTMsg(
            type=MsgType.ROUND_CHANGE,
            duty=self.duty,
            peer_idx=self.peer_idx,
            round=new_round,
            prepared_round=prepared_round,
            signature=self._sign_message(new_round, prepared_value_hash or b""),
            value_hash=b"\x00" * 32,  # No specific value in round change
            prepared_value_hash=prepared_value_hash
        )

    def create_decided(self, value_hash: bytes, round_num: int) -> QBFTMsg:
        """Create a DECIDED message."""
        return QBFTMsg(
            type=MsgType.DECIDED,
            duty=self.duty,
            peer_idx=self.peer_idx,
            round=round_num,
            prepared_round=round_num,
            signature=self._sign_message(round_num, value_hash),
            value_hash=value_hash,
            prepared_value_hash=value_hash
        )

    def _sign_message(self, round_num: int, value_hash: bytes) -> bytes:
        """Create a mock signature for a message."""
        # TODO
        # In real implementation, this would use proper cryptographic signing
        signature_data = f"{self.duty.slot}_{self.duty.type}_{round_num}_{value_hash.hex()}"
        signature_bytes = signature_data.encode()[:65]
        return signature_bytes.ljust(65, b'\x00')

    def check_timeout(self) -> Optional[QBFTMsg]:
        """Check for round timeout and create round change if needed."""
        if self.is_decided():
            return None

        current_time = time.time()
        elapsed = current_time - self.round_start_time
        timeout = self.timer.calculate_timeout(self.current_round)

        if elapsed > timeout:
            # Create round change for next round
            next_round = self.current_round + 1
            round_change = self.create_round_change(
                new_round=next_round,
                prepared_round=self.prepared_round,
                prepared_value_hash=self.prepared_value_hash
            )

            # Update to new round
            self.current_round = next_round
            self.round_start_time = current_time

            return round_change

        return None
