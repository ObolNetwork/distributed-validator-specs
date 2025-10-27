"""Duty types and structure for distributed validators."""

from enum import IntEnum

from pydantic import BaseModel, Field


class DutyType(IntEnum):
    """Types of duties a validator can have."""

    UNKNOWN = 0
    PROPOSER = 1
    ATTESTER = 2
    SIGNATURE = 3
    EXIT = 4
    BUILDER_PROPOSER = 5  # Deprecated due to v3 block proposal
    BUILDER_REGISTRATION = 6
    RANDAO = 7
    PREPARE_AGGREGATOR = 8
    AGGREGATOR = 9
    SYNC_MESSAGE = 10
    PREPARE_SYNC_CONTRIBUTION = 11
    SYNC_CONTRIBUTION = 12
    INFO_SYNC = 13


class Duty(BaseModel):
    """A duty assigned to a validator."""

    slot: int = Field(ge=0, description="The slot number for the duty.")
    type: DutyType = Field(description="The type of duty, represented as an integer.")

    def __hash__(self) -> int:
        """Make Duty hashable so it can be used as dict key."""
        return hash((self.slot, self.type))

    def __eq__(self, other: object) -> bool:
        """Define equality for Duty objects."""
        if not isinstance(other, Duty):
            return False
        return self.slot == other.slot and self.type == other.type
