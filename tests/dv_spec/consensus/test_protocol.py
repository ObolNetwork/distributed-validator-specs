"""
Test suite for QBFT Protocol implementation
"""

from dv_spec.subspecs.consensus.cryptography import hash_value
from dv_spec.subspecs.consensus.qbft.definition import Definition
from dv_spec.subspecs.consensus.qbft.message import MsgType, QBFTConsensusMsg, QBFTMsg
from dv_spec.subspecs.consensus.qbft.protocol import (
    MAX_DECIDED_RESENDS,
    QBFTConsensus,
    UponRule,
)
from dv_spec.subspecs.consensus.qbft.transport import PeerInfo, Transport
from dv_spec.types import Duty


def create_test_peers(num_nodes: int) -> list[PeerInfo]:
    """Helper function to create test peers."""
    return [
        PeerInfo(peer_idx=i, public_key=b"test_key", peer_id=f"peer_{i}") for i in range(num_nodes)
    ]


class TestDefinition:
    def test_initialization(self) -> None:
        """Test creating a Definition."""
        d = Definition(nodes=4)
        assert d.nodes == 4

    def test_quorum(self) -> None:
        """Test quorum calculation."""
        d = Definition(nodes=4)
        assert d.quorum() == 3  # ceil(2*4/3) = 3
        d = Definition(nodes=7)
        assert d.quorum() == 5  # ceil(2*7/3) = 5
        d = Definition(nodes=10)
        assert d.quorum() == 7  # ceil(2*10/3) = 7

    def test_faulty(self) -> None:
        """Test faulty node calculation."""
        d = Definition(nodes=4)
        assert d.faulty() == 1  # floor((4-1)/3) = 1
        d = Definition(nodes=7)
        assert d.faulty() == 2  # floor((7-1)/3) = 2
        d = Definition(nodes=10)
        assert d.faulty() == 3  # floor((10-1)/3) = 3

    def test_is_leader(self) -> None:
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

    def test_initialization(self) -> None:
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

    def test_is_justified_pre_prepare(self) -> None:
        """Test is_justified_pre_prepare method."""
        duty = Duty(slot=100, type=1)
        d = Definition(nodes=4)
        proposal_value = b"test_block"
        peers = create_test_peers(4)
        transport = Transport(private_key=b"test_key" * 4, peers=peers)
        consensus = QBFTConsensus(
            d=d, t=transport, duty=duty, peer=0, proposal_value=proposal_value
        )

        # Non pre-prepare message
        wrong_type_msg = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.COMMIT,
                duty=duty,
                peer_idx=0,
                round=1,
                prepared_round=0,
                signature=b"0" * 65,
                value_hash=hash_value(proposal_value),
                prepared_value_hash=b"\x00" * 32,
            ),
            justification=[],
            values=[proposal_value],
        )
        assert not consensus.is_justified_pre_prepare(wrong_type_msg)

        # Pre-prepare from non-leader
        non_leader_msg = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.PRE_PREPARE,
                duty=duty,
                peer_idx=1,
                round=1,
                prepared_round=0,
                signature=b"0" * 65,
                value_hash=hash_value(proposal_value),
                prepared_value_hash=b"\x00" * 32,
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
                prepared_round=0,
                signature=b"0" * 65,
                value_hash=hash_value(proposal_value),
                prepared_value_hash=b"\x00" * 32,
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
                prepared_round=0,
                signature=b"0" * 65,
                value_hash=hash_value(proposal_value),
                prepared_value_hash=b"\x00" * 32,
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
                prepared_round=0,
                signature=b"0" * 65,
                value_hash=None,
                prepared_value_hash=b"\x00" * 32,
            )
            rc_msgs.append(rc_msg)
        leader_msg_round2_with_just = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.PRE_PREPARE,
                duty=duty,
                peer_idx=3,
                round=2,
                prepared_round=0,
                signature=b"0" * 65,
                value_hash=hash_value(proposal_value),
                prepared_value_hash=b"\x00" * 32,
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
                prepared_round=0,
                signature=b"0" * 65,
                value_hash=prepared_value_hash,
                prepared_value_hash=b"\x00" * 32,
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
                prepared_round=0,
                signature=b"0" * 65,
                value_hash=prepared_value_hash,
                prepared_value_hash=b"\x00" * 32,
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

        # quorum of round-change messages but one of them has higher prepared round
        # than what is justified by the prepare quorum
        justifications = []
        for i in range(d.quorum() - 1):
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
        higher_rc_msg = QBFTMsg(
            type=MsgType.ROUND_CHANGE,
            duty=duty,
            peer_idx=d.quorum() - 1,
            round=2,
            prepared_round=2,  # Higher prepared round
            signature=b"0" * 65,
            value_hash=None,
            prepared_value_hash=prepared_value_hash,
        )
        justifications.append(higher_rc_msg)
        # quorum of prepare messages from round 1 which caused the round-changes to be prepared
        for i in range(d.quorum()):
            prepare_msg = QBFTMsg(
                type=MsgType.PREPARE,
                duty=duty,
                peer_idx=i,
                round=1,
                prepared_round=0,
                signature=b"0" * 65,
                value_hash=prepared_value_hash,
                prepared_value_hash=b"\x00" * 32,
            )
            justifications.append(prepare_msg)
        leader_msg = QBFTConsensusMsg(
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
        assert not consensus.is_justified_pre_prepare(leader_msg)

    def test_is_justifited_round_change(self) -> None:
        """Test is_justified_round_change method."""
        duty = Duty(slot=100, type=1)
        d = Definition(nodes=4)
        proposal_value = b"test_block"
        peers = create_test_peers(4)
        transport = Transport(private_key=b"test_key" * 4, peers=peers)
        consensus = QBFTConsensus(
            d=d, t=transport, duty=duty, peer=0, proposal_value=proposal_value
        )

        # Non round-change message
        wrong_type_msg = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.COMMIT,
                duty=duty,
                peer_idx=0,
                round=1,
                prepared_round=0,
                signature=b"0" * 65,
                value_hash=hash_value(proposal_value),
                prepared_value_hash=b"\x00" * 32,
            ),
            justification=[],
            values=[proposal_value],
        )
        assert not consensus.is_justified_round_change(wrong_type_msg)

        # Round-change with no prepared values and no justification
        rc_msg_no_just = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.ROUND_CHANGE,
                duty=duty,
                peer_idx=1,
                round=2,
                prepared_round=0,
                signature=b"0" * 65,
                value_hash=None,
                prepared_value_hash=b"\x00" * 32,
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
                prepared_round=0,
                signature=b"0" * 65,
                value_hash=prepared_value_hash,
                prepared_value_hash=b"\x00" * 32,
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

    def test_is_justified_decided(self) -> None:
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

        # Non decided message
        wrong_type_msg = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.COMMIT,
                duty=duty,
                peer_idx=0,
                round=1,
                prepared_round=0,
                signature=b"0" * 65,
                value_hash=hash_value(proposal_value),
                prepared_value_hash=b"\x00" * 32,
            ),
            justification=[],
            values=[proposal_value],
        )
        assert not consensus.is_justified_decided(wrong_type_msg)

        # Decided message without justification
        decided_no_just = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.DECIDED,
                duty=duty,
                peer_idx=1,
                round=1,
                prepared_round=0,
                signature=b"0" * 65,
                value_hash=proposal_value_hash,
                prepared_value_hash=b"\x00" * 32,
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
                prepared_round=0,
                signature=b"0" * 65,
                value_hash=proposal_value_hash,
                prepared_value_hash=b"\x00" * 32,
            )
            justifications.append(commit_msg)
        decided_insufficient_just = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.DECIDED,
                duty=duty,
                peer_idx=1,
                round=1,
                prepared_round=0,
                signature=b"0" * 65,
                value_hash=proposal_value_hash,
                prepared_value_hash=b"\x00" * 32,
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
                prepared_round=0,
                signature=b"0" * 65,
                value_hash=proposal_value_hash,
                prepared_value_hash=b"\x00" * 32,
            )
            justifications.append(commit_msg)
        decided_with_just = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.DECIDED,
                duty=duty,
                peer_idx=1,
                round=1,
                prepared_round=0,
                signature=b"0" * 65,
                value_hash=proposal_value_hash,
                prepared_value_hash=b"\x00" * 32,
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
                prepared_round=0,
                signature=b"0" * 65,
                value_hash=b"1" * 32,  # Different hash
                prepared_value_hash=b"\x00" * 32,
            )
            justifications.append(commit_msg)
        decided_diff_hash_just = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.DECIDED,
                duty=duty,
                peer_idx=1,
                round=1,
                prepared_round=0,
                signature=b"0" * 65,
                value_hash=proposal_value_hash,
                prepared_value_hash=b"\x00" * 32,
            ),
            justification=justifications,
            values=[proposal_value],
        )
        assert not consensus.is_justified_decided(decided_diff_hash_just)

    def test_is_justified(self) -> None:
        """
        Test is_justified method.
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
                prepared_round=0,
                signature=b"0" * 65,
                value_hash=hash_value(proposal_value),
                prepared_value_hash=b"\x00" * 32,
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
                prepared_round=0,
                signature=b"0" * 65,
                value_hash=hash_value(proposal_value),
                prepared_value_hash=b"\x00" * 32,
            ),
            justification=[],
            values=[],
        )
        assert consensus.is_justified(commit_msg)

        # Round-change message
        rc_msg = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.ROUND_CHANGE,
                duty=duty,
                peer_idx=1,
                round=2,
                prepared_round=0,
                signature=b"0" * 65,
                value_hash=None,
                prepared_value_hash=b"\x00" * 32,
            ),
            justification=[],
            values=[],
        )
        assert consensus.is_justified(rc_msg)

        # Decided message with quorum justification
        justifications = []
        for i in range(d.quorum()):
            j_commit_msg = QBFTMsg(
                type=MsgType.COMMIT,
                duty=duty,
                peer_idx=i,
                round=1,
                prepared_round=0,
                signature=b"0" * 65,
                value_hash=hash_value(proposal_value),
                prepared_value_hash=b"\x00" * 32,
            )
            justifications.append(j_commit_msg)
        decided_msg = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.DECIDED,
                duty=duty,
                peer_idx=1,
                round=1,
                prepared_round=0,
                signature=b"0" * 65,
                value_hash=hash_value(proposal_value),
                prepared_value_hash=b"\x00" * 32,
            ),
            justification=justifications,
            values=[proposal_value],
        )
        assert consensus.is_justified(decided_msg)

    def test_buffer_message(self) -> None:
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
                prepared_round=0,
                signature=b"0" * 65,
                value_hash=hash_value(proposal_value),
                prepared_value_hash=b"\x00" * 32,
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
                prepared_round=0,
                signature=b"0" * 65,
                value_hash=hash_value(proposal_value),
                prepared_value_hash=b"\x00" * 32,
            ),
            justification=[],
            values=[proposal_value],
        )

        consensus._buffer_message(msg1)
        consensus._buffer_message(msg2)

        assert 2 in consensus.buffer
        assert consensus.buffer[1] == [msg1]
        assert consensus.buffer[2] == [msg2]

    def test_flatten(self) -> None:
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
                    prepared_round=0,
                    signature=b"0" * 65,
                    value_hash=hash_value(proposal_value),
                    prepared_value_hash=b"\x00" * 32,
                ),
                QBFTMsg(
                    type=MsgType.PREPARE,
                    duty=duty,
                    peer_idx=3,
                    round=1,
                    prepared_round=0,
                    signature=b"0" * 65,
                    value_hash=hash_value(proposal_value),
                    prepared_value_hash=b"\x00" * 32,
                ),
                QBFTMsg(
                    type=MsgType.PREPARE,
                    duty=duty,
                    peer_idx=0,
                    round=1,
                    prepared_round=0,
                    signature=b"0" * 65,
                    value_hash=hash_value(proposal_value),
                    prepared_value_hash=b"\x00" * 32,
                ),
            ],
        )

        assert consensus.is_justified_round_change(round_change_msg)

        consensus._buffer_message(round_change_msg)
        assert len(consensus.buffer) == 1  # one round with one message
        assert len(consensus._flatten()) == 4  # 1 round-change + 3 prepares

    def test_classify_decide(self) -> None:
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
                prepared_round=0,
                signature=b"0" * 65,
                value_hash=hash_value(proposal_value),
                prepared_value_hash=b"\x00" * 32,
            ),
            justification=[
                QBFTMsg(
                    type=MsgType.COMMIT,
                    duty=duty,
                    peer_idx=2,
                    round=1,
                    prepared_round=0,
                    signature=b"0" * 65,
                    value_hash=hash_value(proposal_value),
                    prepared_value_hash=b"\x00" * 32,
                ),
                QBFTMsg(
                    type=MsgType.COMMIT,
                    duty=duty,
                    peer_idx=3,
                    round=1,
                    prepared_round=0,
                    signature=b"0" * 65,
                    value_hash=hash_value(proposal_value),
                    prepared_value_hash=b"\x00" * 32,
                ),
                QBFTMsg(
                    type=MsgType.COMMIT,
                    duty=duty,
                    peer_idx=0,
                    round=1,
                    prepared_round=0,
                    signature=b"0" * 65,
                    value_hash=hash_value(proposal_value),
                    prepared_value_hash=b"\x00" * 32,
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

    def test_classify_pre_prepare(self) -> None:
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
                prepared_round=0,
                signature=b"0" * 65,
                value_hash=hash_value(proposal_value),
                prepared_value_hash=b"\x00" * 32,
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

    def test_classify_prepare(self) -> None:
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

        # Prepare from different round
        wrong_round_msg = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.PREPARE,
                duty=duty,
                peer_idx=1,
                round=2,  # different round
                prepared_round=0,
                signature=b"0" * 65,
                value_hash=hash_value(proposal_value),
                prepared_value_hash=b"\x00" * 32,
            ),
            justification=[],
            values=[proposal_value],
        )
        (rule, just) = consensus._classify(wrong_round_msg)
        assert rule == UponRule.NOTHING
        assert len(just) == 0

        prepare_msg1 = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.PREPARE,
                duty=duty,
                peer_idx=1,
                round=1,
                prepared_round=0,
                signature=b"0" * 65,
                value_hash=hash_value(proposal_value),
                prepared_value_hash=b"\x00" * 32,
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
                prepared_round=0,
                signature=b"0" * 65,
                value_hash=hash_value(proposal_value),
                prepared_value_hash=b"\x00" * 32,
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
                prepared_round=0,
                signature=b"0" * 65,
                value_hash=b"1" * 32,  # different value hash
                prepared_value_hash=b"\x00" * 32,
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
                prepared_round=0,
                signature=b"0" * 65,
                value_hash=hash_value(proposal_value),
                prepared_value_hash=b"\x00" * 32,
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

    def test_classify_commit(self) -> None:
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

        # Commit from different round
        wrong_round_msg = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.COMMIT,
                duty=duty,
                peer_idx=1,
                round=2,  # different round
                prepared_round=0,
                signature=b"0" * 65,
                value_hash=hash_value(proposal_value),
                prepared_value_hash=b"\x00" * 32,
            ),
            justification=[],
            values=[proposal_value],
        )
        (rule, just) = consensus._classify(wrong_round_msg)
        assert rule == UponRule.NOTHING
        assert len(just) == 0

        commit_msg1 = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.COMMIT,
                duty=duty,
                peer_idx=1,
                round=1,
                prepared_round=0,
                signature=b"0" * 65,
                value_hash=hash_value(proposal_value),
                prepared_value_hash=b"\x00" * 32,
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
                prepared_round=0,
                signature=b"0" * 65,
                value_hash=hash_value(proposal_value),
                prepared_value_hash=b"\x00" * 32,
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
                prepared_round=0,
                signature=b"0" * 65,
                value_hash=b"1" * 32,  # different value hash
                prepared_value_hash=b"\x00" * 32,
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
                prepared_round=0,
                signature=b"0" * 65,
                value_hash=hash_value(proposal_value),
                prepared_value_hash=b"\x00" * 32,
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

    def test_classify_round_change(self) -> None:
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
                prepared_round=0,
                signature=b"0" * 65,
                value_hash=None,
                prepared_value_hash=b"\x00" * 32,
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
                prepared_round=0,
                signature=b"0" * 65,
                value_hash=None,
                prepared_value_hash=b"\x00" * 32,
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
                prepared_round=0,
                signature=b"0" * 65,
                value_hash=None,
                prepared_value_hash=b"\x00" * 32,
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
                prepared_round=0,
                signature=b"0" * 65,
                value_hash=prepared_value_hash,
                prepared_value_hash=b"\x00" * 32,
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

        # Send insufficient round-change messages for current round
        d = Definition(nodes=4)
        peers = create_test_peers(4)
        transport = Transport(private_key=b"test_key" * 4, peers=peers)
        consensus = QBFTConsensus(
            d=d, t=transport, duty=duty, peer=3, proposal_value=proposal_value
        )
        rc_msg1 = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.ROUND_CHANGE,
                duty=duty,
                peer_idx=3,
                round=1,
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

    def test_broadcast_message(self) -> None:
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

    def test_broadcast_round_change(self) -> None:
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
        assert res[0].msg.prepared_round == 0
        assert res[0].msg.prepared_value_hash == b"\x00" * 32
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
                prepared_round=0,
                signature=b"0" * 65,
                value_hash=prepared_value_hash,
                prepared_value_hash=b"\x00" * 32,
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

    def test_broadcast_own_pre_prepare(self) -> None:
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

    def test_change_round(self) -> None:
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
        consensus.dedup_rules[(UponRule.JUSTIFIED_PRE_PREPARE, 1)] = True

        assert consensus.round == 1
        assert len(consensus.dedup_rules) == 1
        consensus._change_round(3)
        assert consensus.round == 3
        assert len(consensus.dedup_rules) == 0

    def test_handle_message_happy_path(self) -> None:
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
                prepared_round=0,
                signature=b"0" * 65,
                value_hash=proposal_value_hash,
                prepared_value_hash=b"\x00" * 32,
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

    def test_handle_message_leader_offline_round_change(self) -> None:
        """
        Test the handle_message method for the non-happy path where the leader is offline.

        This test verifies the QBFT round change mechanism when the leader becomes unavailable.

        Scenario:
        1. Leader (node 0) sends pre-prepare to himself but no one else (offline)
        2. Two nodes (1,2) detect timeout and send round change
        3. This triggers f+1 rule (2 nodes in 4-node network, f=1) - all nodes send round change
        4. One more node (3) sends round change, triggering quorum (3 nodes)
        5. New leader (node 1) in round 2 sends pre-prepare with round-change justification
        6. Other nodes receive new pre-prepare and respond with prepare messages for round 2

        This covers the core safety property that consensus can recover from leader failures
        through the round change mechanism with proper justification and leader election.
        """
        duty = Duty(slot=102, type=1)
        d = Definition(nodes=4)
        proposal_value = b"test_block"
        peers = create_test_peers(4)
        proposal_value_hash = hash_value(proposal_value)

        # Create consensus instances for each node
        transports = []
        consensuses = []
        for i in range(4):
            transport = Transport(private_key=b"test_key" * 4, peers=peers)
            consensus = QBFTConsensus(
                d=d, t=transport, duty=duty, peer=i, proposal_value=proposal_value
            )
            transports.append(transport)
            consensuses.append(consensus)

        # Step 1: Leader (node 0) is offline - only sends pre-prepare to himself
        leader_pre_prepare = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.PRE_PREPARE,
                duty=duty,
                peer_idx=0,
                round=1,
                prepared_round=0,
                signature=b"0" * 65,
                value_hash=proposal_value_hash,
                prepared_value_hash=b"\x00" * 32,
            ),
            justification=[],
            values=[proposal_value],
        )

        # Leader processes his own pre-prepare (would normally broadcast prepare)
        res = consensuses[0].handle_message(leader_pre_prepare)
        assert len(res) == d.nodes  # leader broadcasts prepare
        assert all(m.msg.type == MsgType.PREPARE for m in res)

        # But other nodes don't receive the pre-prepare due to leader being offline
        # They timeout and decide to send round-change messages

        # Step 2: Node 1 sends round change for round 2 (timeout detected)
        rc_msg_node1 = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.ROUND_CHANGE,
                duty=duty,
                peer_idx=1,
                round=2,
                prepared_round=0,
                signature=b"0" * 65,
                value_hash=None,
                prepared_value_hash=b"\x00" * 32,
            ),
            justification=[],
            values=[],
        )

        # Node 2 also sends round change for round 2
        rc_msg_node2 = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.ROUND_CHANGE,
                duty=duty,
                peer_idx=2,
                round=2,
                prepared_round=0,
                signature=b"0" * 65,
                value_hash=None,
                prepared_value_hash=b"\x00" * 32,
            ),
            justification=[],
            values=[],
        )

        # All nodes process the first round-change message (node 1's)
        for i in range(4):
            res = consensuses[i].handle_message(rc_msg_node1)
            assert len(res) == 0  # No action yet, need f+1

        # Step 3: Process second round-change (node 2's) - triggers f+1 rule
        for i in range(4):
            res = consensuses[i].handle_message(rc_msg_node2)
            # All nodes should broadcast round-change when f+1 threshold is met
            assert len(res) == 4  # Each node broadcasts round-change to all 4 nodes
            assert all(m.msg.type == MsgType.ROUND_CHANGE for m in res)
            assert all(m.msg.round == 2 for m in res)
            assert all(m.msg.peer_idx == i for m in res)  # from current node

            # All nodes should have moved to round 2 due to f+1 rule
            assert consensuses[i].round == 2

        # Step 4: Node 3 sends round change - this triggers quorum (3 out of 4)
        rc_msg_node3 = QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.ROUND_CHANGE,
                duty=duty,
                peer_idx=3,
                round=2,
                prepared_round=0,
                signature=b"0" * 65,
                value_hash=None,
                prepared_value_hash=b"\x00" * 32,
            ),
            justification=[],
            values=[],
        )

        # Process the third round-change message and capture the pre-prepare from new leader
        new_leader_pre_prepare = None
        for i in range(4):
            res = consensuses[i].handle_message(rc_msg_node3)
            if i == 1:  # node 1 is the leader for round 2: (102+1+2)%4=1
                # Leader should broadcast pre-prepare with round-change justification
                assert len(res) == d.nodes
                assert all(m.msg.type == MsgType.PRE_PREPARE for m in res)
                assert all(m.msg.round == 2 for m in res)
                assert all(m.msg.peer_idx == 1 for m in res)  # new leader
                assert all(m.msg.prepared_round == 0 for m in res)
                assert all(len(m.justification) == 3 for m in res)  # 3 round-change messages
                assert all(
                    all(j.type == MsgType.ROUND_CHANGE for j in m.justification) for m in res
                )
                new_leader_pre_prepare = res[0]  # Capture the pre-prepare message
            else:
                # Non-leaders don't broadcast pre-prepare
                assert len(res) == 0

        # Verify that the new leader (node 1) has the correct round-change justification
        # The justification should contain the 3 round-change messages
        new_leader_consensus = consensuses[1]

        # Check that all nodes are in round 2
        for consensus in consensuses:
            assert consensus.round == 2

        # The round-change justification should be available in the buffer
        # and should contain messages from nodes 1, 2, and 3
        round_change_msgs = []
        for round_msgs in new_leader_consensus.buffer.values():
            for msg in round_msgs:
                if msg.msg.type == MsgType.ROUND_CHANGE and msg.msg.round == 2:
                    round_change_msgs.append(msg)

        assert len(round_change_msgs) >= 3  # Should have at least 3 round-change messages
        peer_indices = [msg.msg.peer_idx for msg in round_change_msgs]
        assert 1 in peer_indices  # node 1's round-change
        assert 2 in peer_indices  # node 2's round-change
        assert 3 in peer_indices  # node 3's round-change

        # Step 5: Verify that consensus can continue in round 2
        # The new leader (node 1) should have sent pre-prepare in step 4
        # Now simulate the other nodes receiving that pre-prepare and continuing consensus

        assert new_leader_pre_prepare is not None
        assert new_leader_pre_prepare.msg.round == 2
        assert new_leader_pre_prepare.msg.peer_idx == 1
        assert len(new_leader_pre_prepare.justification) == 3  # round-change justification

        # Simulate other nodes receiving the new pre-prepare and responding with prepares
        prepare_responses = []
        for i in [0, 2, 3]:  # nodes other than the leader (node 1)
            res = consensuses[i].handle_message(new_leader_pre_prepare)
            assert len(res) == 4  # should broadcast prepare
            assert all(m.msg.type == MsgType.PREPARE for m in res)
            assert all(m.msg.round == 2 for m in res)
            prepare_responses.extend(res)

        # Verify the prepare messages are for the correct value and round
        assert all(m.msg.value_hash == hash_value(proposal_value) for m in prepare_responses[:4])


class TestDecidedResendRateLimit:
    """Test rate limiting of DECIDED rebroadcasts after consensus decided."""

    def _make_decided_consensus(self) -> QBFTConsensus:
        """Create a consensus instance that has already decided."""
        duty = Duty(slot=100, type=1)
        d = Definition(nodes=4)
        proposal_value = b"test_block"
        peers = create_test_peers(4)
        transport = Transport(private_key=b"test_key" * 4, peers=peers)
        consensus = QBFTConsensus(
            d=d, t=transport, duty=duty, peer=0, proposal_value=proposal_value
        )
        consensus.q_commit = [
            QBFTMsg(
                type=MsgType.COMMIT,
                duty=duty,
                peer_idx=i,
                round=1,
                signature=b"0" * 65,
                value_hash=hash_value(proposal_value),
            )
            for i in range(3)
        ]
        return consensus

    def _round_change(
        self, consensus: QBFTConsensus, peer_idx: int, round_num: int
    ) -> QBFTConsensusMsg:
        """Build a ROUND-CHANGE message from a peer."""
        return QBFTConsensusMsg(
            msg=QBFTMsg(
                type=MsgType.ROUND_CHANGE,
                duty=consensus.duty,
                peer_idx=peer_idx,
                round=round_num,
                signature=b"0" * 65,
            ),
            justification=[],
            values=[],
        )

    def test_resend_on_new_round(self) -> None:
        """Test a post-decision ROUND-CHANGE triggers a DECIDED rebroadcast."""
        consensus = self._make_decided_consensus()

        res = consensus.handle_message(self._round_change(consensus, 1, 2))
        assert len(res) == 4
        assert all(m.msg.type == MsgType.DECIDED for m in res)

    def test_duplicate_round_not_resent(self) -> None:
        """Test the same round from the same peer triggers only one rebroadcast."""
        consensus = self._make_decided_consensus()

        assert len(consensus.handle_message(self._round_change(consensus, 1, 2))) == 4
        assert consensus.handle_message(self._round_change(consensus, 1, 2)) == []

    def test_lower_round_not_resent(self) -> None:
        """Test a lower round after a higher one does not trigger a rebroadcast."""
        consensus = self._make_decided_consensus()

        assert len(consensus.handle_message(self._round_change(consensus, 1, 5))) == 4
        assert consensus.handle_message(self._round_change(consensus, 1, 3)) == []

    def test_max_resends_per_peer(self) -> None:
        """Test at most MAX_DECIDED_RESENDS rebroadcasts per peer."""
        consensus = self._make_decided_consensus()

        for i in range(MAX_DECIDED_RESENDS):
            res = consensus.handle_message(self._round_change(consensus, 1, i + 2))
            assert len(res) == 4

        # The 17th strictly-increasing round is capped.
        assert consensus.handle_message(self._round_change(consensus, 1, 100)) == []

    def test_peers_tracked_independently(self) -> None:
        """Test the rate limit is tracked per peer."""
        consensus = self._make_decided_consensus()

        assert len(consensus.handle_message(self._round_change(consensus, 1, 2))) == 4
        assert consensus.handle_message(self._round_change(consensus, 1, 2)) == []
        # A different peer at the same round still gets served.
        assert len(consensus.handle_message(self._round_change(consensus, 2, 2))) == 4

    def test_own_round_change_not_resent(self) -> None:
        """Test our own ROUND-CHANGE does not trigger a rebroadcast."""
        consensus = self._make_decided_consensus()

        assert consensus.handle_message(self._round_change(consensus, 0, 2)) == []
