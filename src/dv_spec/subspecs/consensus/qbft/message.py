"""
QBFT Consensus Protocol - Message Definitions

This module defines the message structures used in the QBFT consensus protocol
for distributed validators.
"""

from enum import IntEnum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

from dv_spec.types import Duty


class MsgType(IntEnum):
    """QBFT message types."""
    PRE_PREPARE = 1
    PREPARE = 2
    COMMIT = 3
    ROUND_CHANGE = 4
    DECIDED = 5

class QBFTMsg(BaseModel):
    """A message in the QBFT consensus protocol."""
    type: MsgType = Field(description="The type of QBFT message.")
    duty: Duty = Field(description="The duty associated with the message.")
    peer_idx: int = Field(description="The index of the peer sending the message.")
    round: int = Field(description="The round number for the message.")
    prepared_round: Optional[int] = Field(
        default=None,
        description="The prepared round number. None indicates no preparation has occurred."
    )
    signature: bytes = Field(description="The signature of the message.")
    value_hash: bytes = Field(description="The hash of the value being proposed.")
    prepared_value_hash: Optional[bytes] = Field(
        default=None,
        description="The hash of the prepared value."
    )

    @field_validator('peer_idx')
    def validate_peer_idx(cls, v: int) -> int:
        """Ensure peer_idx is non-negative."""
        if v < 0:
            raise ValueError("peer_idx must be >= 0")
        return v

    @field_validator('round')
    def validate_round(cls, v: int) -> int:
        """Ensure round is positive."""
        if v < 1:
            raise ValueError("round must be >= 1")
        return v

    @field_validator('prepared_round')
    def validate_prepared_round(cls, v: Optional[int], info) -> Optional[int]:
        """
        Validate prepared_round constraints.
        
        Rules:
        1. If not None, prepared_round must be >= 1
        2. If not None, prepared_round must be <= current round
        3. None indicates no previous value prepared
        """
        # None is always valid
        if v is None:
            return v

        if v < 1:
            raise ValueError("prepared_round must be >= 1 when not None")

        if info.data and 'round' in info.data:
            current_round = info.data['round']
            if v > current_round:
                raise ValueError(f"prepared_round ({v}) must be <= current round ({current_round})")

        return v

    @field_validator('signature')
    def validate_signature(cls, v: bytes) -> bytes:
        """Ensure signature is 65 bytes ("Ethereum R S V" format)"""
        if len(v) != 65:
            raise ValueError("signature must be 65 bytes")
        return v

    @field_validator('value_hash')
    def validate_value_hash(cls, v: bytes) -> bytes:
        """Ensure hash is 32 bytes"""
        if len(v) != 32:
            raise ValueError("value_hash must be 32 bytes")
        return v

    @field_validator('prepared_value_hash')
    def validate_prepared_value_hash(cls, v: Optional[bytes], info) -> Optional[bytes]:
        """
        Validate prepared_value_hash constraints.
        
        Rules:
        1. If not None, prepared_value_hash must be 32 bytes
        2. None indicates no previous value prepared
        """
        if v is not None and len(v) != 32:
            raise ValueError("prepared_value_hash must be 32 bytes")
        if v is None and info.data and 'prepared_round' in info.data:
            prepared_round = info.data['prepared_round']
            if prepared_round is not None:
                raise ValueError("prepared_value_hash cannot be None when prepared_round is set")
        return v

class QBFTConsensusMsg(BaseModel):
    """A consensus message containing a QBFT message and its justifications."""
    msg: QBFTMsg = Field(description="The main QBFT message being sent.")
    justification: list[QBFTMsg] = Field(
        default_factory=list,
        description="Supporting messages proving validity of this message"
    )
    values: list[Any] = Field(
        default_factory=list,
        description="Actual consensus values referenced by value hashes"
    )

    @field_validator('justification')
    def validate_justification(cls, v: list[QBFTMsg], info) -> list[QBFTMsg]:
        """
        Validate justification given specific message type.
        This is basic validation only. Detailed verification occurs in protocol.py.
        """
        if not info.data or 'msg' not in info.data:
            raise ValueError("msg must be provided in validation context")

        msg = info.data['msg']

        if msg.type == MsgType.PRE_PREPARE:
            # PRE-PREPARE messages shouldn't have justifications in round 1
            if msg.round == 1 and v:
                raise ValueError("PRE-PREPARE messages in round 1 should not have justifications")
            # PRE-PREPARE messages should have justifications in rounds > 1
            if msg.round > 1 and not v:
                raise ValueError("PRE-PREPARE messages in rounds > 1 require justifications")

        elif msg.type == MsgType.PREPARE:
            # PREPARE messages should have PRE-PREPARE justification
            if not any(just.type == MsgType.PRE_PREPARE and
                       just.duty == msg.duty and
                       just.round == msg.round for just in v):
                raise ValueError("PREPARE messages require a matching PRE-PREPARE justification")

        elif msg.type == MsgType.COMMIT:
            # COMMIT messages should have PREPARE justifications
            if not any(just.type == MsgType.PREPARE and
                       just.duty == msg.duty and
                       just.round == msg.round for just in v):
                raise ValueError("COMMIT messages require PREPARE justifications")

        elif msg.type == MsgType.ROUND_CHANGE:
            # ROUND-CHANGE messages don't need justification when no prepared value is present
            if msg.prepared_round is None and msg.prepared_value_hash is None:
                if v:
                    raise ValueError("ROUND-CHANGE with no prepared value should not have justifications")
            else:
                # Has prepared value: should have justifications
                if not v:
                    raise ValueError("ROUND-CHANGE with prepared value requires justifications")

            return v

        elif msg.type == MsgType.DECIDED:
            # DECIDED messages should have COMMIT justifications
            if not any(just.type == MsgType.COMMIT
                       and just.duty == msg.duty
                       and just.round == msg.round for just in v):
                raise ValueError("DECIDED messages require COMMIT justifications")

        return v
