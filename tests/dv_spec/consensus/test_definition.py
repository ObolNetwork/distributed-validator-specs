"""
Test suite for Definition class implementation
"""

import pytest

from dv_spec.subspecs.consensus.qbft.definition import Definition
from dv_spec.types import Duty


class TestDefinition:
    """Test cases for the Definition class."""

    def test_initialization(self):
        """Test creating a Definition with valid parameters."""
        d = Definition(nodes=4)
        assert d.nodes == 4

        d = Definition(nodes=7)
        assert d.nodes == 7

        d = Definition(nodes=10)
        assert d.nodes == 10

    def test_quorum_calculation(self):
        """Test quorum calculation for various cluster sizes."""
        # Standard cases
        d = Definition(nodes=4)
        assert d.quorum() == 3  # ceil(2*4/3) = ceil(8/3) = 3

        d = Definition(nodes=7)
        assert d.quorum() == 5  # ceil(2*7/3) = ceil(14/3) = 5

        d = Definition(nodes=10)
        assert d.quorum() == 7  # ceil(2*10/3) = ceil(20/3) = 7

    def test_faulty_calculation(self):
        """Test faulty node calculation for various cluster sizes."""
        # Standard cases
        d = Definition(nodes=4)
        assert d.faulty() == 1  # floor((4-1)/3) = floor(3/3) = 1

        d = Definition(nodes=7)
        assert d.faulty() == 2  # floor((7-1)/3) = floor(6/3) = 2

        d = Definition(nodes=10)
        assert d.faulty() == 3  # floor((10-1)/3) = floor(9/3) = 3

    def test_is_leader_deterministic(self):
        """Test that leader election is deterministic."""
        duty = Duty(slot=100, type=1)
        d = Definition(nodes=4)

        # Test same inputs produce same results
        result1 = d.is_leader(duty, 1, 0)
        result2 = d.is_leader(duty, 1, 0)
        assert result1 == result2

        # Test all nodes for round 1
        leaders_round1 = []
        for peer in range(4):
            if d.is_leader(duty, 1, peer):
                leaders_round1.append(peer)

        # Should have exactly one leader per round
        assert len(leaders_round1) == 1

    def test_is_leader_round_rotation(self):
        """Test that leadership rotates across rounds."""
        duty = Duty(slot=102, type=1)
        d = Definition(nodes=4)

        # Check multiple rounds
        leaders = []
        for round_num in range(1, 9):  # Test 8 rounds
            for peer in range(4):
                if d.is_leader(duty, round_num, peer):
                    leaders.append(peer)
                    break

        # Should have 8 leaders (one per round)
        assert len(leaders) == 8

        # Leadership should cycle through all peers
        unique_leaders = set(leaders)
        assert len(unique_leaders) == 4

    def test_byzantine_fault_tolerance_properties(self):
        """Test that quorum and faulty calculations satisfy BFT properties."""
        for nodes in range(1, 20):
            d = Definition(nodes=nodes)
            quorum = d.quorum()
            faulty = d.faulty()

            # Basic properties
            assert quorum > 0
            assert faulty >= 0
            assert quorum <= nodes
            assert faulty < nodes

            # BFT property: quorum > (nodes + faulty) / 2
            # This ensures that any two quorums overlap
            assert quorum > (nodes + faulty) / 2
