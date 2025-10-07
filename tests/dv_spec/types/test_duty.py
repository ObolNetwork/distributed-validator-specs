"""
Tests for the duty types and structures.

This module tests the duty assignment structures used across
the distributed validator system.
"""

import pytest

from dv_spec.types import Duty, DutyType


class TestDutyType:
    """Test DutyType enumeration."""

    def test_duty_type_values(self):
        """Test that DutyType values are correct."""
        assert DutyType.UNKNOWN == 0
        assert DutyType.PROPOSER == 1
        assert DutyType.ATTESTER == 2
        assert DutyType.SIGNATURE == 3
        assert DutyType.EXIT == 4
        assert DutyType.BUILDER_PROPOSER == 5
        assert DutyType.BUILDER_REGISTRATION == 6
        assert DutyType.RANDAO == 7
        assert DutyType.PREPARE_AGGREGATOR == 8
        assert DutyType.AGGREGATOR == 9
        assert DutyType.SYNC_MESSAGE == 10
        assert DutyType.PREPARE_SYNC_CONTRIBUTION == 11
        assert DutyType.SYNC_CONTRIBUTION == 12
        assert DutyType.INFO_SYNC == 13

    def test_duty_type_names(self):
        """Test that DutyType names are correct."""
        assert DutyType.PROPOSER.name == "PROPOSER"
        assert DutyType.ATTESTER.name == "ATTESTER"
        assert DutyType.AGGREGATOR.name == "AGGREGATOR"


class TestDuty:
    """Test Duty class functionality."""

    def test_duty_creation(self):
        """Test creating a Duty object."""
        duty = Duty(slot=100, type=DutyType.PROPOSER)
        assert duty.slot == 100
        assert duty.type == DutyType.PROPOSER

    def test_duty_equality(self):
        """Test Duty equality comparison."""
        duty1 = Duty(slot=100, type=DutyType.PROPOSER)
        duty2 = Duty(slot=100, type=DutyType.PROPOSER)
        duty3 = Duty(slot=101, type=DutyType.PROPOSER)
        duty4 = Duty(slot=100, type=DutyType.ATTESTER)

        assert duty1 == duty2
        assert duty1 != duty3
        assert duty1 != duty4
        assert duty1 != "not a duty"

    def test_duty_hash(self):
        """Test that Duty objects can be hashed and used as dict keys."""
        duty1 = Duty(slot=100, type=DutyType.PROPOSER)
        duty2 = Duty(slot=100, type=DutyType.PROPOSER)
        duty3 = Duty(slot=101, type=DutyType.PROPOSER)

        # Same duties should have same hash
        assert hash(duty1) == hash(duty2)

        # Different duties should have different hashes (likely)
        assert hash(duty1) != hash(duty3)

        # Should be usable as dict keys
        duty_dict = {duty1: "value1", duty3: "value2"}
        assert duty_dict[duty2] == "value1"  # duty2 == duty1
        assert len(duty_dict) == 2
