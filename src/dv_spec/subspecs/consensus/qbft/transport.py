"""
Network transport abstraction for QBFT consensus.

This module provides interfaces and implementations for message transport
in distributed consensus systems.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from dv_spec.subspecs.consensus.cryptography import hash_value, sign
from dv_spec.subspecs.consensus.qbft.message import MsgType, QBFTConsensusMsg, QBFTMsg
from dv_spec.types import Duty


@dataclass
class PeerInfo:
    """Information about a peer in the consensus cluster."""

    peer_idx: int
    """Index of this peer in the cluster."""

    public_key: bytes
    """Public key for signature verification (placeholder)."""

    peer_id: str
    """Identifier for this peer (placeholder)."""


class Transport:
    """Transport layer for QBFT consensus messages."""

    private_key: bytes
    """Private key used for signing messages."""

    peers: List[PeerInfo]
    """List of peers in the consensus cluster."""

    values: Dict[bytes, Any]
    """Mapping of value hashes to their corresponding values."""

    def __init__(self, private_key: bytes, peers: List[PeerInfo]):
        """Initialize transport with private key and peer information."""
        self.private_key = private_key
        self.peers = peers
        self.values = {}

    @property
    def num_peers(self) -> int:
        """Number of peers in the cluster."""
        return len(self.peers)

    def set_values(self, values: Dict[bytes, Any]) -> None:
        """Set the mapping of value hashes to their corresponding values."""
        self.values.update(values)

    def get_value(self, value_hash: bytes) -> Optional[Any]:
        """Retrieve the value corresponding to a given hash."""
        return self.values.get(value_hash, None)

    def _sign_message(self, msg: QBFTMsg) -> bytes:
        """Sign a QBFT message. Message should not have signature set."""
        if msg.signature is not None:
            raise ValueError("Message should not have signature set before signing")

        # Hash the message content (signature is None so it's excluded)
        msg_hash = hash_value(msg.model_dump())

        # Sign the hash
        return sign(msg_hash, self.private_key)

    def broadcast_message(
        self,
        msg_type: MsgType,
        duty: Duty,
        peer_idx: int,
        round_num: int,
        value_hash: bytes,
        justification: Optional[List[QBFTMsg]] = None,
        prepared_round: Optional[int] = None,
        prepared_value_hash: Optional[bytes] = None,
    ) -> List[QBFTConsensusMsg]:
        """
        Create and broadcast QBFT messages for current round.

        Args:
            msg_type: Type of QBFT message to broadcast
            duty: The duty being agreed upon
            peer_idx: Index of this peer in the cluster
            round_num: Current round number
            value_hash: Hash of the value being proposed
            justification: Supporting messages for this broadcast
            prepared_round: Prepared round for ROUND_CHANGE messages
            prepared_value_hash: Prepared value hash for ROUND_CHANGE messages

        Returns:
            List of consensus messages ready for broadcast
        """
        result: List[QBFTConsensusMsg] = []

        # Create one message for each peer in the cluster
        for _ in range(self.num_peers):
            # Create the base message without signature
            msg = QBFTMsg(
                type=msg_type,
                duty=duty,
                peer_idx=peer_idx,
                round=round_num,
                value_hash=value_hash if msg_type != MsgType.ROUND_CHANGE else None,
                prepared_round=prepared_round if prepared_round is not None else 0,
                prepared_value_hash=(
                    prepared_value_hash if prepared_value_hash is not None else b"\x00" * 32
                ),
                signature=None,  # Will be set after signing
            )

            # Sign the message
            msg.signature = self._sign_message(msg)

            # Get the actual value for the consensus message if available
            values = set()
            if value_hash and value_hash in self.values:
                values.add(self.values[value_hash])
            if prepared_value_hash and prepared_value_hash in self.values:
                values.add(self.values[prepared_value_hash])

            # Create consensus message
            consensus_msg = QBFTConsensusMsg(
                msg=msg, justification=justification or [], values=list(values)
            )

            result.append(consensus_msg)

        return result

    def broadcast_round_change(
        self,
        duty: Duty,
        peer_idx: int,
        round_num: int,
        prepared_round: Optional[int] = None,
        prepared_value_hash: Optional[bytes] = None,
        prepared_justification: Optional[List[QBFTMsg]] = None,
    ) -> List[QBFTConsensusMsg]:
        """
        Broadcast ROUND_CHANGE message for current round.

        Args:
            duty: The duty being agreed upon
            peer_idx: Index of this peer in the cluster
            round_num: Current round number
            prepared_round: Previously prepared round if any
            prepared_value_hash: Previously prepared value hash if any
            prepared_justification: Justification for prepared value if any

        Returns:
            List of consensus messages ready for broadcast
        """
        result = []

        # Create one message for each peer in the cluster
        for _ in range(self.num_peers):
            msg = QBFTMsg(
                type=MsgType.ROUND_CHANGE,
                duty=duty,
                peer_idx=peer_idx,
                round=round_num,
                prepared_round=prepared_round if prepared_round is not None else 0,
                prepared_value_hash=(
                    prepared_value_hash if prepared_value_hash is not None else b"\x00" * 32
                ),
                value_hash=None,  # ROUND_CHANGE messages don't have value_hash
                signature=None,  # Will be set after signing
            )

            # Sign the message
            msg.signature = self._sign_message(msg)

            # Get values if available
            values = []
            if prepared_value_hash and prepared_value_hash in self.values:
                values.append(self.values[prepared_value_hash])

            consensus_msg = QBFTConsensusMsg(
                msg=msg, justification=prepared_justification or [], values=values
            )

            result.append(consensus_msg)

        return result

    def broadcast_pre_prepare(
        self,
        duty: Duty,
        peer_idx: int,
        round_num: int,
        value_hash: bytes,
        justification: List[QBFTMsg],
    ) -> List[QBFTConsensusMsg]:
        """
        Broadcast PRE_PREPARE message using own proposal value.

        Args:
            duty: The duty being agreed upon
            peer_idx: Index of this peer in the cluster
            round_num: Current round number
            value_hash: Hash of the value being proposed
            justification: Required justification for the PRE_PREPARE

        Returns:
            List of consensus messages ready for broadcast
        """
        return self.broadcast_message(
            msg_type=MsgType.PRE_PREPARE,
            duty=duty,
            peer_idx=peer_idx,
            round_num=round_num,
            value_hash=value_hash,
            justification=justification,
        )
