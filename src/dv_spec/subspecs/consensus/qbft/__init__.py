"""
QBFT Consensus Protocol Package

This package implements the QBFT consensus protocol for distributed validators.

Main components:
- message: Message structures and validation
- protocol: Core consensus algorithm and state machine
"""

from .message import (
    MsgType,
    QBFTConsensusMsg,
    QBFTMsg,
)
from .protocol import (
    QBFTConsensus,
    UponRule,
)

__all__ = [
    "MsgType",
    "QBFTMsg",
    "QBFTConsensusMsg",
    "UponRule",
    "QBFTConsensus",
]
