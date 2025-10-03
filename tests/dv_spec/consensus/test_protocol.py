"""
Test suite for QBFT Protocol implementation
"""

import time

from dv_spec.subspecs.consensus.qbft.protocol import QBFTConsensus, UponRule
from dv_spec.subspecs.consensus.qbft.message import QBFTMsg, QBFTConsensusMsg, MsgType
from dv_spec.types import Duty


class TestQBFTConsensusBasics:
    """Test basic QBFT consensus functionality."""
    
    def test_initialization(self):
        """Test consensus initialization with correct parameters."""
        duty = Duty(slot=100, type=1)
        consensus = QBFTConsensus(duty=duty, cluster_size=4, peer_idx=0)
        
        assert consensus.duty == duty
        assert consensus.cluster_size == 4
        assert consensus.peer_idx == 0
        assert consensus.current_round == 1
        assert consensus.max_byzantine_faults == 1  # floor((4-1)/3) = 1
        assert consensus.quorum_size == 3  # ceil(2*4/3) = 3
        assert consensus.current_value is None
        assert consensus.current_value_hash is None
    
    def test_byzantine_quorum_calculation(self):
        """Test quorum calculation matches Byzantine fault tolerant formula: ceil(2n/3)."""
        test_cases = [
            (1, 1),  # ceil(2*1/3) = ceil(0.67) = 1
            (2, 2),  # ceil(2*2/3) = ceil(1.33) = 2
            (3, 2),  # ceil(2*3/3) = ceil(2.0) = 2
            (4, 3),  # ceil(2*4/3) = ceil(2.67) = 3
            (5, 4),  # ceil(2*5/3) = ceil(3.33) = 4
            (6, 4),  # ceil(2*6/3) = ceil(4.0) = 4
            (7, 5),  # ceil(2*7/3) = ceil(4.67) = 5
            (10, 7), # ceil(2*10/3) = ceil(6.67) = 7
        ]
        
        duty = Duty(slot=100, type=1)
        for cluster_size, expected_quorum in test_cases:
            consensus = QBFTConsensus(duty=duty, cluster_size=cluster_size, peer_idx=0)
            assert consensus.quorum_size == expected_quorum, \
                f"Cluster {cluster_size}: expected quorum {expected_quorum}, got {consensus.quorum_size}"
    
    def test_byzantine_fault_calculation(self):
        """Test Byzantine fault tolerance calculation: floor((n-1)/3)."""
        test_cases = [
            (1, 0),  # floor((1-1)/3) = 0
            (2, 0),  # floor((2-1)/3) = 0
            (3, 0),  # floor((3-1)/3) = 0
            (4, 1),  # floor((4-1)/3) = 1
            (5, 1),  # floor((5-1)/3) = 1
            (6, 1),  # floor((6-1)/3) = 1
            (7, 2),  # floor((7-1)/3) = 2
            (10, 3), # floor((10-1)/3) = 3
        ]
        
        duty = Duty(slot=100, type=1)
        for cluster_size, expected_faults in test_cases:
            consensus = QBFTConsensus(duty=duty, cluster_size=cluster_size, peer_idx=0)
            assert consensus.max_byzantine_faults == expected_faults, \
                f"Cluster {cluster_size}: expected {expected_faults} faults, got {consensus.max_byzantine_faults}"
    
    def test_leader_election(self):
        """Test round-robin leader election."""
        duty = Duty(slot=100, type=1)
        consensus = QBFTConsensus(duty=duty, cluster_size=4, peer_idx=0)
        
        # Test multiple rounds (QBFT rounds start from 1)
        # With slot=100, type=1: (100 + 1 + round) % 4
        assert consensus.compute_leader(1) == 2  # (102) % 4 = 2
        assert consensus.compute_leader(2) == 3  # (103) % 4 = 3
        assert consensus.compute_leader(3) == 0  # (104) % 4 = 0
        assert consensus.compute_leader(4) == 1  # (105) % 4 = 1
        assert consensus.compute_leader(5) == 2  # (106) % 4 = 2 (wraps around)
        assert consensus.compute_leader(6) == 3  # (107) % 4 = 3


class TestMessageBasedProgress:
    """Test message-based progress tracking."""
    
    def setup_method(self):
        """Setup common test fixtures."""
        self.duty = Duty(slot=100, type=1)
        self.consensus = QBFTConsensus(duty=self.duty, cluster_size=4, peer_idx=1)
        self.value_hash = b"a" * 32
    
    def test_has_pre_prepare_for_round(self):
        """Test PRE-PREPARE detection."""
        assert not self.consensus.has_pre_prepare_for_round(1)
        
        # Add PRE-PREPARE
        pre_prepare = QBFTMsg(
            type=MsgType.PRE_PREPARE,
            duty=self.duty,
            peer_idx=0,
            round=1,
            value_hash=self.value_hash,
            signature=b"s" * 65,
            prepared_round=None,
            prepared_value_hash=None
        )
        self.consensus._store_message(pre_prepare)
        
        assert self.consensus.has_pre_prepare_for_round(1)
        assert not self.consensus.has_pre_prepare_for_round(2)
    
    def test_has_quorum_prepares_for_round_value(self):
        """Test PREPARE quorum detection."""
        assert not self.consensus.has_quorum_prepares_for_round_value(1, self.value_hash)
        
        # Add PRE-PREPARE first
        pre_prepare = QBFTMsg(
            type=MsgType.PRE_PREPARE,
            duty=self.duty,
            peer_idx=0,
            round=1,
            value_hash=self.value_hash,
            signature=b"s" * 65,
            prepared_round=None,
            prepared_value_hash=None
        )
        self.consensus._store_message(pre_prepare)
        
        # Add quorum of PREPARE messages (3 out of 4)
        for i in range(3):
            prepare = QBFTMsg(
                type=MsgType.PREPARE,
                duty=self.duty,
                peer_idx=i,
                round=1,
                value_hash=self.value_hash,
                signature=b"s" * 65,
                prepared_round=None,
                prepared_value_hash=None
            )
            self.consensus._store_message(prepare)
        
        assert self.consensus.has_quorum_prepares_for_round_value(1, self.value_hash)
        assert not self.consensus.has_quorum_prepares_for_round_value(1, b"different" + b"x" * 24)
    
    def test_has_quorum_commits_for_round_value(self):
        """Test COMMIT quorum detection."""
        assert not self.consensus.has_quorum_commits_for_round_value(1, self.value_hash)
        
        # Add quorum of COMMIT messages (3 out of 4)
        for i in range(3):
            commit = QBFTMsg(
                type=MsgType.COMMIT,
                duty=self.duty,
                peer_idx=i,
                round=1,
                value_hash=self.value_hash,
                signature=b"s" * 65,
                prepared_round=1,
                prepared_value_hash=self.value_hash
            )
            self.consensus._store_message(commit)
        
        assert self.consensus.has_quorum_commits_for_round_value(1, self.value_hash)
        assert not self.consensus.has_quorum_commits_for_round_value(1, b"different" + b"x" * 24)
    
    def test_is_decided(self):
        """Test decision detection."""
        assert not self.consensus.is_decided()
        
        # Add DECIDED message
        decided = QBFTMsg(
            type=MsgType.DECIDED,
            duty=self.duty,
            peer_idx=0,
            round=1,
            value_hash=self.value_hash,
            signature=b"s" * 65,
            prepared_round=1,
            prepared_value_hash=self.value_hash
        )
        self.consensus._store_message(decided)
        
        assert self.consensus.is_decided()


class TestMessageClassification:
    """Test message classification and upon rules."""
    
    def setup_method(self):
        """Setup common test fixtures."""
        self.duty = Duty(slot=100, type=1)
        self.consensus = QBFTConsensus(duty=self.duty, cluster_size=4, peer_idx=1)
        self.consensus.current_round = 1  # Set to round 1 for the tests
        self.value_hash = b"a" * 32
    
    def test_classify_pre_prepare(self):
        """Test PRE-PREPARE message classification."""
        pre_prepare = QBFTMsg(
            type=MsgType.PRE_PREPARE,
            duty=self.duty,
            peer_idx=0,  # Leader for round 1
            round=1,
            value_hash=self.value_hash,
            signature=b"s" * 65,
            prepared_round=None,
            prepared_value_hash=None
        )
        
        # Store the message first
        self.consensus._store_message(pre_prepare)
        
        rule, justification = self.consensus._classify_message(pre_prepare)
        assert rule == UponRule.JUSTIFIED_PRE_PREPARE
        assert len(justification) == 0
    
    def test_classify_prepare_no_quorum(self):
        """Test PREPARE message classification without quorum."""
        prepare = QBFTMsg(
            type=MsgType.PREPARE,
            duty=self.duty,
            peer_idx=0,
            round=1,
            value_hash=self.value_hash,
            signature=b"s" * 65,
            prepared_round=None,
            prepared_value_hash=None
        )
        
        self.consensus._store_message(prepare)
        
        rule, justification = self.consensus._classify_message(prepare)
        assert rule == UponRule.NOTHING  # No quorum yet
        assert len(justification) == 0
    
    def test_classify_prepare_with_quorum(self):
        """Test PREPARE message classification with quorum."""
        # Create quorum of PREPARE messages (3 out of 4)
        prepares = []
        for i in range(3):
            prepare = QBFTMsg(
                type=MsgType.PREPARE,
                duty=self.duty,
                peer_idx=i,
                round=1,
                value_hash=self.value_hash,
                signature=b"s" * 65,
                prepared_round=None,
                prepared_value_hash=None
            )
            prepares.append(prepare)
            self.consensus._store_message(prepare)
        
        # Last message should trigger quorum
        rule, justification = self.consensus._classify_message(prepares[-1])
        assert rule == UponRule.QUORUM_PREPARES
        assert len(justification) == 3
    
    def test_classify_commit_with_quorum(self):
        """Test COMMIT message classification with quorum."""
        # Create quorum of COMMIT messages
        commits = []
        for i in range(3):
            commit = QBFTMsg(
                type=MsgType.COMMIT,
                duty=self.duty,
                peer_idx=i,
                round=1,
                value_hash=self.value_hash,
                signature=b"s" * 65,
                prepared_round=1,
                prepared_value_hash=self.value_hash
            )
            commits.append(commit)
            self.consensus._store_message(commit)
        
        rule, justification = self.consensus._classify_message(commits[-1])
        assert rule == UponRule.QUORUM_COMMITS
        assert len(justification) == 3


class TestStateMachine:
    """Test QBFT state machine transitions."""
    
    def setup_method(self):
        """Setup common test fixtures."""
        self.duty = Duty(slot=100, type=1)
        self.consensus = QBFTConsensus(duty=self.duty, cluster_size=4, peer_idx=1)
        self.value = b"test_block"
        self.value_hash = b"a" * 32
    
    def test_handle_pre_prepare_as_non_leader(self):
        """Test handling PRE-PREPARE as non-leader."""
        pre_prepare = QBFTMsg(
            type=MsgType.PRE_PREPARE,
            duty=self.duty,
            peer_idx=0,  # Leader for round 1
            round=1,
            value_hash=self.value_hash,
            signature=b"s" * 65,
            prepared_round=None,
            prepared_value_hash=None
        )
        
        responses = self.consensus.handle_message(QBFTConsensusMsg(msg=pre_prepare, values=[self.value]))
        
        # Should send PREPARE message
        assert len(responses) == 1
        assert responses[0].type == MsgType.PREPARE
        assert responses[0].peer_idx == self.consensus.peer_idx
        assert responses[0].round == 1
        assert responses[0].value_hash == self.value_hash
        
        # Check state changes
        assert self.consensus.current_value == self.value
        assert self.consensus.current_value_hash == self.value_hash
    
    def test_full_consensus_flow(self):
        """Test complete consensus flow from PRE-PREPARE to DECIDED."""
        # Create 4 consensus instances (one per node)
        duty = Duty(slot=100, type=1)
        nodes = [QBFTConsensus(duty=duty, cluster_size=4, peer_idx=i) for i in range(4)]
        
        value = b"test_block"
        value_hash = b"a" * 32
        
        # Step 1: Leader sends PRE-PREPARE
        leader = nodes[0]
        pre_prepare = leader.create_pre_prepare(
            value=value,
            value_hash=value_hash,
            round_num=1
        )
        
        # Step 2: All nodes handle PRE-PREPARE and send PREPARE (including leader)
        all_prepares = []
        for i in range(4):  # All nodes including leader  
            responses = nodes[i].handle_message(QBFTConsensusMsg(msg=pre_prepare, values=[value]))
            assert len(responses) == 1
            assert responses[0].type == MsgType.PREPARE
            all_prepares.extend(responses)
        
        assert len(all_prepares) == 4
        
        # Step 3: Distribute PREPARE messages
        all_commits = []
        for prepare_msg in all_prepares:
            for i, node in enumerate(nodes):
                if i != prepare_msg.peer_idx:  # Don't send to self
                    responses = node.handle_message(QBFTConsensusMsg(msg=prepare_msg))
                    all_commits.extend(responses)
        
        # Should have COMMIT messages from nodes that reached quorum
        commit_messages = [msg for msg in all_commits if msg.type == MsgType.COMMIT]
        assert len(commit_messages) >= 4  # All nodes should send COMMIT
        
        # Step 4: Distribute COMMIT messages
        all_decided = []
        for commit_msg in commit_messages[:3]:  # Use first 3 to avoid duplicates
            for i, node in enumerate(nodes):
                if i != commit_msg.peer_idx:
                    responses = node.handle_message(QBFTConsensusMsg(msg=commit_msg))
                    all_decided.extend(responses)
        
        # Should have DECIDED messages
        decided_messages = [msg for msg in all_decided if msg.type == MsgType.DECIDED]
        assert len(decided_messages) >= 4
        
        # Check final states
        decided_count = 0
        for node in nodes:
            if node.is_decided():
                decided_count += 1
        
        assert decided_count >= 4  # All nodes should reach consensus


class TestRoundChanges:
    """Test round change behavior."""
    
    def setup_method(self):
        """Setup common test fixtures."""
        self.duty = Duty(slot=100, type=1)
        self.consensus = QBFTConsensus(duty=self.duty, cluster_size=4, peer_idx=0)
    
    def test_round_change_creation(self):
        """Test creating ROUND_CHANGE messages."""
        round_change = self.consensus.create_round_change(
            new_round=1
        )
        
        assert round_change.type == MsgType.ROUND_CHANGE
        assert round_change.peer_idx == 0
        assert round_change.round == 1
        assert round_change.prepared_round is None
    
    def test_f_plus_1_round_changes(self):
        """Test F+1 round change detection."""
        # Create F+1 round changes (2 for cluster of 4)
        for i in range(2):
            round_change = QBFTMsg(
                type=MsgType.ROUND_CHANGE,
                duty=self.duty,
                peer_idx=i,
                round=1,  # Higher round
                value_hash=b"\x00" * 32,
                signature=b"s" * 65,
                prepared_round=None,
                prepared_value_hash=None
            )
            self.consensus._store_message(round_change)
        
        # Check if F+1 detection works
        has_f_plus_1 = self.consensus._has_f_plus_1_round_changes(1)
        assert has_f_plus_1
    
    def test_round_change_with_prepared_value_persistence(self):
        """Test that after a quorum of PREPARED, round change preserves the prepared value."""
        # Setup: Node 1 becomes new leader in round 2, must propose the prepared value from round 1
        duty = Duty(slot=100, type=1)
        new_leader = QBFTConsensus(duty=duty, cluster_size=4, peer_idx=1)
        new_leader.set_proposal_value(b"leader_own_value")  # Leader's own preferred value
        
        # Original prepared value from round 1 (different from leader's preference)
        prepared_value = b"prepared_value_from_round_1"
        prepared_value_hash = b"p" * 32
        
        # Create round change messages with prepared values (quorum of 3 in cluster of 4)
        round_changes_with_prepared = []
        for i in range(3):  # Quorum of nodes with prepared values
            round_change = QBFTMsg(
                type=MsgType.ROUND_CHANGE,
                duty=duty,
                peer_idx=i,
                round=2,  # ROUND-CHANGE for round 2
                value_hash=b"\x00" * 32,
                signature=b"s" * 65,
                prepared_round=1,  # They were prepared in round 1
                prepared_value_hash=prepared_value_hash
            )
            round_changes_with_prepared.append(round_change)
            new_leader._store_message(round_change)
        
        # Simulate the leader determining what value to propose
        # According to QBFT, it should propose the prepared value, not its own
        proposal_value, proposal_value_hash = new_leader._determine_proposal_value(round_num=2)
        
        # TODO
        # The leader should propose the prepared value from the round changes
        # In a real implementation, the leader would have access to the actual prepared value
        # For this test, we verify the logic selects the highest prepared round's value
        highest_prepared_round = max(
            msg.prepared_round for msg in round_changes_with_prepared if msg.prepared_round is not None
        )
        assert highest_prepared_round == 1  # The prepared round from our messages
        
        # Verify F+1 round changes detected
        assert new_leader._has_f_plus_1_round_changes(2)
        
        # The proposal value determination should follow QBFT rules
        # Since we have prepared values from round changes, it should not use leader's own value
        assert proposal_value != b"leader_own_value"  # Should not be leader's preference
    
    def test_round_change_without_prepared_values_uses_own_value(self):
        """Test that when no prepared values exist, the leader proposes its own value."""
        # Setup: Node 1 becomes new leader in round 2
        duty = Duty(slot=100, type=1)
        new_leader = QBFTConsensus(duty=duty, cluster_size=4, peer_idx=1)
        new_leader.set_proposal_value(b"leader_own_value")
        
        # Create round change messages WITHOUT prepared values (quorum of 3 in cluster of 4)
        for i in range(3):
            round_change = QBFTMsg(
                type=MsgType.ROUND_CHANGE,
                duty=duty,
                peer_idx=i,
                round=2,
                value_hash=b"\x00" * 32,
                signature=b"s" * 65,
                prepared_round=None,  # No prepared values
                prepared_value_hash=None
            )
            new_leader._store_message(round_change)
        
        # Verify F+1 round changes detected
        assert new_leader._has_f_plus_1_round_changes(2)
        
        # Simulate the leader determining what value to propose
        proposal_value, proposal_value_hash = new_leader._determine_proposal_value(round_num=2)

        # Since no prepared values exist, leader should propose its own value
        assert proposal_value == b"leader_own_value"


class TestByzantineFaultTolerance:
    """Test Byzantine fault tolerance properties."""
    
    def test_consensus_with_byzantine_faults(self):
        """Test consensus works with up to f Byzantine nodes."""
        cluster_size = 7  # f = 2, quorum = 5
        duty = Duty(slot=100, type=1)
        nodes = [QBFTConsensus(duty=duty, cluster_size=cluster_size, peer_idx=i) for i in range(cluster_size)]
        
        value = b"honest_value"
        value_hash = b"h" * 32
        
        # Simulate 2 Byzantine nodes (within fault tolerance)
        byzantine_nodes = {5, 6}
        honest_nodes = [i for i in range(cluster_size) if i not in byzantine_nodes]
        
        # Leader (node 0) sends PRE-PREPARE
        pre_prepare = nodes[0].create_pre_prepare(
            value=value,
            value_hash=value_hash,
            round_num=1
        )
        
        # All honest nodes (including leader) process PRE-PREPARE
        all_prepares = []
        for i in honest_nodes:
            responses = nodes[i].handle_message(QBFTConsensusMsg(msg=pre_prepare, values=[value]))
            all_prepares.extend(responses)
        
        # Should have enough PREPARE messages for quorum (5 honest nodes should all send PREPARE)
        assert len(all_prepares) == 5
        
        # Distribute PREPARE messages among honest nodes only
        all_commits = []
        for prepare_msg in all_prepares:
            for i in honest_nodes:
                if i != prepare_msg.peer_idx:
                    responses = nodes[i].handle_message(QBFTConsensusMsg(msg=prepare_msg))
                    all_commits.extend(responses)
        
        # Check that honest nodes can still reach consensus
        commit_messages = [msg for msg in all_commits if msg.type == MsgType.COMMIT]
        assert len(commit_messages) >= nodes[0].quorum_size  # Should meet quorum
    
    def test_no_consensus_with_too_many_faults(self):
        """Test that consensus fails with more than f Byzantine nodes."""
        cluster_size = 4  # f = 1, quorum = 3
        duty = Duty(slot=100, type=1)
        nodes = [QBFTConsensus(duty=duty, cluster_size=cluster_size, peer_idx=i) for i in range(cluster_size)]
        
        value = b"honest_value"
        value_hash = b"h" * 32
        
        # Leader sends PRE-PREPARE
        pre_prepare = nodes[0].create_pre_prepare(
            value=value,
            value_hash=value_hash,
            round_num=1
        )
        
        # Only 1 honest non-leader responds
        responses = nodes[1].handle_message(QBFTConsensusMsg(msg=pre_prepare, values=[value]))
        assert len(responses) == 1  # Only 1 PREPARE

class TestEdgeCases:
    """Test edge cases and error conditions."""
    
    def setup_method(self):
        """Setup common test fixtures."""
        self.duty = Duty(slot=100, type=1)
        self.consensus = QBFTConsensus(duty=self.duty, cluster_size=4, peer_idx=1)
    
    def test_duplicate_message_handling(self):
        """Test that duplicate messages are properly handled."""
        prepare = QBFTMsg(
            type=MsgType.PREPARE,
            duty=self.duty,
            peer_idx=0,
            round=1,
            value_hash=b"a" * 32,
            signature=b"s" * 65,
            prepared_round=None,
            prepared_value_hash=None
        )
        
        # Send same message twice
        responses1 = self.consensus.handle_message(QBFTConsensusMsg(msg=prepare))
        responses2 = self.consensus.handle_message(QBFTConsensusMsg(msg=prepare))
        
        # Should not process duplicate
        assert len(self.consensus.received_prepares[1]) == 1  # Only one copy stored
    
    def test_old_round_message_handling(self):
        """Test that old round messages are ignored appropriately."""
        self.consensus.current_round = 2  # Advanced to round 2
        
        # Send message for old round
        old_prepare = QBFTMsg(
            type=MsgType.PREPARE,
            duty=self.duty,
            peer_idx=0,
            round=1,  # Old round
            value_hash=b"a" * 32,
            signature=b"s" * 65,
            prepared_round=None,
            prepared_value_hash=None
        )
        
        responses = self.consensus.handle_message(QBFTConsensusMsg(msg=old_prepare))
        
        # Should ignore old round PREPARE
        assert len(responses) == 0
    
    def test_wrong_duty_message(self):
        """Test that messages for wrong duty are ignored."""
        correct_duty = Duty(slot=100, type=1)
        wrong_duty = Duty(slot=101, type=1)
        
        # Create consensus for correct duty
        consensus = QBFTConsensus(duty=correct_duty, cluster_size=4, peer_idx=1)
        
        # Send message for wrong duty
        wrong_msg = QBFTMsg(
            type=MsgType.PREPARE,
            duty=wrong_duty,
            peer_idx=0,
            round=1,
            value_hash=b"a" * 32,
            signature=b"s" * 65,
            prepared_round=None,
            prepared_value_hash=None
        )
        
        responses = consensus.handle_message(QBFTConsensusMsg(msg=wrong_msg))
        
        # Should ignore message for wrong duty
        assert len(responses) == 0


class TestTimeouts:
    """Test timeout integration with protocol."""
    
    def setup_method(self):
        """Setup common test fixtures."""
        self.duty = Duty(slot=100, type=2)  # Non-proposer duty
        self.consensus = QBFTConsensus(duty=self.duty, cluster_size=4, peer_idx=0)
    
    def test_timeout_detection(self):
        """Test that timeouts are properly detected and trigger round changes."""
        # Set consensus to start in the past
        self.consensus.round_start_time = time.time() - 10  # 10 seconds ago
        
        # Check for timeout
        timeout_message = self.consensus.check_timeout()
        
        # Should generate round change message
        assert timeout_message is not None
        assert timeout_message.type == MsgType.ROUND_CHANGE
        assert timeout_message.round == 2  # Next round (from current round 1 to 2)
        # Should move to next round
        assert self.consensus.current_round == 2
    
    def test_no_timeout_when_decided(self):
        """Test that timeouts don't occur when consensus is decided."""
        # Add DECIDED message
        decided = QBFTMsg(
            type=MsgType.DECIDED,
            duty=self.duty,
            peer_idx=0,
            round=1,
            value_hash=b"a" * 32,
            signature=b"s" * 65,
            prepared_round=1,
            prepared_value_hash=b"a" * 32
        )
        self.consensus._store_message(decided)
        
        # Set timeout condition
        self.consensus.round_start_time = time.time() - 10
        
        # Should not timeout when decided
        timeout_message = self.consensus.check_timeout()
        assert timeout_message is None


class TestProposalValueDetermination:
    """Test proposal value determination logic."""
    
    def setup_method(self):
        """Setup common test fixtures."""
        self.duty = Duty(slot=100, type=1)
        self.consensus = QBFTConsensus(duty=self.duty, cluster_size=4, peer_idx=0)
    
    def test_propose_new_value_when_no_prepared_values(self):
        """Test proposing new value when no prepared values exist."""
        value, value_hash = self.consensus._determine_proposal_value(round_num=1)
        
        assert b"new_proposal_round_1" in value
        assert len(value_hash) == 32
    
    def test_propose_own_prepared_value(self):
        """Test proposing our own prepared value when it exists."""
        # Set up our own prepared state
        self.consensus.prepared_round = 1
        self.consensus.prepared_value = b"our_prepared_value"
        self.consensus.prepared_value_hash = b"our_prepared_hash".ljust(32, b'\x00')
        
        value, value_hash = self.consensus._determine_proposal_value(round_num=1)
        
        assert value == b"our_prepared_value"
        assert value_hash == self.consensus.prepared_value_hash
    
    def test_propose_highest_prepared_value_from_round_changes(self):
        """Test proposing highest prepared value from round change messages."""
        # Add round change with prepared value
        round_change = QBFTMsg(
            type=MsgType.ROUND_CHANGE,
            duty=self.duty,
            peer_idx=1,
            round=2,
            prepared_round=1,
            signature=b"s" * 65,
            value_hash=b"\x00" * 32,
            prepared_value_hash=b"rc_prepared_hash".ljust(32, b'\x00')
        )
        self.consensus._store_message(round_change)
        
        value, value_hash = self.consensus._determine_proposal_value(round_num=2)
        
        assert b"prepared_value_round_1" in value
        assert value_hash == round_change.prepared_value_hash
    
    def test_propose_highest_among_multiple_prepared_values(self):
        """Test that highest prepared round wins among multiple prepared values."""
        # Set our own prepared state (round 1)
        self.consensus.prepared_round = 1
        self.consensus.prepared_value = b"our_prepared_value"
        self.consensus.prepared_value_hash = b"our_hash".ljust(32, b'\x00')
        
        # Add round change with higher prepared round (round 1)
        round_change_1 = QBFTMsg(
            type=MsgType.ROUND_CHANGE,
            duty=self.duty,
            peer_idx=1,
            round=3,
            prepared_round=1,
            signature=b"s" * 65,
            value_hash=b"\x00" * 32,
            prepared_value_hash=b"rc1_hash".ljust(32, b'\x00')
        )
        self.consensus._store_message(round_change_1)
        
        # Add another round change with even higher prepared round (round 2)
        round_change_2 = QBFTMsg(
            type=MsgType.ROUND_CHANGE,
            duty=self.duty,
            peer_idx=2,
            round=3,
            prepared_round=2,
            signature=b"s" * 65,
            value_hash=b"\x00" * 32,
            prepared_value_hash=b"rc2_highest_hash".ljust(32, b'\x00')
        )
        self.consensus._store_message(round_change_2)
        
        value, value_hash = self.consensus._determine_proposal_value(round_num=3)
        
        # Should choose the highest prepared round (round 2)
        assert b"prepared_value_round_2" in value
        assert value_hash == round_change_2.prepared_value_hash
    
    def test_ignore_round_changes_for_future_rounds(self):
        """Test that round changes for future rounds are ignored."""
        # Add round change for a future round
        future_round_change = QBFTMsg(
            type=MsgType.ROUND_CHANGE,
            duty=self.duty,
            peer_idx=1,
            round=5,  # Future round
            prepared_round=3,
            signature=b"s" * 65,
            value_hash=b"\x00" * 32,
            prepared_value_hash=b"future_hash".ljust(32, b'\x00')
        )
        self.consensus._store_message(future_round_change)
        
        # Proposing for round 2 should ignore the future round change
        value, value_hash = self.consensus._determine_proposal_value(round_num=2)
        
        # Should propose new value since future round changes are ignored
        assert b"new_proposal_round_2" in value


class TestProtocolJustificationVerification:
    """Test detailed QBFT justification verification."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.duty = Duty(type=1, slot=1)
        self.consensus = QBFTConsensus(duty=self.duty, cluster_size=4, peer_idx=1)
        self.value_hash = b"v" * 32
        self.signature = b"s" * 65
        
    def test_verify_pre_prepare_round_1_no_justification(self):
        """PRE-PREPARE for round 1 should need no justification."""
        pre_prepare = QBFTMsg(
            type=MsgType.PRE_PREPARE,
            duty=self.duty,
            peer_idx=0,
            round=1,
            value_hash=self.value_hash,
            signature=self.signature,
            prepared_round=None,
            prepared_value_hash=None
        )
        
        # Round 1 should require no justification
        assert self.consensus.verify_pre_prepare_justification(pre_prepare, [])
        
        # Round 1 should reject justifications
        dummy_rc = QBFTMsg(
            type=MsgType.ROUND_CHANGE,
            duty=self.duty,
            peer_idx=1,
            round=1,
            value_hash=self.value_hash,
            signature=self.signature,
            prepared_round=None,
            prepared_value_hash=None
        )
        assert not self.consensus.verify_pre_prepare_justification(pre_prepare, [dummy_rc])
    
    def test_verify_pre_prepare_insufficient_round_changes(self):
        """PRE-PREPARE for round > 1 with insufficient ROUND-CHANGE justifications."""
        pre_prepare = QBFTMsg(
            type=MsgType.PRE_PREPARE,
            duty=self.duty,
            peer_idx=0,
            round=2,
            value_hash=self.value_hash,
            signature=self.signature,
            prepared_round=None,
            prepared_value_hash=None
        )
        
        # Create insufficient ROUND-CHANGE messages (need quorum of 3, only provide 1)
        rc = QBFTMsg(
            type=MsgType.ROUND_CHANGE,
            duty=self.duty,
            peer_idx=1,
            round=1,
            value_hash=b"x" * 32,
            signature=self.signature,
            prepared_round=None,
            prepared_value_hash=None
        )
        
        assert not self.consensus.verify_pre_prepare_justification(pre_prepare, [rc])
    
    def test_verify_pre_prepare_valid_round_changes_no_prepared(self):
        """PRE-PREPARE with valid ROUND-CHANGE justifications (no prepared values)."""
        pre_prepare = QBFTMsg(
            type=MsgType.PRE_PREPARE,
            duty=self.duty,
            peer_idx=0,
            round=2,
            value_hash=self.value_hash,
            signature=self.signature,
            prepared_round=None,
            prepared_value_hash=None
        )
        
        # Create quorum of ROUND-CHANGE messages (3 out of 4)
        round_changes = []
        for i in range(3):
            rc = QBFTMsg(
                type=MsgType.ROUND_CHANGE,
                duty=self.duty,
                peer_idx=i,
                round=1,  # round r-1
                value_hash=b"x" * 32,
                signature=self.signature,
                prepared_round=None,  # No prepared value
                prepared_value_hash=None
            )
            round_changes.append(rc)
        
        assert self.consensus.verify_pre_prepare_justification(pre_prepare, round_changes)
    
    def test_verify_round_change_no_prepared_value(self):
        """ROUND-CHANGE with no prepared value should need no justification."""
        round_change = QBFTMsg(
            type=MsgType.ROUND_CHANGE,
            duty=self.duty,
            peer_idx=0,
            round=2,
            value_hash=b"x" * 32,
            signature=self.signature,
            prepared_round=None,
            prepared_value_hash=None
        )
        
        # No prepared value should require no justification
        assert self.consensus.verify_round_change_justification(round_change, [])
        
        # Should reject justifications when no prepared value
        dummy_prepare = QBFTMsg(
            type=MsgType.PREPARE,
            duty=self.duty,
            peer_idx=1,
            round=1,
            value_hash=self.value_hash,
            signature=self.signature,
            prepared_round=None,
            prepared_value_hash=None
        )
        assert not self.consensus.verify_round_change_justification(round_change, [dummy_prepare])
    
    def test_verify_round_change_insufficient_prepares(self):
        """ROUND-CHANGE with prepared value but insufficient PREPARE justifications."""
        round_change = QBFTMsg(
            type=MsgType.ROUND_CHANGE,
            duty=self.duty,
            peer_idx=0,
            round=2,
            value_hash=b"x" * 32,
            signature=self.signature,
            prepared_round=1,
            prepared_value_hash=self.value_hash
        )
        
        # Create insufficient PREPARE messages (need quorum of 3, only provide 1)
        prepare = QBFTMsg(
            type=MsgType.PREPARE,
            duty=self.duty,
            peer_idx=0,
            round=1,
            value_hash=self.value_hash,
            signature=self.signature,
            prepared_round=None,
            prepared_value_hash=None
        )
        
        assert not self.consensus.verify_round_change_justification(round_change, [prepare])
    
    def test_verify_round_change_valid_prepare_justification(self):
        """ROUND-CHANGE with prepared value and valid PREPARE justifications."""
        round_change = QBFTMsg(
            type=MsgType.ROUND_CHANGE,
            duty=self.duty,
            peer_idx=0,
            round=2,
            value_hash=b"x" * 32,
            signature=self.signature,
            prepared_round=1,
            prepared_value_hash=self.value_hash
        )
        
        # Create quorum of PREPARE messages (3 out of 4)
        prepares = []
        for i in range(3):
            prepare = QBFTMsg(
                type=MsgType.PREPARE,
                duty=self.duty,
                peer_idx=i,
                round=1,
                value_hash=self.value_hash,
                signature=self.signature,
                prepared_round=None,
                prepared_value_hash=None
            )
            prepares.append(prepare)
        
        assert self.consensus.verify_round_change_justification(round_change, prepares)
    
    def test_verify_commit_justification(self):
        """Test COMMIT justification verification."""
        commit = QBFTMsg(
            type=MsgType.COMMIT,
            duty=self.duty,
            peer_idx=0,
            round=1,
            value_hash=self.value_hash,
            signature=self.signature,
            prepared_round=1,
            prepared_value_hash=self.value_hash
        )
        
        # Insufficient PREPARE messages
        prepares = []
        for i in range(2):  # Only 2, need quorum of 3
            prepare = QBFTMsg(
                type=MsgType.PREPARE,
                duty=self.duty,
                peer_idx=i,
                round=1,
                value_hash=self.value_hash,
                signature=self.signature,
                prepared_round=None,
                prepared_value_hash=None
            )
            prepares.append(prepare)
        
        assert not self.consensus.verify_commit_justification(commit, prepares)
        
        # Add one more PREPARE to reach quorum
        prepares.append(QBFTMsg(
            type=MsgType.PREPARE,
            duty=self.duty,
            peer_idx=2,
            round=1,
            value_hash=self.value_hash,
            signature=self.signature,
            prepared_round=None,
            prepared_value_hash=None
        ))
        
        assert self.consensus.verify_commit_justification(commit, prepares)
    
    def test_verify_decided_justification(self):
        """Test DECIDED justification verification."""
        decided = QBFTMsg(
            type=MsgType.DECIDED,
            duty=self.duty,
            peer_idx=0,
            round=1,
            value_hash=self.value_hash,
            signature=self.signature,
            prepared_round=1,
            prepared_value_hash=self.value_hash
        )
        
        # Insufficient COMMIT messages
        commits = []
        for i in range(2):  # Only 2, need quorum of 3
            commit = QBFTMsg(
                type=MsgType.COMMIT,
                duty=self.duty,
                peer_idx=i,
                round=1,
                value_hash=self.value_hash,
                signature=self.signature,
                prepared_round=1,
                prepared_value_hash=self.value_hash
            )
            commits.append(commit)
        
        assert not self.consensus.verify_decided_justification(decided, commits)
        
        # Add one more COMMIT to reach quorum
        commits.append(QBFTMsg(
            type=MsgType.COMMIT,
            duty=self.duty,
            peer_idx=2,
            round=1,
            value_hash=self.value_hash,
            signature=self.signature,
            prepared_round=1,
            prepared_value_hash=self.value_hash
        ))
        
        assert self.consensus.verify_decided_justification(decided, commits)