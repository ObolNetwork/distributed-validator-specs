"""
Test suite for QBFT Message types and validation.

This module contains tests for QBFT message.
"""

from dv_spec.subspecs.consensus.qbft.message import MsgType, QBFTMsg
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
            prepared_round=None,
            signature=b"s" * 65,  # 65 bytes
            value_hash=b"a" * 32,  # 32 bytes
            prepared_value_hash=None,
        )

        assert msg.type == MsgType.PRE_PREPARE
        assert msg.duty == duty
        assert msg.peer_idx == 0
        assert msg.round == 1
        assert msg.prepared_round is None
        assert msg.signature is not None and len(msg.signature) == 65
        assert msg.value_hash is not None and len(msg.value_hash) == 32
        assert msg.prepared_value_hash is None

    def test_prepare_message_creation(self) -> None:
        """Test creating a PREPARE message."""
        duty = Duty(slot=100, type=DutyType.PROPOSER)
        QBFTMsg(
            type=MsgType.PREPARE,
            duty=duty,
            peer_idx=1,
            round=1,
            prepared_round=None,
            signature=b"s" * 65,
            value_hash=b"a" * 32,
            prepared_value_hash=None,
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
            prepared_round=None,
            signature=b"s" * 65,
            value_hash=b"a" * 32,
            prepared_value_hash=None,
        )

        msg2 = QBFTMsg(
            type=MsgType.PREPARE,
            duty=duty,
            peer_idx=1,
            round=1,
            prepared_round=None,
            signature=b"s" * 65,
            value_hash=b"a" * 32,
            prepared_value_hash=None,
        )

        msg3 = QBFTMsg(
            type=MsgType.PREPARE,
            duty=duty,
            peer_idx=2,  # Different peer
            round=1,
            prepared_round=None,
            signature=b"s" * 65,
            value_hash=b"a" * 32,
            prepared_value_hash=None,
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
