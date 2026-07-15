"""
Round Change Consensus Timers

This package implements various timer strategies for managing round changes
in a consensus protocol. Different timer strategies can be used to optimize
the performance and responsiveness of the consensus mechanism under varying
network conditions.
"""

from .timer import (
    DoubleEagerLinearRoundTimer,
    IncreasingRoundTimer,
    LinearRoundTimer,
    RoundTimer,
    TimerType,
    create_timer,
    get_default_timer,
    get_duty_start_delay,
)

__all__ = [
    "TimerType",
    "RoundTimer",
    # Timer implementations
    "IncreasingRoundTimer",
    "LinearRoundTimer",
    "DoubleEagerLinearRoundTimer",
    # Factory functions
    "create_timer",
    "get_default_timer",
    # Helpers
    "get_duty_start_delay",
]
