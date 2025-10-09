"""
Test suite for QBFT Protocol implementation
"""

from dv_spec.subspecs.consensus.cryptography import hash_value
from dv_spec.subspecs.consensus.qbft.definition import Definition
from dv_spec.subspecs.consensus.qbft.message import MsgType, QBFTConsensusMsg, QBFTMsg
from dv_spec.subspecs.consensus.qbft.protocol import QBFTConsensus, UponRule
from dv_spec.subspecs.consensus.qbft.transport import PeerInfo, Transport
from dv_spec.types import Duty


def create_test_peers(num_nodes: int) -> list[PeerInfo]:
    """Helper function to create test peers."""
    return [
        PeerInfo(peer_idx=i, public_key=b"test_key", peer_id=f"peer_{i}") for i in range(num_nodes)
    ]


class TestDefinition:
    def test_initialization(self):
        """Test creating a Definition."""
        d = Definition(nodes=4)
        assert d.nodes == 4

    def test_quorum(self):
        """Test quorum calculation."""
        d = Definition(nodes=4)
        assert d.quorum() == 3  # ceil(2*4/3) = 3
        d = Definition(nodes=7)
        assert d.quorum() == 5  # ceil(2*7/3) = 5
        d = Definition(nodes=10)
        assert d.quorum() == 7  # ceil(2*10/3) = 7

    def test_faulty(self):
        """Test faulty node calculation."""
        d = Definition(nodes=4)
        assert d.faulty() == 1  # floor((4-1)/3) = 1
        d = Definition(nodes=7)
        assert d.faulty() == 2  # floor((7-1)/3) = 2
        d = Definition(nodes=10)
        assert d.faulty() == 3  # floor((10-1)/3) = 3

    def test_is_leader(self):
        """Test leader election."""
        duty = Duty(slot=100, type=1)
        d = Definition(nodes=4)

        # Round 1 leader
        assert d.is_leader(duty, 1, 2)  # (100+1+1)%4=2
        assert not d.is_leader(duty, 1, 0)
        assert not d.is_leader(duty, 1, 1)
        assert not d.is_leader(duty, 1, 3)

        # Round 2 leader
        assert d.is_leader(duty, 2, 3)  # (100+1+2)%4=3
        assert not d.is_leader(duty, 2, 0)
        assert not d.is_leader(duty, 2, 1)
        assert not d.is_leader(duty, 2, 2)

        # Round 3 leader
        assert d.is_leader(duty, 3, 0)  # (100+1+3)%4=0
        assert not d.is_leader(duty, 3, 1)
        assert not d.is_leader(duty, 3, 2)
        assert not d.is_leader(duty, 3, 3)

        # Round 4 leader
        assert d.is_leader(duty, 4, 1)  # (100+1+4)%4=1
        assert not d.is_leader(duty, 4, 0)
        assert not d.is_leader(duty, 4, 2)
        assert not d.is_leader(duty, 4, 3)


class TestQBFTConsensus:
    """Test basic QBFTConsensus functionality."""

    def test_initialization(self):
        """Test consensus initialization with correct parameters."""
        duty = Duty(slot=100, type=1)
        d = Definition(nodes=4)
        proposal_value = b"test_block"
        peers = create_test_peers(4)
        transport = Transport(private_key=b"test_key" * 4, peers=peers)  # 32 bytes
        consensus = QBFTConsensus(
            d=d, t=transport, duty=duty, peer=0, proposal_value=proposal_value
        )

        assert consensus.d == d
        assert consensus.duty == duty
        assert consensus.peer == 0
        assert consensus.round == 1
        assert consensus.proposal_value is proposal_value
        assert consensus.prepared_round is None
        assert consensus.prepared_value is None
        assert consensus.prepared_value_hash is None
        assert consensus.prepared_justification == []
        assert consensus.q_commit == []
        assert consensus.buffer == {}
        assert consensus.dedup_rules == {}
        # round_start_time
        # timer
        # Check that proposal value is stored in transport
        proposal_hash = hash_value(proposal_value)
        assert transport.get_value(proposal_hash) == proposal_value

    def test_is_justified_pre_prepare(self):
        """Test is_justified_pre_prepare method."""
        duty = Duty(slot=100, type=1)
        d = Definition(nodes=4)
        proposal_value = b"test_block"
        peers = create_test_peers(4)
        transport = Transport(private_key=b"test_key" * 4, peers=peers)
        consensus = QBFTConsensus(
            d=d, t=transport, duty=duty, peer=0, proposal_value=proposal_value
        )

        # Pre-prepare from non-leader
        non_leader_msg = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.PRE_PREPARE,
                duty=duty,
                peer_idx=1,
                round=1,
                prepared_round=None,
                signature=b"0" * 65,
                value_hash=hash_value(proposal_value),
                prepared_value_hash=None,
            ),
            justification=[],
            values=[proposal_value],
        )
        assert not consensus.is_justified_pre_prepare(non_leader_msg)

        # Pre-prepare from leader
        leader_msg = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.PRE_PREPARE,
                duty=duty,
                peer_idx=2,
                round=1,
                prepared_round=None,
                signature=b"0" * 65,
                value_hash=hash_value(proposal_value),
                prepared_value_hash=None,
            ),
            justification=[],
            values=[proposal_value],
        )
        assert d.is_leader(duty, 1, 2)
        assert consensus.is_justified_pre_prepare(leader_msg)

        # Pre-prepare from leader from second round but without proper justification
        leader_msg_round2_no_just = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.PRE_PREPARE,
                duty=duty,
                peer_idx=3,
                round=2,
                prepared_round=None,
                signature=b"0" * 65,
                value_hash=hash_value(proposal_value),
                prepared_value_hash=None,
            ),
            justification=[],  # No justification
            values=[proposal_value],
        )
        assert d.is_leader(duty, 2, 3)
        assert not consensus.is_justified_pre_prepare(leader_msg_round2_no_just)

        # Pre-prepare from leader from second round with quorum of round-change
        # with nothing prepared
        rc_msgs = []
        for i in range(d.quorum()):
            rc_msg = QBFTMsg(
                type=MsgType.ROUND_CHANGE,
                duty=duty,
                peer_idx=i,
                round=2,
                prepared_round=None,
                signature=b"0" * 65,
                value_hash=None,
                prepared_value_hash=None,
            )
            rc_msgs.append(rc_msg)
        leader_msg_round2_with_just = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.PRE_PREPARE,
                duty=duty,
                peer_idx=3,
                round=2,
                prepared_round=None,
                signature=b"0" * 65,
                value_hash=hash_value(proposal_value),
                prepared_value_hash=None,
            ),
            justification=rc_msgs,
            values=[proposal_value],
        )
        assert d.is_leader(duty, 2, 3)
        assert consensus.is_justified_pre_prepare(leader_msg_round2_with_just)

        # Pre-prepare from leader from second round with quorum of round-change
        # with prepared value
        prepared_value = b"prepared_block"
        prepared_value_hash = hash_value(prepared_value)
        justifications = []
        # quorum of round-change messages with prepared round/value
        for i in range(d.quorum()):
            rc_msg = QBFTMsg(
                type=MsgType.ROUND_CHANGE,
                duty=duty,
                peer_idx=i,
                round=2,
                prepared_round=1,
                signature=b"0" * 65,
                value_hash=None,
                prepared_value_hash=prepared_value_hash,
            )
            justifications.append(rc_msg)
        # quorum of prepare messages from round 1 which caused the round-changes to be prepared
        for i in range(d.quorum()):
            prepare_msg = QBFTMsg(
                type=MsgType.PREPARE,
                duty=duty,
                peer_idx=i,
                round=1,
                prepared_round=None,
                signature=b"0" * 65,
                value_hash=prepared_value_hash,
                prepared_value_hash=None,
            )
            justifications.append(prepare_msg)
        leader_msg_round2_with_just_prepared = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.PRE_PREPARE,
                duty=duty,
                peer_idx=3,
                round=2,
                prepared_round=1,
                signature=b"0" * 65,
                value_hash=prepared_value_hash,
                prepared_value_hash=prepared_value_hash,
            ),
            justification=justifications,
            values=[prepared_value],
        )
        assert d.is_leader(duty, 2, 3)
        assert consensus.is_justified_pre_prepare(leader_msg_round2_with_just_prepared)

        # Pre-prepare from leader from second round with quorum of round-change
        # with prepared value but missing prepare quorum
        justifications = []
        # quorum of round-change messages with prepared round/value
        for i in range(d.quorum()):
            rc_msg = QBFTMsg(
                type=MsgType.ROUND_CHANGE,
                duty=duty,
                peer_idx=i,
                round=2,
                prepared_round=1,
                signature=b"0" * 65,
                value_hash=None,
                prepared_value_hash=prepared_value_hash,
            )
            justifications.append(rc_msg)
        # only faulty number of prepare messages from round 1
        # which caused the round-changes to be prepared
        for i in range(d.faulty()):
            prepare_msg = QBFTMsg(
                type=MsgType.PREPARE,
                duty=duty,
                peer_idx=i,
                round=1,
                prepared_round=None,
                signature=b"0" * 65,
                value_hash=prepared_value_hash,
                prepared_value_hash=None,
            )
            justifications.append(prepare_msg)
        leader_msg_round2_with_just_prepared_insufficient = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.PRE_PREPARE,
                duty=duty,
                peer_idx=3,
                round=2,
                prepared_round=1,
                signature=b"0" * 65,
                value_hash=prepared_value_hash,
                prepared_value_hash=prepared_value_hash,
            ),
            justification=justifications,
            values=[prepared_value],
        )
        assert d.is_leader(duty, 2, 3)
        assert not consensus.is_justified_pre_prepare(
            leader_msg_round2_with_just_prepared_insufficient
        )

    def test_is_justifited_round_change(self):
        """Test is_justified_round_change method."""
        duty = Duty(slot=100, type=1)
        d = Definition(nodes=4)
        proposal_value = b"test_block"
        peers = create_test_peers(4)
        transport = Transport(private_key=b"test_key" * 4, peers=peers)
        consensus = QBFTConsensus(
            d=d, t=transport, duty=duty, peer=0, proposal_value=proposal_value
        )

        # Round-change with no prepared values and no justification
        rc_msg_no_just = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.ROUND_CHANGE,
                duty=duty,
                peer_idx=1,
                round=2,
                prepared_round=None,
                signature=b"0" * 65,
                value_hash=None,
                prepared_value_hash=None,
            ),
            justification=[],
            values=[],
        )
        assert consensus.is_justified_round_change(rc_msg_no_just)

        # Round-change with prepared values but no justification
        rc_msg_prepared_no_just = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.ROUND_CHANGE,
                duty=duty,
                peer_idx=1,
                round=2,
                prepared_round=1,
                signature=b"0" * 65,
                value_hash=None,
                prepared_value_hash=b"0" * 32,
            ),
            justification=[],
            values=[],
        )
        assert not consensus.is_justified_round_change(rc_msg_prepared_no_just)

        # Round-change with prepared value and quorum of justification
        justifications = []
        # quorum of prepare messages from round 1 which caused the prepared value
        prepared_value_hash = b"0" * 32
        for i in range(d.quorum()):
            prepare_msg = QBFTMsg(
                type=MsgType.PREPARE,
                duty=duty,
                peer_idx=i,
                round=1,
                prepared_round=None,
                signature=b"0" * 65,
                value_hash=prepared_value_hash,
                prepared_value_hash=None,
            )
            justifications.append(prepare_msg)
        rc_msg_prepared_with_just = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.ROUND_CHANGE,
                duty=duty,
                peer_idx=1,
                round=2,
                prepared_round=1,
                signature=b"0" * 65,
                value_hash=None,
                prepared_value_hash=prepared_value_hash,
            ),
            justification=justifications,
            values=[],
        )
        assert consensus.is_justified_round_change(rc_msg_prepared_with_just)

    def test_is_justified_decided(self):
        """Test is_justified_decided method."""
        duty = Duty(slot=100, type=1)
        d = Definition(nodes=4)
        proposal_value = b"test_block"
        peers = create_test_peers(4)
        transport = Transport(private_key=b"test_key" * 4, peers=peers)
        consensus = QBFTConsensus(
            d=d, t=transport, duty=duty, peer=0, proposal_value=proposal_value
        )
        proposal_value_hash = hash_value(proposal_value)

        # Decided message without justification
        decided_no_just = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.DECIDED,
                duty=duty,
                peer_idx=1,
                round=1,
                prepared_round=None,
                signature=b"0" * 65,
                value_hash=proposal_value_hash,
                prepared_value_hash=None,
            ),
            justification=[],
            values=[proposal_value],
        )
        assert not consensus.is_justified_decided(decided_no_just)

        # Decided message with insufficient commit justification
        justifications = []
        for i in range(d.faulty()):
            commit_msg = QBFTMsg(
                type=MsgType.COMMIT,
                duty=duty,
                peer_idx=i,
                round=1,
                prepared_round=None,
                signature=b"0" * 65,
                value_hash=proposal_value_hash,
                prepared_value_hash=None,
            )
            justifications.append(commit_msg)
        decided_insufficient_just = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.DECIDED,
                duty=duty,
                peer_idx=1,
                round=1,
                prepared_round=None,
                signature=b"0" * 65,
                value_hash=proposal_value_hash,
                prepared_value_hash=None,
            ),
            justification=justifications,
            values=[proposal_value],
        )
        assert not consensus.is_justified_decided(decided_insufficient_just)

        # Decided message with quorum of commit justification
        justifications = []
        for i in range(d.quorum()):
            commit_msg = QBFTMsg(
                type=MsgType.COMMIT,
                duty=duty,
                peer_idx=i,
                round=1,
                prepared_round=None,
                signature=b"0" * 65,
                value_hash=proposal_value_hash,
                prepared_value_hash=None,
            )
            justifications.append(commit_msg)
        decided_with_just = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.DECIDED,
                duty=duty,
                peer_idx=1,
                round=1,
                prepared_round=None,
                signature=b"0" * 65,
                value_hash=proposal_value_hash,
                prepared_value_hash=None,
            ),
            justification=justifications,
            values=[proposal_value],
        )
        assert consensus.is_justified_decided(decided_with_just)

        # Decided message with different value hash than justification
        justifications = []
        for i in range(d.quorum()):
            commit_msg = QBFTMsg(
                type=MsgType.COMMIT,
                duty=duty,
                peer_idx=i,
                round=1,
                prepared_round=None,
                signature=b"0" * 65,
                value_hash=b"1" * 32,  # Different hash
                prepared_value_hash=None,
            )
            justifications.append(commit_msg)
        decided_diff_hash_just = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.DECIDED,
                duty=duty,
                peer_idx=1,
                round=1,
                prepared_round=None,
                signature=b"0" * 65,
                value_hash=proposal_value_hash,
                prepared_value_hash=None,
            ),
            justification=justifications,
            values=[proposal_value],
        )
        assert not consensus.is_justified_decided(decided_diff_hash_just)

    def test_is_justified(self):
        """
        Test is_justified method.

        Since we already tested the individual justification methods, here we just
        ensure messages that don't require justification return True.
        """
        duty = Duty(slot=100, type=1)
        d = Definition(nodes=4)
        proposal_value = b"test_block"
        peers = create_test_peers(4)
        transport = Transport(private_key=b"test_key" * 4, peers=peers)
        consensus = QBFTConsensus(
            d=d, t=transport, duty=duty, peer=0, proposal_value=proposal_value
        )

        # Prepare message (always justified)
        prepare_msg = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.PREPARE,
                duty=duty,
                peer_idx=1,
                round=1,
                prepared_round=None,
                signature=b"0" * 65,
                value_hash=hash_value(proposal_value),
                prepared_value_hash=None,
            ),
            justification=[],
            values=[],
        )
        assert consensus.is_justified(prepare_msg)

        # Commit message (always justified)
        commit_msg = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.COMMIT,
                duty=duty,
                peer_idx=1,
                round=1,
                prepared_round=None,
                signature=b"0" * 65,
                value_hash=hash_value(proposal_value),
                prepared_value_hash=None,
            ),
            justification=[],
            values=[],
        )
        assert consensus.is_justified(commit_msg)

    def test_buffer_message(self):
        """Test buffering messages."""
        duty = Duty(slot=100, type=1)
        d = Definition(nodes=4)
        proposal_value = b"test_block"
        peers = create_test_peers(4)
        transport = Transport(private_key=b"test_key" * 4, peers=peers)
        consensus = QBFTConsensus(
            d=d, t=transport, duty=duty, peer=0, proposal_value=proposal_value
        )

        msg1 = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.PREPARE,
                duty=duty,
                peer_idx=1,
                round=2,
                prepared_round=None,
                signature=b"0" * 65,
                value_hash=hash_value(proposal_value),
                prepared_value_hash=None,
            ),
            justification=[],
            values=[proposal_value],
        )
        msg2 = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.COMMIT,
                duty=duty,
                peer_idx=2,
                round=3,
                prepared_round=None,
                signature=b"0" * 65,
                value_hash=hash_value(proposal_value),
                prepared_value_hash=None,
            ),
            justification=[],
            values=[proposal_value],
        )

        consensus._buffer_message(msg1)
        consensus._buffer_message(msg2)

        assert 2 in consensus.buffer
        assert consensus.buffer[1] == [msg1]
        assert consensus.buffer[2] == [msg2]

    def test_flatten(self):
        """Test the flatten utility method."""
        duty = Duty(slot=100, type=1)
        d = Definition(nodes=4)
        proposal_value = b"test_block"
        peers = create_test_peers(4)
        transport = Transport(private_key=b"test_key" * 4, peers=peers)
        consensus = QBFTConsensus(
            d=d, t=transport, duty=duty, peer=0, proposal_value=proposal_value
        )

        # message with justification
        round_change_msg = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.ROUND_CHANGE,
                duty=duty,
                peer_idx=1,
                round=2,
                prepared_round=1,
                signature=b"0" * 65,
                value_hash=None,
                prepared_value_hash=hash_value(proposal_value),
            ),
            values=[proposal_value],
            justification=[
                QBFTMsg(
                    type=MsgType.PREPARE,
                    duty=duty,
                    peer_idx=2,
                    round=1,
                    prepared_round=None,
                    signature=b"0" * 65,
                    value_hash=hash_value(proposal_value),
                    prepared_value_hash=None,
                ),
                QBFTMsg(
                    type=MsgType.PREPARE,
                    duty=duty,
                    peer_idx=3,
                    round=1,
                    prepared_round=None,
                    signature=b"0" * 65,
                    value_hash=hash_value(proposal_value),
                    prepared_value_hash=None,
                ),
                QBFTMsg(
                    type=MsgType.PREPARE,
                    duty=duty,
                    peer_idx=0,
                    round=1,
                    prepared_round=None,
                    signature=b"0" * 65,
                    value_hash=hash_value(proposal_value),
                    prepared_value_hash=None,
                ),
            ],
        )

        assert consensus.is_justified_round_change(round_change_msg)

        consensus._buffer_message(round_change_msg)
        assert len(consensus.buffer) == 1  # one round with one message
        assert len(consensus._flatten()) == 4  # 1 round-change + 3 prepares

    def test_classify_decide(self):
        """
        Test the classify method upon receiving a DECIDED message.
        """
        duty = Duty(slot=100, type=1)
        d = Definition(nodes=4)
        proposal_value = b"test_block"
        peers = create_test_peers(4)
        transport = Transport(private_key=b"test_key" * 4, peers=peers)
        consensus = QBFTConsensus(
            d=d, t=transport, duty=duty, peer=0, proposal_value=proposal_value
        )

        # Upon justified decided
        decided_msg = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.DECIDED,
                duty=duty,
                peer_idx=1,
                round=1,
                prepared_round=None,
                signature=b"0" * 65,
                value_hash=hash_value(proposal_value),
                prepared_value_hash=None,
            ),
            justification=[
                QBFTMsg(
                    type=MsgType.COMMIT,
                    duty=duty,
                    peer_idx=2,
                    round=1,
                    prepared_round=None,
                    signature=b"0" * 65,
                    value_hash=hash_value(proposal_value),
                    prepared_value_hash=None,
                ),
                QBFTMsg(
                    type=MsgType.COMMIT,
                    duty=duty,
                    peer_idx=3,
                    round=1,
                    prepared_round=None,
                    signature=b"0" * 65,
                    value_hash=hash_value(proposal_value),
                    prepared_value_hash=None,
                ),
                QBFTMsg(
                    type=MsgType.COMMIT,
                    duty=duty,
                    peer_idx=0,
                    round=1,
                    prepared_round=None,
                    signature=b"0" * 65,
                    value_hash=hash_value(proposal_value),
                    prepared_value_hash=None,
                ),
            ],
            values=[proposal_value],
        )
        assert consensus.is_justified_decided(decided_msg)
        consensus._buffer_message(decided_msg)
        assert len(consensus.buffer) == 1
        (rule, just) = consensus._classify(decided_msg)
        assert rule == UponRule.JUSTIFIED_DECIDED
        assert just == decided_msg.justification

    def test_classify_pre_prepare(self):
        """
        Test the classify method upon receiving a PRE-PREPARE message.
        """
        duty = Duty(slot=100, type=1)
        d = Definition(nodes=4)
        proposal_value = b"test_block"
        peers = create_test_peers(4)
        transport = Transport(private_key=b"test_key" * 4, peers=peers)
        consensus = QBFTConsensus(
            d=d, t=transport, duty=duty, peer=0, proposal_value=proposal_value
        )

        # Upon justified pre-prepare
        pre_prepare_msg = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.PRE_PREPARE,
                duty=duty,
                peer_idx=2,  # leader for round 1
                round=1,
                prepared_round=None,
                signature=b"0" * 65,
                value_hash=hash_value(proposal_value),
                prepared_value_hash=None,
            ),
            justification=[],
            values=[proposal_value],
        )
        assert consensus.is_justified_pre_prepare(pre_prepare_msg)
        consensus._buffer_message(pre_prepare_msg)
        assert len(consensus.buffer) == 1
        (rule, just) = consensus._classify(pre_prepare_msg)
        assert rule == UponRule.JUSTIFIED_PRE_PREPARE
        assert just == pre_prepare_msg.justification

        # Be in round 2 and receive a PRE-PREPARE for round 1 (old round)
        consensus.round = 2
        (rule, just) = consensus._classify(pre_prepare_msg)
        assert rule == UponRule.NOTHING
        assert len(just) == 0

    def test_classify_prepare(self):
        """
        Test the classify method upon receiving a PREPARE message.
        """
        duty = Duty(slot=100, type=1)
        d = Definition(nodes=4)
        proposal_value = b"test_block"
        peers = create_test_peers(4)
        transport = Transport(private_key=b"test_key" * 4, peers=peers)
        consensus = QBFTConsensus(
            d=d, t=transport, duty=duty, peer=0, proposal_value=proposal_value
        )

        prepare_msg1 = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.PREPARE,
                duty=duty,
                peer_idx=1,
                round=1,
                prepared_round=None,
                signature=b"0" * 65,
                value_hash=hash_value(proposal_value),
                prepared_value_hash=None,
            ),
            justification=[],
            values=[proposal_value],
        )
        prepare_msg2 = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.PREPARE,
                duty=duty,
                peer_idx=2,
                round=1,
                prepared_round=None,
                signature=b"0" * 65,
                value_hash=hash_value(proposal_value),
                prepared_value_hash=None,
            ),
            justification=[],
            values=[proposal_value],
        )
        prepare_msg3 = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.PREPARE,
                duty=duty,
                peer_idx=3,
                round=1,
                prepared_round=None,
                signature=b"0" * 65,
                value_hash=b"1" * 32,  # different value hash
                prepared_value_hash=None,
            ),
            justification=[],
            values=[b"other_value"],
        )
        prepare_msg4 = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.PREPARE,
                duty=duty,
                peer_idx=0,
                round=1,
                prepared_round=None,
                signature=b"0" * 65,
                value_hash=hash_value(proposal_value),
                prepared_value_hash=None,
            ),
            justification=[],
            values=[proposal_value],
        )

        # First prepare for X value
        consensus._buffer_message(prepare_msg1)
        (rule, just) = consensus._classify(prepare_msg1)
        assert rule == UponRule.NOTHING
        assert len(just) == 0
        # Second prepare for X value
        consensus._buffer_message(prepare_msg2)
        (rule, just) = consensus._classify(prepare_msg2)
        assert rule == UponRule.NOTHING
        assert len(just) == 0
        # Prepare for different value (should not affect quorum for X)
        consensus._buffer_message(prepare_msg3)
        (rule, just) = consensus._classify(prepare_msg3)
        assert rule == UponRule.NOTHING
        assert len(just) == 0
        # Third prepare for X value (should reach quorum now)
        consensus._buffer_message(prepare_msg4)
        (rule, just) = consensus._classify(prepare_msg4)
        assert rule == UponRule.QUORUM_PREPARES
        assert len(just) == 3  # the 3 prepares which formed the quorum

    def test_classify_commit(self):
        """
        Test the classify method upon receiving a COMMIT message.
        """
        duty = Duty(slot=100, type=1)
        d = Definition(nodes=4)
        proposal_value = b"test_block"
        peers = create_test_peers(4)
        transport = Transport(private_key=b"test_key" * 4, peers=peers)
        consensus = QBFTConsensus(
            d=d, t=transport, duty=duty, peer=0, proposal_value=proposal_value
        )

        commit_msg1 = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.COMMIT,
                duty=duty,
                peer_idx=1,
                round=1,
                prepared_round=None,
                signature=b"0" * 65,
                value_hash=hash_value(proposal_value),
                prepared_value_hash=None,
            ),
            justification=[],
            values=[proposal_value],
        )
        commit_msg2 = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.COMMIT,
                duty=duty,
                peer_idx=2,
                round=1,
                prepared_round=None,
                signature=b"0" * 65,
                value_hash=hash_value(proposal_value),
                prepared_value_hash=None,
            ),
            justification=[],
            values=[proposal_value],
        )
        commit_msg3 = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.COMMIT,
                duty=duty,
                peer_idx=3,
                round=1,
                prepared_round=None,
                signature=b"0" * 65,
                value_hash=b"1" * 32,  # different value hash
                prepared_value_hash=None,
            ),
            justification=[],
            values=[b"other_value"],
        )
        commit_msg4 = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.COMMIT,
                duty=duty,
                peer_idx=0,
                round=1,
                prepared_round=None,
                signature=b"0" * 65,
                value_hash=hash_value(proposal_value),
                prepared_value_hash=None,
            ),
            justification=[],
            values=[proposal_value],
        )

        # First commit for X value
        consensus._buffer_message(commit_msg1)
        (rule, just) = consensus._classify(commit_msg1)
        assert rule == UponRule.NOTHING
        assert len(just) == 0
        # Second commit for X value
        consensus._buffer_message(commit_msg2)
        (rule, just) = consensus._classify(commit_msg2)
        assert rule == UponRule.NOTHING
        assert len(just) == 0
        # Commit for different value (should not affect quorum for X)
        consensus._buffer_message(commit_msg3)
        (rule, just) = consensus._classify(commit_msg3)
        assert rule == UponRule.NOTHING
        assert len(just) == 0
        # Third commit for X value (should reach quorum now)
        consensus._buffer_message(commit_msg4)
        (rule, just) = consensus._classify(commit_msg4)
        assert rule == UponRule.QUORUM_COMMITS
        assert len(just) == 3  # the 3 commits which formed the quorum

    def test_classify_round_change(self):
        """
        Test the classify method upon receiving a ROUND-CHANGE message.
        """
        duty = Duty(slot=100, type=1)
        d = Definition(nodes=4)
        proposal_value = b"test_block"
        peers = create_test_peers(4)
        transport_leader = Transport(private_key=b"test_key" * 4, peers=peers)
        consensus_leader = QBFTConsensus(
            d=d, t=transport_leader, duty=duty, peer=3, proposal_value=proposal_value
        )
        transport_non_leader = Transport(private_key=b"test_key" * 4, peers=peers)
        consensus_non_leader = QBFTConsensus(
            d=d, t=transport_non_leader, duty=duty, peer=0, proposal_value=proposal_value
        )

        # Send round-change messages with nothing prepared
        rc_msg1 = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.ROUND_CHANGE,
                duty=duty,
                peer_idx=0,
                round=2,
                prepared_round=None,
                signature=b"0" * 65,
                value_hash=None,
                prepared_value_hash=None,
            ),
            justification=[],
            values=[],
        )

        consensus_leader._buffer_message(rc_msg1)
        (rule, just) = consensus_leader._classify(rc_msg1)
        assert rule == UponRule.NOTHING
        assert len(just) == 0
        consensus_non_leader._buffer_message(rc_msg1)
        (rule, just) = consensus_non_leader._classify(rc_msg1)
        assert rule == UponRule.NOTHING
        assert len(just) == 0

        rc_msg2 = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.ROUND_CHANGE,
                duty=duty,
                peer_idx=1,
                round=2,
                prepared_round=None,
                signature=b"0" * 65,
                value_hash=None,
                prepared_value_hash=None,
            ),
            justification=[],
            values=[],
        )
        consensus_leader._buffer_message(rc_msg2)
        (rule, just) = consensus_leader._classify(rc_msg2)
        assert rule == UponRule.F_PLUS_1_ROUND_CHANGES
        assert len(just) == 2
        consensus_non_leader._buffer_message(rc_msg2)
        (rule, just) = consensus_non_leader._classify(rc_msg2)
        assert rule == UponRule.F_PLUS_1_ROUND_CHANGES
        assert len(just) == 2

        consensus_leader.round = 2  # move to round 2 since we have f+1 round-change messages
        consensus_non_leader.round = 2

        rc_msg3 = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.ROUND_CHANGE,
                duty=duty,
                peer_idx=2,
                round=2,
                prepared_round=None,
                signature=b"0" * 65,
                value_hash=None,
                prepared_value_hash=None,
            ),
            justification=[],
            values=[],
        )
        consensus_leader._buffer_message(rc_msg3)
        (rule, just) = consensus_leader._classify(rc_msg3)
        assert rule == UponRule.QUORUM_ROUND_CHANGES
        assert len(just) == 3
        consensus_non_leader._buffer_message(rc_msg3)
        (rule, just) = consensus_non_leader._classify(rc_msg3)
        assert rule == UponRule.NOTHING  # non-leader does not act on quorum of round-changes
        assert len(just) == 0

        # Send round-change messages with prepared value and justification

        d = Definition(nodes=4)
        prepared_value = b"prepared_block"
        prepared_value_hash = hash_value(prepared_value)
        peers = create_test_peers(4)
        transport = Transport(private_key=b"test_key" * 4, peers=peers)
        consensus = QBFTConsensus(
            d=d, t=transport, duty=duty, peer=3, proposal_value=proposal_value
        )

        prepare_msgs = []
        for i in range(d.quorum()):
            prepare_msg = QBFTMsg(
                type=MsgType.PREPARE,
                duty=duty,
                peer_idx=i,
                round=1,
                prepared_round=None,
                signature=b"0" * 65,
                value_hash=prepared_value_hash,
                prepared_value_hash=None,
            )
            prepare_msgs.append(prepare_msg)

        rc_msg1 = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.ROUND_CHANGE,
                duty=duty,
                peer_idx=0,
                round=2,
                prepared_round=1,
                signature=b"0" * 65,
                value_hash=None,
                prepared_value_hash=prepared_value_hash,
            ),
            justification=prepare_msgs,
            values=[],
        )
        consensus._buffer_message(rc_msg1)
        (rule, just) = consensus._classify(rc_msg1)
        assert rule == UponRule.NOTHING
        assert len(just) == 0

        rc_msg2 = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.ROUND_CHANGE,
                duty=duty,
                peer_idx=1,
                round=2,
                prepared_round=1,
                signature=b"0" * 65,
                value_hash=None,
                prepared_value_hash=prepared_value_hash,
            ),
            justification=prepare_msgs,
            values=[],
        )
        consensus._buffer_message(rc_msg2)
        (rule, just) = consensus._classify(rc_msg2)
        assert rule == UponRule.F_PLUS_1_ROUND_CHANGES
        assert len(just) == 2

        consensus.round = 2  # move to round 2 since we have f+1 round-change messages

        rc_msg3 = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.ROUND_CHANGE,
                duty=duty,
                peer_idx=2,
                round=2,
                prepared_round=1,
                signature=b"0" * 65,
                value_hash=None,
                prepared_value_hash=prepared_value_hash,
            ),
            justification=prepare_msgs,
            values=[],
        )
        consensus._buffer_message(rc_msg3)
        (rule, just) = consensus._classify(rc_msg3)
        assert rule == UponRule.QUORUM_ROUND_CHANGES
        assert len(just) == 3 + 3  # quorum of round-changes + quorum of prepares

        # Send round-change messages with prepared value and no justification

        d = Definition(nodes=4)
        prepared_value = b"prepared_block"
        prepared_value_hash = hash_value(prepared_value)
        peers = create_test_peers(4)
        transport = Transport(private_key=b"test_key" * 4, peers=peers)
        consensus = QBFTConsensus(
            d=d, t=transport, duty=duty, peer=3, proposal_value=proposal_value
        )

        rc_msg1 = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.ROUND_CHANGE,
                duty=duty,
                peer_idx=0,
                round=2,
                prepared_round=1,
                signature=b"0" * 65,
                value_hash=None,
                prepared_value_hash=prepared_value_hash,
            ),
            justification=[],
            values=[],
        )
        consensus._buffer_message(rc_msg1)
        (rule, just) = consensus._classify(rc_msg1)
        assert rule == UponRule.NOTHING
        assert len(just) == 0

        rc_msg2 = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.ROUND_CHANGE,
                duty=duty,
                peer_idx=1,
                round=2,
                prepared_round=1,
                signature=b"0" * 65,
                value_hash=None,
                prepared_value_hash=prepared_value_hash,
            ),
            justification=[],
            values=[],
        )
        consensus._buffer_message(rc_msg2)
        (rule, just) = consensus._classify(rc_msg2)
        assert rule == UponRule.F_PLUS_1_ROUND_CHANGES
        assert len(just) == 2

        consensus.round = 2  # move to round 2 since we have f+1 round-change messages

        rc_msg3 = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.ROUND_CHANGE,
                duty=duty,
                peer_idx=2,
                round=2,
                prepared_round=1,
                signature=b"0" * 65,
                value_hash=None,
                prepared_value_hash=prepared_value_hash,
            ),
            justification=[],
            values=[],
        )
        consensus._buffer_message(rc_msg3)
        (rule, just) = consensus._classify(rc_msg3)
        assert rule == UponRule.UNJUST_QUORUM_ROUND_CHANGES
        assert len(just) == 0

    def test_broadcast_message(self):
        """
        Test the broadcast_message utility method from transport.

        This is used for pre-prepare/prepare/commit messages.
        """

        duty = Duty(slot=100, type=1)
        d = Definition(nodes=4)
        proposal_value = b"test_block"
        peers = create_test_peers(4)
        transport = Transport(private_key=b"test_key" * 4, peers=peers)
        consensus = QBFTConsensus(
            d=d, t=transport, duty=duty, peer=0, proposal_value=proposal_value
        )

        res = transport.broadcast_message(
            msg_type=MsgType.PRE_PREPARE,
            duty=duty,
            peer_idx=consensus.peer,
            round_num=consensus.round,
            value_hash=hash_value(proposal_value),
            justification=[],
        )
        assert len(res) == d.nodes
        assert res[0].msg.type == MsgType.PRE_PREPARE
        assert res[0].msg.duty == duty
        assert res[0].msg.round == consensus.round
        assert res[0].msg.peer_idx == consensus.peer
        # Knows own mapping from value_hash to proposal_value
        assert len(res[0].values) == 1
        assert res[0].values[0] == proposal_value

        res = transport.broadcast_message(
            msg_type=MsgType.PREPARE,
            duty=duty,
            peer_idx=consensus.peer,
            round_num=consensus.round,
            value_hash=hash_value(b"other_value"),
            justification=[],
        )
        assert len(res) == d.nodes
        assert res[0].msg.type == MsgType.PREPARE
        assert res[0].msg.duty == duty
        assert res[0].msg.round == consensus.round
        assert res[0].msg.peer_idx == consensus.peer
        assert res[0].msg.value_hash == hash_value(b"other_value")
        # Does not know mapping from value_hash to proposal_value
        assert len(res[0].values) == 0

    def test_broadcast_round_change(self):
        """
        Test the broadcast_round_change utility method from transport.
        """

        duty = Duty(slot=100, type=1)
        d = Definition(nodes=4)
        proposal_value = b"test_block"
        peers = create_test_peers(4)
        transport = Transport(private_key=b"test_key" * 4, peers=peers)
        consensus = QBFTConsensus(
            d=d, t=transport, duty=duty, peer=0, proposal_value=proposal_value
        )

        # Without prepared value and justification
        res = transport.broadcast_round_change(
            duty=duty, peer_idx=consensus.peer, round_num=consensus.round
        )
        assert len(res) == d.nodes
        assert res[0].msg.type == MsgType.ROUND_CHANGE
        assert res[0].msg.duty == duty
        assert res[0].msg.round == consensus.round
        assert res[0].msg.peer_idx == consensus.peer
        assert res[0].msg.prepared_round is None
        assert res[0].msg.prepared_value_hash is None
        assert len(res[0].justification) == 0
        assert len(res[0].values) == 0

        # With prepared value and justification
        prepared_value = b"prepared_block"
        prepared_value_hash = hash_value(prepared_value)
        consensus.prepared_round = 1
        consensus.prepared_value_hash = prepared_value_hash
        transport.set_values({prepared_value_hash: prepared_value})

        prepare_msgs = []
        for i in range(d.quorum()):
            prepare_msg = QBFTMsg(
                type=MsgType.PREPARE,
                duty=duty,
                peer_idx=i,
                round=1,
                prepared_round=None,
                signature=b"0" * 65,
                value_hash=prepared_value_hash,
                prepared_value_hash=None,
            )
            prepare_msgs.append(prepare_msg)
        consensus.prepared_justification = prepare_msgs

        res = transport.broadcast_round_change(
            duty=duty,
            peer_idx=consensus.peer,
            round_num=consensus.round,
            prepared_round=consensus.prepared_round,
            prepared_value_hash=consensus.prepared_value_hash,
            prepared_justification=consensus.prepared_justification,
        )
        assert len(res) == d.nodes
        assert res[0].msg.type == MsgType.ROUND_CHANGE
        assert res[0].msg.duty == duty
        assert res[0].msg.round == consensus.round
        assert res[0].msg.peer_idx == consensus.peer
        assert res[0].msg.prepared_round == 1
        assert res[0].msg.prepared_value_hash == prepared_value_hash
        assert len(res[0].justification) == d.quorum()
        assert len(res[0].values) == 1  # stored mapping
        assert res[0].values[0] == prepared_value

    def test_broadcast_own_pre_prepare(self):
        """
        Test the broadcast_pre_prepare utility method from transport.

        This is used by the leader to broadcast its own pre-prepare message.
        """

        duty = Duty(slot=100, type=1)
        d = Definition(nodes=4)
        proposal_value = b"test_block"
        peers = create_test_peers(4)
        transport = Transport(private_key=b"test_key" * 4, peers=peers)
        consensus = QBFTConsensus(
            d=d, t=transport, duty=duty, peer=0, proposal_value=proposal_value
        )

        res = transport.broadcast_pre_prepare(
            duty=duty,
            peer_idx=consensus.peer,
            round_num=consensus.round,
            value_hash=hash_value(proposal_value),
            justification=[],
        )
        assert len(res) == d.nodes
        assert res[0].msg.type == MsgType.PRE_PREPARE
        assert res[0].msg.duty == duty
        assert res[0].msg.round == consensus.round
        assert res[0].msg.peer_idx == consensus.peer
        assert len(res[0].values) == 1
        assert res[0].values[0] == proposal_value

    def test_change_round(self):
        """
        Test the _change_round utility method.

        Since this is called from handle_message, we know the round number will be >= current round.
        """
        duty = Duty(slot=100, type=1)
        d = Definition(nodes=4)
        proposal_value = b"test_block"
        peers = create_test_peers(4)
        transport = Transport(private_key=b"test_key" * 4, peers=peers)
        consensus = QBFTConsensus(
            d=d, t=transport, duty=duty, peer=0, proposal_value=proposal_value
        )
        consensus.dedup_rules[(MsgType.PRE_PREPARE, 1)] = True

        assert consensus.round == 1
        assert len(consensus.dedup_rules) == 1
        consensus._change_round(3)
        assert consensus.round == 3
        assert len(consensus.dedup_rules) == 0

    def test_handle_message_happy_path(self):
        """
        Test the handle_message method.

        This is the main entry point for processing incoming messages.
        Contains all previous logic so this test works as an integration test.

        Upon handling a message, the method will return a list of messages to be broadcasted.

        This test will cover the happy path where consensus is reached in round 1.
        Next tests will cover alternate paths.
        """
        duty = Duty(slot=102, type=1)
        d = Definition(nodes=4)
        proposal_value = b"test_block"
        peers = create_test_peers(4)
        transport = Transport(private_key=b"test_key" * 4, peers=peers)
        consensus = QBFTConsensus(
            d=d, t=transport, duty=duty, peer=0, proposal_value=proposal_value
        )
        proposal_value_hash = hash_value(proposal_value)

        # Receive own pre-prepare (as leader)
        pre_prepare_msg = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.PRE_PREPARE,
                duty=duty,
                peer_idx=0,  # self as leader for round 1
                round=1,
                prepared_round=None,
                signature=b"0" * 65,
                value_hash=proposal_value_hash,
                prepared_value_hash=None,
            ),
            justification=[],
            values=[proposal_value],
        )
        res = consensus.handle_message(pre_prepare_msg)
        assert len(res) == d.nodes  # should broadcast prepare messages
        assert all(m.msg.type == MsgType.PREPARE for m in res)
        assert all(m.msg.round == 1 for m in res)
        assert all(m.msg.peer_idx == 0 for m in res)  # from self
        assert all(m.msg.value_hash == hash_value(proposal_value) for m in res)
        assert all(m.justification == [] for m in res)
        assert all(m.values == [proposal_value] for m in res)
        assert consensus.prepared_round is None
        assert consensus.prepared_value_hash is None
        assert len(consensus.prepared_justification) == 0  # no justification in pre-prepare

        prepare_msg1 = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.PREPARE,
                duty=duty,
                peer_idx=1,
                round=1,
                signature=b"0" * 65,
                value_hash=proposal_value_hash,
            ),
            justification=[],
            values=[proposal_value],
        )
        prepare_msg2 = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.PREPARE,
                duty=duty,
                peer_idx=2,
                round=1,
                signature=b"0" * 65,
                value_hash=proposal_value_hash,
            ),
            justification=[],
            values=[proposal_value],
        )
        prepare_msg3 = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.PREPARE,
                duty=duty,
                peer_idx=3,
                round=1,
                signature=b"0" * 65,
                value_hash=proposal_value_hash,
            ),
            justification=[],
            values=[proposal_value],
        )
        res = consensus.handle_message(prepare_msg1)
        assert len(res) == 0  # no broadcast yet (only 1 prepare)

        res = consensus.handle_message(prepare_msg2)
        assert len(res) == 0  # no broadcast yet (only 2 prepares)

        res = consensus.handle_message(prepare_msg3)
        assert len(res) == d.nodes  # should broadcast commit messages now (3rd prepare
        assert all(m.msg.type == MsgType.COMMIT for m in res)
        assert all(m.msg.round == 1 for m in res)
        assert all(m.msg.peer_idx == 0 for m in res)  # from self
        assert all(m.msg.value_hash == proposal_value_hash for m in res)
        assert all(m.justification == [] for m in res)
        assert all(m.values == [proposal_value] for m in res)
        assert consensus.prepared_round == 1
        assert consensus.prepared_value_hash == proposal_value_hash

        commit_msg1 = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.COMMIT,
                duty=duty,
                peer_idx=1,
                round=1,
                signature=b"0" * 65,
                value_hash=proposal_value_hash,
            ),
            justification=[],
            values=[proposal_value],
        )
        commit_msg2 = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.COMMIT,
                duty=duty,
                peer_idx=2,
                round=1,
                signature=b"0" * 65,
                value_hash=proposal_value_hash,
            ),
            justification=[],
            values=[proposal_value],
        )
        commit_msg3 = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.COMMIT,
                duty=duty,
                peer_idx=3,
                round=1,
                signature=b"0" * 65,
                value_hash=proposal_value_hash,
            ),
            justification=[],
            values=[proposal_value],
        )
        res = consensus.handle_message(commit_msg1)
        assert len(res) == 0  # no broadcast yet (only 1 commit)

        res = consensus.handle_message(commit_msg2)
        assert len(res) == 0  # no broadcast yet (only 2 commits)

        res = consensus.handle_message(commit_msg3)
        assert len(res) == 0
        assert consensus.q_commit is not None  # should have decided now
