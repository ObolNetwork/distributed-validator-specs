"""
Test suite for QBFT Message types and validation.

This module contains tests for QBFT message.
"""

import pytest

from dv_spec.subspecs.consensus.qbft.message import (
    MAX_CONSENSUS_MSG_SIZE,
    MsgType,
    QBFTConsensusMsg,
    QBFTMsg,
    verify_msg_limits,
)
from dv_spec.types import Duty, DutyType


class TestQBFTMsg:
    """Test QBFT message functionality."""

    def test_pre_prepare_message_creation(self) -> None:
        """Test creating a PRE-PREPARE message."""
        duty = Duty(slot=100, type=DutyType.PROPOSER)
        msg = QBFTMsg(
            type=MsgType.PRE_PREPARE,
            duty=duty,
            peer_idx=0,
            round=1,
            prepared_round=0,
            signature=b"s" * 65,  # 65 bytes
            value_hash=b"a" * 32,  # 32 bytes
            prepared_value_hash=b"\x00" * 32,
        )

        assert msg.type == MsgType.PRE_PREPARE
        assert msg.duty == duty
        assert msg.peer_idx == 0
        assert msg.round == 1
        assert msg.prepared_round == 0
        assert msg.signature is not None and len(msg.signature) == 65
        assert msg.value_hash is not None and len(msg.value_hash) == 32
        assert msg.prepared_value_hash == b"\x00" * 32

    def test_prepare_message_creation(self) -> None:
        """Test creating a PREPARE message."""
        duty = Duty(slot=100, type=DutyType.PROPOSER)
        QBFTMsg(
            type=MsgType.PREPARE,
            duty=duty,
            peer_idx=1,
            round=1,
            prepared_round=0,
            signature=b"s" * 65,
            value_hash=b"a" * 32,
            prepared_value_hash=b"\x00" * 32,
        )

    def test_commit_message_creation(self) -> None:
        """Test creating a COMMIT message."""
        duty = Duty(slot=100, type=DutyType.PROPOSER)
        QBFTMsg(
            type=MsgType.COMMIT,
            duty=duty,
            peer_idx=2,
            round=1,
            prepared_round=1,
            signature=b"s" * 65,
            value_hash=b"a" * 32,
            prepared_value_hash=b"a" * 32,
        )

    def test_round_change_message_creation(self) -> None:
        """Test creating a ROUND_CHANGE message."""
        duty = Duty(slot=100, type=DutyType.PROPOSER)
        QBFTMsg(
            type=MsgType.ROUND_CHANGE,
            duty=duty,
            peer_idx=3,
            round=1,
            prepared_round=1,
            signature=b"s" * 65,
            value_hash=b"\x00" * 32,
            prepared_value_hash=b"a" * 32,
        )

    def test_decided_message_creation(self) -> None:
        """Test creating a DECIDED message."""
        duty = Duty(slot=100, type=DutyType.PROPOSER)
        QBFTMsg(
            type=MsgType.DECIDED,
            duty=duty,
            peer_idx=0,
            round=1,
            prepared_round=1,
            signature=b"s" * 65,
            value_hash=b"a" * 32,
            prepared_value_hash=b"a" * 32,
        )

    def test_message_equality(self) -> None:
        """Test message equality comparison."""
        duty = Duty(slot=100, type=DutyType.PROPOSER)

        msg1 = QBFTMsg(
            type=MsgType.PREPARE,
            duty=duty,
            peer_idx=1,
            round=1,
            prepared_round=0,
            signature=b"s" * 65,
            value_hash=b"a" * 32,
            prepared_value_hash=b"\x00" * 32,
        )

        msg2 = QBFTMsg(
            type=MsgType.PREPARE,
            duty=duty,
            peer_idx=1,
            round=1,
            prepared_round=0,
            signature=b"s" * 65,
            value_hash=b"a" * 32,
            prepared_value_hash=b"\x00" * 32,
        )

        msg3 = QBFTMsg(
            type=MsgType.PREPARE,
            duty=duty,
            peer_idx=2,  # Different peer
            round=1,
            prepared_round=0,
            signature=b"s" * 65,
            value_hash=b"a" * 32,
            prepared_value_hash=b"\x00" * 32,
        )

        assert msg1 == msg2
        assert msg1 != msg3


class TestMsgType:
    """Test MsgType enum functionality."""

    def test_message_type_values(self) -> None:
        """Test that message types have expected values."""
        assert MsgType.PRE_PREPARE.value == 1
        assert MsgType.PREPARE.value == 2
        assert MsgType.COMMIT.value == 3
        assert MsgType.ROUND_CHANGE.value == 4
        assert MsgType.DECIDED.value == 5

    def test_message_type_names(self) -> None:
        """Test that message types have expected names."""
        assert MsgType.PRE_PREPARE.name == "PRE_PREPARE"
        assert MsgType.PREPARE.name == "PREPARE"
        assert MsgType.COMMIT.name == "COMMIT"
        assert MsgType.ROUND_CHANGE.name == "ROUND_CHANGE"
        assert MsgType.DECIDED.name == "DECIDED"


class TestDutyType:
    """Test DutyType enum functionality."""

    def test_duty_type_values(self) -> None:
        """Test that duty types have expected values."""
        assert DutyType.PROPOSER.value == 1
        assert DutyType.ATTESTER.value == 2
        assert DutyType.AGGREGATOR.value == 9
        assert DutyType.SYNC_MESSAGE.value == 10

    def test_duty_type_names(self) -> None:
        """Test that duty types have expected names."""
        assert DutyType.PROPOSER.name == "PROPOSER"
        assert DutyType.ATTESTER.name == "ATTESTER"
        assert DutyType.AGGREGATOR.name == "AGGREGATOR"
        assert DutyType.SYNC_MESSAGE.name == "SYNC_MESSAGE"


class TestVerifyMsgLimits:
    """Test consensus message justification/value count limits."""

    def _make_msg(self, num_justifications: int, num_values: int) -> QBFTConsensusMsg:
        """Build a consensus message with given justification/value counts."""
        duty = Duty(slot=100, type=DutyType.ATTESTER)
        msg = QBFTMsg(
            type=MsgType.PRE_PREPARE,
            duty=duty,
            peer_idx=0,
            round=1,
            value_hash=b"\x01" * 32,
            signature=b"0" * 65,
        )
        justification = [
            QBFTMsg(
                type=MsgType.ROUND_CHANGE,
                duty=duty,
                peer_idx=i % 4,
                round=1,
                signature=b"0" * 65,
            )
            for i in range(num_justifications)
        ]
        values = [bytes([i % 256]) for i in range(num_values)]
        return QBFTConsensusMsg(msg=msg, justification=justification, values=values)

    def test_max_consensus_msg_size(self) -> None:
        """Test the wire size limit constant."""
        assert MAX_CONSENSUS_MSG_SIZE == 32 * 1024 * 1024

    def test_within_limits(self) -> None:
        """Test messages within limits pass."""
        # No justifications, one value: max values = 2 * (0 + 1) = 2
        verify_msg_limits(self._make_msg(0, 2), nodes=4)
        # Full quorum of round-changes plus prepares: 2 * 4 = 8 justifications
        verify_msg_limits(self._make_msg(8, 18), nodes=4)

    def test_too_many_justifications(self) -> None:
        """Test justification count above 2*nodes is rejected."""
        with pytest.raises(ValueError, match="too many justifications"):
            verify_msg_limits(self._make_msg(9, 0), nodes=4)

    def test_too_many_values(self) -> None:
        """Test value count above 2*(justifications+1) is rejected."""
        with pytest.raises(ValueError, match="too many values"):
            verify_msg_limits(self._make_msg(0, 3), nodes=4)
        with pytest.raises(ValueError, match="too many values"):
            verify_msg_limits(self._make_msg(2, 7), nodes=4)
