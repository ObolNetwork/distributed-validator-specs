"""
QBFT Consensus Protocol Package

This package implements the QBFT consensus protocol for distributed validators.

Main components:
- message: Message structures and validation
- protocol: Core consensus algorithm and state machine
"""

from .definition import Definition
from .message import (
    MsgType,
    QBFTConsensusMsg,
    QBFTMsg,
)
from .protocol import (
    QBFTConsensus,
    UponRule,
)
from .transport import PeerInfo, Transport

__all__ = [
    "Definition",
    "MsgType",
    "QBFTMsg",
    "QBFTConsensusMsg",
    "QBFTConsensus",
    "UponRule",
    "Transport",
    "PeerInfo",
]
