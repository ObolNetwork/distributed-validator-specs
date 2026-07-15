"""
QBFT Consensus Protocol Package

This package implements the QBFT consensus protocol for distributed validators.

Main components:
- message: Message structures and validation
- protocol: Core consensus algorithm and state machine
"""

from .definition import Definition
from .message import (
    MAX_CONSENSUS_MSG_SIZE,
    MsgType,
    QBFTConsensusMsg,
    QBFTMsg,
    verify_msg_limits,
)
from .protocol import (
    MAX_DECIDED_RESENDS,
    QBFTConsensus,
    UponRule,
)
from .transport import PeerInfo, Transport

__all__ = [
    "Definition",
    "MAX_CONSENSUS_MSG_SIZE",
    "MAX_DECIDED_RESENDS",
    "MsgType",
    "QBFTMsg",
    "QBFTConsensusMsg",
    "QBFTConsensus",
    "UponRule",
    "Transport",
    "PeerInfo",
    "verify_msg_limits",
]
