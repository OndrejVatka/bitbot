"""Clock abstraction for simulated time in backtesting.

Production code defaults to WallClock (real time). The backtest engine
injects SimulatedClock so that RiskManager and Portfolio use candle
timestamps instead of datetime.now().
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol


class Clock(Protocol):
    """Protocol for time providers."""

    def now(self) -> datetime: ...


class WallClock:
    """Real wall-clock time — used in production and paper trading."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class SimulatedClock:
    """Simulated clock for backtesting — time advances when the engine says so."""

    def __init__(self, start: datetime) -> None:
        self._current = start

    def now(self) -> datetime:
        return self._current

    def advance_to(self, dt: datetime) -> None:
        """Advance simulated time to the given timestamp.

        Raises:
            ValueError: If dt is before the current simulated time.
        """
        if dt < self._current:
            raise ValueError(
                f"Cannot go back in time: {dt} < {self._current}"
            )
        self._current = dt
