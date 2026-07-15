"""
Timer implementations for consensus rounds.

This module provides different timer strategies for consensus protocols.
The timer determines how long each consensus round should wait before timing out
and triggering a round change.
"""

import time
from abc import ABC, abstractmethod
from enum import Enum
from typing import Dict, Optional

from dv_spec.types import Duty
from dv_spec.types.duty import DutyType


class TimerType(Enum):
    """Types of round timers available."""

    INCREASING = "inc"
    EAGER_DOUBLE_LINEAR = "eager_dlinear"
    LINEAR = "linear"


def get_duty_start_delay(duty_type: DutyType, slot_duration: float) -> float:
    """
    Return the delay from slot start to when a duty is scheduled to begin.

    This matches the duty scheduler's slot offsets so that consensus round
    deadlines align with when consensus actually starts for the duty:

    - Attestations start one third into the slot.
    - Aggregations and sync contributions start two thirds into the slot.
    - All other duties start at the slot boundary.
    """
    if duty_type == DutyType.ATTESTER:
        return slot_duration / 3
    if duty_type in (DutyType.AGGREGATOR, DutyType.SYNC_CONTRIBUTION):
        return (2 * slot_duration) / 3
    return 0.0


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

    4. **Deterministic**: When constructed with ``genesis_time`` and ``slot_duration``,
       the first deadline of each round is derived from the duty's slot start time
       (plus the duty start delay, see ``get_duty_start_delay``) rather than the local
       wall clock. All correct nodes therefore compute identical round deadlines,
       keeping round transitions (and hence leader election) aligned across the
       cluster regardless of when each node locally started the consensus instance.

    The original solution is to reset the round timer on justified pre-prepare, but this causes
    the leader to reset at the start of the round (no effect), while others reset when they
    receive the justified pre-prepare (large effect). Leaders tend to get out of sync.
    """

    duty: Duty
    """Duty associated with this timer, used for optimizations."""

    genesis_time: Optional[float]
    """Chain genesis time (unix seconds), used for deterministic deadlines."""

    slot_duration: Optional[float]
    """Slot duration in seconds, used for deterministic deadlines."""

    def __init__(
        self,
        duty: Duty,
        genesis_time: Optional[float] = None,
        slot_duration: Optional[float] = None,
    ):
        """Initialize the timer with duty and optional chain timing information."""
        self.duty = duty
        self.genesis_time = genesis_time
        self.slot_duration = slot_duration
        self.first_deadlines: Dict[int, float] = {}  # Track first deadline for each round
        self._current_time_func = time.time  # Allow injection for testing

    def calculate_timeout(self, round_num: int) -> float:
        """
        Calculate timeout duration, with doubling logic for active rounds.

        The timeout logic works as follows:
        1. First call for a round: the deadline is the duty's deterministic start
           time (slot start + duty start delay, when genesis_time/slot_duration are
           set) plus the linear timeout (round * 1s). Without chain timing info it
           falls back to the local wall clock (now + timeout).
        2. Subsequent calls: the deadline extends by the base timeout from the
           first deadline ("double when leader is active" behavior).

        Returns the remaining duration until the deadline. May be zero or negative
        when the deterministic deadline has already passed (the round times out
        immediately), e.g. on a node that started late.
        """
        # Handle proposal timeout optimization
        if self._proposal_timeout_optimization(round_num):
            timeout = 1.5  # 1500ms
        else:
            timeout = self._linear_round_timeout(round_num)

        current_time = self._current_time_func()

        if round_num in self.first_deadlines:
            # This round has been accessed before - deadline is the first
            # deadline extended by the base timeout (effectively doubling).
            deadline = self.first_deadlines[round_num] + timeout
        else:
            # First time accessing this round - calculate the first deadline.
            if self.genesis_time is not None and self.slot_duration is not None:
                # Deterministic: derive the deadline from the duty's slot start
                # time so all nodes agree on round boundaries.
                slot_start = self.genesis_time + self.slot_duration * self.duty.slot
                duty_start = slot_start + get_duty_start_delay(self.duty.type, self.slot_duration)
                deadline = duty_start + timeout
            else:
                # Fallback: local wall clock.
                deadline = current_time + timeout

            self.first_deadlines[round_num] = deadline

        return deadline - current_time

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

    def reset_round(self, round_num: int) -> None:
        """Reset the timeout tracking for a specific round."""
        if round_num in self.first_deadlines:
            del self.first_deadlines[round_num]

    def clear_all_rounds(self) -> None:
        """Clear all round timeout tracking."""
        self.first_deadlines.clear()


def create_timer(
    timer_type: TimerType,
    duty: Duty,
    genesis_time: Optional[float] = None,
    slot_duration: Optional[float] = None,
) -> RoundTimer:
    """Factory function to create timer instances.

    ``genesis_time`` and ``slot_duration`` are only used by the eager double
    linear timer to compute deterministic, cluster-aligned round deadlines.
    """
    if timer_type == TimerType.INCREASING:
        return IncreasingRoundTimer(duty)
    elif timer_type == TimerType.LINEAR:
        return LinearRoundTimer(duty)
    elif timer_type == TimerType.EAGER_DOUBLE_LINEAR:
        return DoubleEagerLinearRoundTimer(duty, genesis_time, slot_duration)
    else:
        raise ValueError(f"Unknown timer type: {timer_type}")


def get_default_timer(
    duty: Duty,
    genesis_time: Optional[float] = None,
    slot_duration: Optional[float] = None,
) -> RoundTimer:
    """
    Get the default timer type for distributed consensus.

    Default timer selection logic:
    - Use LinearRoundTimer for Proposer duty if Linear feature is enabled
    - Use DoubleEagerLinearRoundTimer for other duties if EagerDoubleLinear is enabled
    - Otherwise use IncreasingRoundTimer

    For this implementation, we default to DoubleEagerLinearRoundTimer.
    Implementations should provide ``genesis_time`` and ``slot_duration`` so
    that round deadlines are deterministic and aligned across the cluster.
    """
    return DoubleEagerLinearRoundTimer(duty, genesis_time, slot_duration)
