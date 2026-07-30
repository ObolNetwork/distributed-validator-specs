"""
QBFT Consensus Protocol - Message Definitions

This module defines the message structures used in the QBFT consensus protocol
for distributed validators.
"""

from enum import IntEnum
from typing import Optional

from pydantic import BaseModel, Field, ValidationInfo, field_validator

from dv_spec.types import Duty


class MsgType(IntEnum):
    """QBFT message types."""

    PRE_PREPARE = 1
    PREPARE = 2
    COMMIT = 3
    ROUND_CHANGE = 4
    DECIDED = 5


MAX_CONSENSUS_MSG_SIZE = 32 * 1024 * 1024  # 32 MB
"""Maximum wire size of an incoming consensus message.

Receivers MUST enforce this as a stream read limit before decoding, so a
malicious peer cannot exhaust memory with an oversized message. The cap is
well above the largest legitimate message (a DECIDED carrying a full quorum
of COMMIT justifications plus a beacon block value)."""


class QBFTMsg(BaseModel):
    """A message in the QBFT consensus protocol."""

    type: MsgType = Field(description="The type of QBFT message.")
    duty: Duty = Field(description="The duty associated with the message.")
    peer_idx: int = Field(description="The index of the peer sending the message.")
    round: int = Field(description="The round number for the message.")
    prepared_round: int = Field(
        default=0,
        description="The prepared round number. 0 indicates no preparation has occurred.",
    )
    signature: Optional[bytes] = Field(default=None, description="The signature of the message.")
    value_hash: Optional[bytes] = Field(
        default=None, description="The hash of the value being proposed."
    )
    prepared_value_hash: bytes = Field(
        default=b"\x00" * 32,
        description=(
            "The hash of the prepared value. Zero hash (32 zero bytes) indicates no prepared value."
        ),
    )

    @field_validator("peer_idx")
    @classmethod
    def validate_peer_idx(cls, v: int) -> int:
        """Ensure peer_idx is non-negative."""
        if v < 0:
            raise ValueError("peer_idx must be >= 0")
        return v

    @field_validator("round")
    @classmethod
    def validate_round(cls, v: int) -> int:
        """Ensure round is positive."""
        if v < 1:
            raise ValueError("round must be >= 1")
        return v

    @field_validator("prepared_round")
    @classmethod
    def validate_prepared_round(cls, v: int, info: ValidationInfo) -> int:
        """
        Validate prepared_round constraints.

        Rules:
        1. prepared_round must be >= 0
        2. prepared_round must be <= current round
        3. 0 indicates no previous value prepared
        """
        if v < 0:
            raise ValueError("prepared_round must be >= 0")

        if info.data and "round" in info.data:
            current_round = info.data["round"]
            if v > current_round:
                raise ValueError(f"prepared_round ({v}) must be <= current round ({current_round})")

        return v

    @field_validator("signature")
    @classmethod
    def validate_signature(cls, v: Optional[bytes]) -> Optional[bytes]:
        """Ensure signature is 65 bytes ("Ethereum R S V" format)"""
        if v is not None and len(v) != 65:
            raise ValueError("signature must be 65 bytes")
        return v

    @field_validator("value_hash")
    @classmethod
    def validate_value_hash(cls, v: Optional[bytes]) -> Optional[bytes]:
        """Ensure hash is 32 bytes"""
        if v is not None and len(v) != 32:
            raise ValueError("value_hash must be 32 bytes")
        return v

    @field_validator("prepared_value_hash")
    @classmethod
    def validate_prepared_value_hash(cls, v: bytes, info: ValidationInfo) -> bytes:
        """
        Validate prepared_value_hash constraints.

        Rules:
        1. prepared_value_hash must be 32 bytes
        2. Zero hash (32 zero bytes) indicates no previous value prepared
        3. prepared_value_hash must be zero hash if prepared_round is 0
        4. prepared_value_hash must be non-zero if prepared_round > 0
        """
        if len(v) != 32:
            raise ValueError("prepared_value_hash must be 32 bytes")

        is_zero_hash = v == b"\x00" * 32

        if info.data and "prepared_round" in info.data:
            prepared_round = info.data["prepared_round"]
            if prepared_round == 0 and not is_zero_hash:
                raise ValueError("prepared_value_hash must be zero hash when prepared_round is 0")
            if prepared_round > 0 and is_zero_hash:
                raise ValueError("prepared_value_hash must be non-zero when prepared_round > 0")

        return v


class QBFTConsensusMsg(BaseModel):
    """A consensus message containing a QBFT message and its justifications."""

    msg: QBFTMsg = Field(description="The main QBFT message being sent.")
    justification: list[QBFTMsg] = Field(
        default_factory=list, description="Supporting messages proving validity of this message"
    )
    values: list[bytes] = Field(
        default_factory=list,
        description=(
            "Consensus values referenced by value hashes, as deterministic "
            "protobuf encodings (Any-wrapped on the wire)"
        ),
    )


def verify_msg_limits(consensus_msg: QBFTConsensusMsg, nodes: int) -> None:
    """Bound the justification and value counts of a consensus message.

    Receivers MUST apply these limits before any expensive per-element work
    (each justification requires a signature verification/recovery, each value
    a decode + hash). Without them a single authenticated peer could pack one
    large message with many sub-messages to exhaust CPU/memory on every peer
    (amplification DoS).

    Limits:
    - A legitimate justification set contains at most a quorum of ROUND-CHANGE
      plus a quorum of PREPARE messages, bounded above by ``2 * nodes``.
    - Each message (the main message plus each justification) references at
      most two values (value and prepared value), so values are bounded by
      ``2 * (justifications + 1)``.

    Raises:
        ValueError: If the message exceeds either limit.
    """
    max_justifications = 2 * nodes
    if len(consensus_msg.justification) > max_justifications:
        raise ValueError(
            f"too many justifications: {len(consensus_msg.justification)} "
            f"(max {max_justifications})"
        )

    max_values = 2 * (len(consensus_msg.justification) + 1)
    if len(consensus_msg.values) > max_values:
        raise ValueError(f"too many values: {len(consensus_msg.values)} (max {max_values})")
