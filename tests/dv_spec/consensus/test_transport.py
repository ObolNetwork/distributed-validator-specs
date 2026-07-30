"""
Test suite for Transport class implementation
"""

from unittest.mock import MagicMock, patch

import pytest

from dv_spec.subspecs.consensus.qbft.message import MsgType, QBFTConsensusMsg, QBFTMsg
from dv_spec.subspecs.consensus.qbft.transport import PeerInfo, Transport
from dv_spec.types import Duty


class TestTransport:
    """Test cases for the Transport class."""

    def test_transport_initialization(self) -> None:
        """Test Transport initialization."""
        private_key = b"test_private_key" * 2  # 32 bytes
        peers = [
            PeerInfo(peer_idx=i, public_key=b"test_key", peer_id=f"peer_{i}") for i in range(4)
        ]
        transport = Transport(private_key=private_key, peers=peers)

        assert transport.private_key == private_key
        assert transport.peers == peers
        assert transport.num_peers == 4
        assert transport.values == {}

    def test_set_values(self) -> None:
        """Test setting value mappings."""
        peers = [
            PeerInfo(peer_idx=i, public_key=b"test_key", peer_id=f"peer_{i}") for i in range(4)
        ]
        transport = Transport(private_key=b"test_key" * 4, peers=peers)

        # Test initial empty state
        assert transport.values == {}

        # Test setting values
        test_values = {b"hash1": b"value1", b"hash2": b"value2"}
        transport.set_values(test_values)

        assert transport.values == test_values

        # Test updating values
        additional_values = {b"hash3": b"value3"}
        transport.set_values(additional_values)

        expected = {b"hash1": b"value1", b"hash2": b"value2", b"hash3": b"value3"}
        assert transport.values == expected

    def test_get_value(self) -> None:
        """Test retrieving values by hash."""

        peers = [
            PeerInfo(peer_idx=i, public_key=b"test_key", peer_id=f"peer_{i}") for i in range(4)
        ]
        transport = Transport(private_key=b"test_key" * 4, peers=peers)

        # Test getting non-existent value
        assert transport.get_value(b"nonexistent") is None

        # Test setting and getting values
        test_values = {b"hash1": b"value1", b"hash2": b"value2"}
        transport.set_values(test_values)

        assert transport.get_value(b"hash1") == b"value1"
        assert transport.get_value(b"hash2") == b"value2"
        assert transport.get_value(b"hash3") is None

    def test_sign_message_basic(self) -> None:
        """Test basic message signing functionality."""

        peers = [
            PeerInfo(peer_idx=i, public_key=b"test_key", peer_id=f"peer_{i}") for i in range(4)
        ]
        transport = Transport(private_key=b"test_key" * 4, peers=peers)

        # Create a message without signature
        duty = Duty(slot=100, type=1)
        msg = QBFTMsg(
            type=MsgType.PREPARE,
            duty=duty,
            peer_idx=0,
            round=1,
            value_hash=b"test_hash" + b"\x00" * 23,  # 32 bytes total
            prepared_round=0,
            prepared_value_hash=b"\x00" * 32,
            signature=None,
        )
        signature = transport._sign_message(msg)
        assert isinstance(signature, bytes)
        assert len(signature) == 65

    def test_sign_message_with_existing_signature_fails(self) -> None:
        """Test that signing fails if message already has signature."""

        peers = [
            PeerInfo(peer_idx=i, public_key=b"test_key", peer_id=f"peer_{i}") for i in range(4)
        ]
        transport = Transport(private_key=b"test_key" * 4, peers=peers)

        # Create message with existing signature
        duty = Duty(slot=100, type=1)
        msg = QBFTMsg(
            type=MsgType.PREPARE,
            duty=duty,
            peer_idx=0,
            round=1,
            value_hash=b"test_hash" + b"\x00" * 23,  # 32 bytes total
            prepared_round=0,
            prepared_value_hash=b"\x00" * 32,
            signature=b"existing_signature" + b"\x00" * 47,  # 65 bytes total
        )

        # Test that signing fails
        with pytest.raises(
            ValueError, match="Message should not have signature set before signing"
        ):
            transport._sign_message(msg)

    def test_broadcast_message_prepare(self) -> None:
        """Test broadcasting PREPARE messages."""

        peers = [
            PeerInfo(peer_idx=i, public_key=b"test_key", peer_id=f"peer_{i}") for i in range(4)
        ]
        transport = Transport(private_key=b"test_key" * 4, peers=peers)

        # Set up test value
        value_hash = b"test_value_hash" + b"\x00" * 17  # 32 bytes total
        transport.set_values({value_hash: b"test_value"})

        duty = Duty(slot=100, type=1)
        justification: list[QBFTMsg] = []

        # Test broadcast
        result = transport.broadcast_message(
            msg_type=MsgType.PREPARE,
            duty=duty,
            peer_idx=0,
            round_num=1,
            value_hash=value_hash,
            justification=justification,
        )

        # Should create one message per peer
        assert len(result) == 4

        # Check each message
        for consensus_msg in result:
            assert isinstance(consensus_msg, QBFTConsensusMsg)
            assert consensus_msg.msg.type == MsgType.PREPARE
            assert consensus_msg.msg.duty == duty
            assert consensus_msg.msg.peer_idx == 0
            assert consensus_msg.msg.round == 1
            assert consensus_msg.msg.value_hash == value_hash
            assert consensus_msg.msg.signature is not None
            assert len(consensus_msg.msg.signature) == 65
            assert consensus_msg.justification == justification
            assert b"test_value" in consensus_msg.values

    def test_broadcast_pre_prepare(self) -> None:
        """Test broadcasting PRE_PREPARE messages."""

        peers = [
            PeerInfo(peer_idx=i, public_key=b"test_key", peer_id=f"peer_{i}") for i in range(4)
        ]
        transport = Transport(private_key=b"test_key" * 4, peers=peers)

        duty = Duty(slot=100, type=1)
        value_hash = b"proposal_hash" + b"\x00" * 19  # 32 bytes total
        justification = [
            QBFTMsg(
                type=MsgType.ROUND_CHANGE,
                duty=duty,
                peer_idx=1,
                round=2,
                value_hash=None,
                prepared_round=0,
                prepared_value_hash=b"\x00" * 32,
                signature=b"rc_sig" + b"\x00" * 59,  # 65 bytes total
            )
        ]

        # Set up proposal value
        transport.set_values({value_hash: b"proposal_value"})

        result = transport.broadcast_pre_prepare(
            duty=duty, peer_idx=2, round_num=2, value_hash=value_hash, justification=justification
        )

        assert len(result) == 4

        for consensus_msg in result:
            assert consensus_msg.msg.type == MsgType.PRE_PREPARE
            assert consensus_msg.msg.duty == duty
            assert consensus_msg.msg.peer_idx == 2
            assert consensus_msg.msg.round == 2
            assert consensus_msg.msg.value_hash == value_hash
            assert consensus_msg.msg.signature is not None
            assert len(consensus_msg.msg.signature) == 65
            assert consensus_msg.justification == justification
            assert b"proposal_value" in consensus_msg.values

    def test_empty_peers_list(self) -> None:
        """Test transport with empty peers list."""

        transport = Transport(private_key=b"test_key" * 4, peers=[])

        assert transport.num_peers == 0

        # Broadcasting with no peers should return empty list
        duty = Duty(slot=100, type=1)
        result = transport.broadcast_message(
            msg_type=MsgType.PREPARE, duty=duty, peer_idx=0, round_num=1, value_hash=b"hash"
        )

        assert result == []

    def test_peer_info_creation(self) -> None:
        """Test creating PeerInfo instances."""

        peer = PeerInfo(peer_idx=0, public_key=b"test_key", peer_id="peer_0")
        assert peer.peer_idx == 0
        assert peer.public_key == b"test_key"
        assert peer.peer_id == "peer_0"

    def test_peer_info_equality(self) -> None:
        """Test PeerInfo equality."""

        peer1 = PeerInfo(peer_idx=0, public_key=b"test_key", peer_id="peer_0")
        peer2 = PeerInfo(peer_idx=0, public_key=b"test_key", peer_id="peer_0")
        peer3 = PeerInfo(peer_idx=1, public_key=b"test_key", peer_id="peer_0")

        assert peer1 == peer2
        assert peer1 != peer3

    def test_transport_private_key_access(self) -> None:
        """Test that private key is properly stored and accessible."""

        private_key = b"secret_key_bytes_here_32_chars"
        peers = [
            PeerInfo(peer_idx=i, public_key=b"test_key", peer_id=f"peer_{i}") for i in range(4)
        ]
        transport = Transport(private_key=private_key, peers=peers)

        assert transport.private_key == private_key

    def test_peers_list_access(self) -> None:
        """Test that peers list is properly stored and accessible."""

        peers = [
            PeerInfo(peer_idx=i, public_key=b"test_key", peer_id=f"peer_{i}") for i in range(5)
        ]
        transport = Transport(private_key=b"test_key" * 4, peers=peers)

        assert transport.peers == peers
        assert len(transport.peers) == 5

        # Test individual peer access
        for i, peer in enumerate(transport.peers):
            assert peer.peer_idx == i
            assert peer.peer_id == f"peer_{i}"
