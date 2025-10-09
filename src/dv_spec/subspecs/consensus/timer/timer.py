"""
Timer implementations for consensus rounds.

This module provides different timer strategies for consensus protocols.
The timer determines how long each consensus round should wait before timing out
and triggering a round change.
"""

import time
from abc import ABC, abstractmethod
from enum import Enum
from typing import Dict

from dv_spec.types import Duty
from dv_spec.types.duty import DutyType


class TimerType(Enum):
    """Types of round timers available."""

    INCREASING = "inc"
    EAGER_DOUBLE_LINEAR = "eager_dlinear"
    LINEAR = "linear"


class RoundTimer(ABC):
    """Abstract base class for round timers."""

    @abstractmethod
    def calculate_timeout(self, round_num: int) -> float:
        """Calculate the timeout duration for a given round."""
        pass

    @abstractmethod
    def get_type(self) -> TimerType:
        """Get the type of this timer."""
        pass

    def is_eager(self) -> bool:
        """Check if this timer is eager (starts before proposal values are present)."""
        return "eager" in self.get_type().value


class IncreasingRoundTimer(RoundTimer):
    """
    Increasing round timer that starts at a base value and increases linearly.

    Implementation characteristics:
    - Protocol starts at round 1: 750ms + 250ms * 1 = 1000ms
    - Increases by 250ms for each subsequent round
    """

    duty: Duty
    """Duty associated with this timer, used for optimizations."""

    INC_ROUND_START = 0.75  # 750ms
    INC_ROUND_INCREASE = 0.25  # 250ms

    def __init__(self, duty: Duty):
        """Initialize the timer with duty information."""
        self.duty = duty

    def calculate_timeout(self, round_num: int) -> float:
        """Calculate increasing timeout: 750ms + 250ms * round."""
        # Handle proposal timeout optimization for first round (round 1)
        if self._proposal_timeout_optimization(round_num):
            return 1.5  # 1500ms

        return self.INC_ROUND_START + (round_num * self.INC_ROUND_INCREASE)

    def get_type(self) -> TimerType:
        """Return the timer type identifier."""
        return TimerType.INCREASING

    def _proposal_timeout_optimization(self, round_num: int) -> bool:
        """Check if proposal timeout optimization applies."""
        # This optimization applies when ProposalTimeout feature is enabled,
        # duty is proposer, and we're in the first round
        return self.duty.type == DutyType.PROPOSER and round_num == 1


class LinearRoundTimer(RoundTimer):
    """
    Linear round timer with special handling for the first round.

    Implementation characteristics:
    - Round 1: 1 second
    - Subsequent rounds: 200ms + 200ms * (round - 1)
    """

    duty: Duty
    """Duty associated with this timer, used for optimizations."""

    def __init__(self, duty: Duty):
        """Initialize the timer with optional duty information."""
        self.duty = duty

    def calculate_timeout(self, round_num: int) -> float:
        """Calculate linear timeout using standard linear formula."""
        if self._proposal_timeout_optimization(round_num):
            return 1.5  # 1500ms

        if round_num == 1:
            return 1.0  # First round has 1 second
        else:
            # Subsequent rounds: 200ms + 200ms * (round - 1)
            return 0.2 * (round_num - 1) + 0.2

    def get_type(self) -> TimerType:
        """Return the timer type identifier."""
        return TimerType.LINEAR

    def _proposal_timeout_optimization(self, round_num: int) -> bool:
        """Check if proposal timeout optimization applies."""
        return self.duty.type == DutyType.PROPOSER and round_num == 1


class DoubleEagerLinearRoundTimer(RoundTimer):
    """
    Double eager linear round timer with advanced timeout management.

    Implementation with the following properties:

    1. **Double timeout**: When a leader is active, it doubles the round duration instead
       of resetting the timer on justified pre-prepare. This ensures all peers' round
       end-times remain aligned with round start times.

    2. **Eager**: Starts at an absolute time before the proposal values are present.
       This aligns the round start times of all peers, which is important for leader election.

    3. **Linear**: Round duration increases linearly with the round number: 1s, 2s, 3s, etc.

    The original solution is to reset the round timer on justified pre-prepare, but this causes
    the leader to reset at the start of the round (no effect), while others reset when they
    receive the justified pre-prepare (large effect). Leaders tend to get out of sync.
    """

    duty: Duty
    """Duty associated with this timer, used for optimizations."""

    def __init__(self, duty: Duty):
        """Initialize the timer with optional duty information."""
        self.duty = duty
        self.first_deadlines: Dict[int, float] = {}  # Track first timeout for each round
        self._current_time_func = time.time  # Allow injection for testing

    def calculate_timeout(self, round_num: int) -> float:
        """
        Calculate timeout duration, with doubling logic for active rounds.

        The timeout logic works as follows:
        1. First call for a round: returns linear timeout (round * 1s)
        2. Subsequent calls: returns double the first timeout

        This implements the "double when leader is active" behavior.
        """
        # Handle proposal timeout optimization
        if self._proposal_timeout_optimization(round_num):
            timeout = 1.5  # 1500ms
        else:
            timeout = self._linear_round_timeout(round_num)

        current_time = self._current_time_func()

        if round_num in self.first_deadlines:
            # This round has been accessed before - use double timeout
            first_deadline = self.first_deadlines[round_num]
            # Calculate remaining time from first deadline, then double it
            remaining_from_first = max(0, first_deadline - current_time)
            return remaining_from_first + timeout  # Effectively doubling
        else:
            # First time accessing this round - store the deadline and return base timeout
            self.first_deadlines[round_num] = current_time + timeout
            return timeout

    def get_type(self) -> TimerType:
        """Return the timer type identifier."""
        return TimerType.EAGER_DOUBLE_LINEAR

    def _linear_round_timeout(self, round_num: int) -> float:
        """Calculate linear timeout: round * 1 second."""
        return max(1.0, round_num * 1.0)

    def _proposal_timeout_optimization(self, round_num: int) -> bool:
        """Check if proposal timeout optimization applies."""
        return (
            self.duty is not None and self.duty.type == DutyType.PROPOSER and round_num == 1
        )  # Protocol starts at round 1

    def reset_round(self, round_num: int):
        """Reset the timeout tracking for a specific round."""
        if round_num in self.first_deadlines:
            del self.first_deadlines[round_num]

    def clear_all_rounds(self):
        """Clear all round timeout tracking."""
        self.first_deadlines.clear()


def create_timer(timer_type: TimerType, duty: Duty = None) -> RoundTimer:
    """Factory function to create timer instances."""
    if timer_type == TimerType.INCREASING:
        return IncreasingRoundTimer(duty)
    elif timer_type == TimerType.LINEAR:
        return LinearRoundTimer(duty)
    elif timer_type == TimerType.EAGER_DOUBLE_LINEAR:
        return DoubleEagerLinearRoundTimer(duty)
    else:
        raise ValueError(f"Unknown timer type: {timer_type}")


def get_default_timer(duty: Duty = None) -> RoundTimer:
    """
    Get the default timer type for distributed consensus.

    Default timer selection logic:
    - Use LinearRoundTimer for Proposer duty if Linear feature is enabled
    - Use DoubleEagerLinearRoundTimer for other duties if EagerDoubleLinear is enabled
    - Otherwise use IncreasingRoundTimer

    For this implementation, we default to DoubleEagerLinearRoundTimer.
    """
    return DoubleEagerLinearRoundTimer(duty)
