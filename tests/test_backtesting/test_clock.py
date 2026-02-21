"""Tests for the Clock abstraction."""

from datetime import datetime, timedelta, timezone

import pytest

from bitbot.backtesting.clock import SimulatedClock, WallClock


class TestWallClock:
    def test_returns_current_time(self) -> None:
        clock = WallClock()
        before = datetime.now(timezone.utc)
        result = clock.now()
        after = datetime.now(timezone.utc)

        assert before <= result <= after
        assert result.tzinfo is not None


class TestSimulatedClock:
    def test_returns_injected_time(self) -> None:
        t = datetime(2024, 6, 15, 12, 0, tzinfo=timezone.utc)
        clock = SimulatedClock(t)

        assert clock.now() == t

    def test_advance_to_updates_time(self) -> None:
        t1 = datetime(2024, 6, 15, 12, 0, tzinfo=timezone.utc)
        t2 = t1 + timedelta(hours=1)
        clock = SimulatedClock(t1)

        clock.advance_to(t2)
        assert clock.now() == t2

    def test_advance_to_same_time_ok(self) -> None:
        t = datetime(2024, 6, 15, 12, 0, tzinfo=timezone.utc)
        clock = SimulatedClock(t)

        clock.advance_to(t)  # Same time should not raise
        assert clock.now() == t

    def test_cannot_go_back_in_time(self) -> None:
        t1 = datetime(2024, 6, 15, 12, 0, tzinfo=timezone.utc)
        t2 = t1 - timedelta(hours=1)
        clock = SimulatedClock(t1)

        with pytest.raises(ValueError, match="Cannot go back in time"):
            clock.advance_to(t2)

    def test_multiple_advances(self) -> None:
        t = datetime(2024, 1, 1, tzinfo=timezone.utc)
        clock = SimulatedClock(t)

        for i in range(1, 10):
            new_t = t + timedelta(minutes=i * 15)
            clock.advance_to(new_t)
            assert clock.now() == new_t
