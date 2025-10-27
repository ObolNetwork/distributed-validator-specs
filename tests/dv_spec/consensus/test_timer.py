"""
Tests for the timer module implementations.

Tests all timer types: IncreasingRoundTimer, LinearRoundTimer, and DoubleEagerLinearRoundTimer.
"""

from dv_spec.subspecs.consensus.timer import (
    DoubleEagerLinearRoundTimer,
    IncreasingRoundTimer,
    LinearRoundTimer,
    TimerType,
    create_timer,
    get_default_timer,
)
from dv_spec.types import Duty, DutyType


class TestTimerTypes:
    """Test timer type enumeration."""

    def test_timer_type_values(self) -> None:
        """Test that timer types have correct values."""
        assert TimerType.INCREASING.value == "inc"
        assert TimerType.EAGER_DOUBLE_LINEAR.value == "eager_dlinear"
        assert TimerType.LINEAR.value == "linear"


class TestIncreasingRoundTimer:
    """Test IncreasingRoundTimer implementation."""

    def setup_method(self) -> None:
        """Setup test fixtures."""
        self.duty = Duty(slot=100, type=DutyType.PROPOSER)
        self.timer = IncreasingRoundTimer(self.duty)

    def test_basic_timeout_calculation(self) -> None:
        """Test increasing timeout calculation."""
        # Use non-proposer duty to avoid proposal timeout optimization
        non_proposer_timer = IncreasingRoundTimer(Duty(slot=100, type=DutyType.ATTESTER))

        # Round 1: 750ms + 250ms = 1000ms
        timeout_1 = non_proposer_timer.calculate_timeout(1)
        assert timeout_1 == 1.0

        # Round 2: 750ms + 2*250ms = 1250ms
        timeout_2 = non_proposer_timer.calculate_timeout(2)
        assert timeout_2 == 1.25

    def test_proposal_timeout_optimization(self) -> None:
        """Test proposal timeout optimization for round 1."""
        # For proposer duty in round 1, should return 1.5s
        timeout = self.timer.calculate_timeout(1)
        assert timeout == 1.5  # Proposal timeout optimization

    def test_timer_type(self) -> None:
        """Test timer type identification."""
        assert self.timer.get_type() == TimerType.INCREASING
        assert not self.timer.is_eager()  # Should not be eager


class TestLinearRoundTimer:
    """Test LinearRoundTimer implementation."""

    def setup_method(self) -> None:
        """Setup test fixtures."""
        self.duty = Duty(slot=100, type=2)  # Non-proposer duty
        self.timer = LinearRoundTimer(self.duty)

    def test_basic_timeout_calculation(self) -> None:
        """Test linear timeout calculation."""
        # Round 1: First round has 1 second
        timeout_1 = self.timer.calculate_timeout(1)
        assert timeout_1 == 1.0

        # Round 2: 0.2 * (2 - 1) + 0.2 = 0.4 seconds
        timeout_2 = self.timer.calculate_timeout(2)
        assert timeout_2 == 0.4

    def test_proposal_timeout_optimization(self) -> None:
        """Test proposal timeout optimization for proposer duty."""
        proposer_timer = LinearRoundTimer(Duty(slot=100, type=1))
        timeout = proposer_timer.calculate_timeout(1)  # First round is now round 1
        assert timeout == 1.5  # Proposal timeout optimization

    def test_timer_type(self) -> None:
        """Test timer type identification."""
        assert self.timer.get_type() == TimerType.LINEAR
        assert not self.timer.is_eager()  # Should not be eager


class TestDoubleEagerLinearRoundTimer:
    """Test DoubleEagerLinearRoundTimer implementation."""

    def setup_method(self) -> None:
        """Setup test fixtures."""
        self.duty = Duty(slot=100, type=2)  # Non-proposer duty
        self.timer = DoubleEagerLinearRoundTimer(self.duty)

        # Mock time function for consistent testing
        self.mock_time = 1000.0
        self.timer._current_time_func = lambda: self.mock_time

    def test_basic_timeout_calculation(self) -> None:
        """Test double eager linear timeout calculation."""
        # Round 1: max(1.0, 1 * 1.0) = 1.0 second
        timeout_1 = self.timer.calculate_timeout(1)
        assert timeout_1 == 1.0

        # Round 2: max(1.0, 2 * 1.0) = 2.0 seconds
        timeout_2 = self.timer.calculate_timeout(2)
        assert timeout_2 == 2.0

        # Round 5: max(1.0, 5 * 1.0) = 5.0 seconds
        timeout_5 = self.timer.calculate_timeout(5)
        assert timeout_5 == 5.0

    def test_double_timeout_behavior(self) -> None:
        """Test the doubling behavior when accessing the same round multiple times."""
        # First access to round 2
        timeout_first = self.timer.calculate_timeout(2)
        assert timeout_first == 2.0  # 2 * 1.0 = 2.0 (doubling behavior)

        # Advance mock time by 1 second
        self.mock_time += 1.0

        # Second access to round 2 should return extended timeout
        timeout_second = self.timer.calculate_timeout(2)
        # Should be remaining time from first deadline + base timeout
        assert timeout_second > timeout_first

    def test_proposal_timeout_optimization(self) -> None:
        """Test proposal timeout optimization for proposer duty."""
        proposer_timer = DoubleEagerLinearRoundTimer(Duty(slot=100, type=1))
        proposer_timer._current_time_func = lambda: 1000.0

        timeout = proposer_timer.calculate_timeout(1)  # First round is now round 1
        assert timeout == 1.5  # Proposal timeout optimization

    def test_timer_type(self) -> None:
        """Test timer type identification."""
        assert self.timer.get_type() == TimerType.EAGER_DOUBLE_LINEAR
        assert self.timer.is_eager()  # Should be eager

    def test_reset_round(self) -> None:
        """Test resetting a specific round."""
        # Access round 2 to create first deadline
        self.timer.calculate_timeout(2)
        assert 2 in self.timer.first_deadlines

        # Reset round 2
        self.timer.reset_round(2)
        assert 2 not in self.timer.first_deadlines

    def test_clear_all_rounds(self) -> None:
        """Test clearing all round tracking."""
        # Access multiple rounds
        self.timer.calculate_timeout(1)
        self.timer.calculate_timeout(2)
        self.timer.calculate_timeout(3)

        assert len(self.timer.first_deadlines) == 3

        # Clear all rounds
        self.timer.clear_all_rounds()
        assert len(self.timer.first_deadlines) == 0


class TestTimerFactory:
    """Test timer factory functions."""

    def test_create_timer_increasing(self) -> None:
        """Test creating IncreasingRoundTimer."""
        duty = Duty(slot=100, type=1)
        timer = create_timer(TimerType.INCREASING, duty)
        assert isinstance(timer, IncreasingRoundTimer)
        assert timer.duty == duty

    def test_create_timer_linear(self) -> None:
        """Test creating LinearRoundTimer."""
        duty = Duty(slot=100, type=1)
        timer = create_timer(TimerType.LINEAR, duty)
        assert isinstance(timer, LinearRoundTimer)
        assert timer.duty == duty

    def test_create_timer_double_eager_linear(self) -> None:
        """Test creating DoubleEagerLinearRoundTimer."""
        duty = Duty(slot=100, type=1)
        timer = create_timer(TimerType.EAGER_DOUBLE_LINEAR, duty)
        assert isinstance(timer, DoubleEagerLinearRoundTimer)
        assert timer.duty == duty

    def test_get_default_timer(self) -> None:
        """Test getting default timer."""
        duty = Duty(slot=100, type=1)
        timer = get_default_timer(duty)
        assert isinstance(timer, DoubleEagerLinearRoundTimer)
        assert timer.duty == duty


class TestTimerComparison:
    """Test comparing different timer implementations."""

    def setup_method(self) -> None:
        """Setup timer instances for comparison."""
        self.duty = Duty(slot=100, type=2)
        self.increasing = IncreasingRoundTimer(self.duty)
        self.linear = LinearRoundTimer(self.duty)
        self.double_eager = DoubleEagerLinearRoundTimer(self.duty)

    def test_round_1_comparison(self) -> None:
        """Compare all timers for round 1 (protocol's first round)."""
        # IncreasingRoundTimer: 750ms + 1*250ms = 1000ms
        inc_timeout = self.increasing.calculate_timeout(1)
        assert inc_timeout == 1.0

        # LinearRoundTimer: 1000ms (first round special case)
        lin_timeout = self.linear.calculate_timeout(1)
        assert lin_timeout == 1.0

        # DoubleEagerLinearRoundTimer: max(1.0, 1*1.0) = 1000ms
        del_timeout = self.double_eager.calculate_timeout(1)
        assert del_timeout == 1.0

        # All timers should be the same for protocol's first round
        assert lin_timeout == del_timeout == inc_timeout

    def test_higher_rounds_comparison(self) -> None:
        """Compare all timers for higher rounds."""
        round_num = 5

        # IncreasingRoundTimer: 750ms + 5*250ms = 2000ms
        inc_timeout = self.increasing.calculate_timeout(round_num)
        assert inc_timeout == 2.0

        # LinearRoundTimer: 200ms * (5-1) + 200ms = 1000ms
        lin_timeout = self.linear.calculate_timeout(round_num)
        assert lin_timeout == 1.0  # 0.2 * (5-1) + 0.2 = 1.0

        # DoubleEagerLinearRoundTimer: max(1.0, 5*1.0) = 5000ms
        del_timeout = self.double_eager.calculate_timeout(round_num)
        assert del_timeout == 5.0

        # DoubleEager should have longest timeout for high rounds
        assert del_timeout > inc_timeout > lin_timeout
