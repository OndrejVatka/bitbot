"""Tests for the MetricsCalculator."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from bitbot.backtesting.engine import BacktestConfig, BacktestResult, PositionSummary, TradeRecord
from bitbot.backtesting.metrics import MetricsCalculator


def _make_equity_curve(values: list[float], start: datetime | None = None) -> pd.DataFrame:
    """Create an equity curve DataFrame from a list of portfolio values."""
    if start is None:
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)

    timestamps = [start + timedelta(minutes=i * 15) for i in range(len(values))]
    df = pd.DataFrame({
        "portfolio_value": values,
        "cash": [v * 0.5 for v in values],
        "exposure": [v * 0.5 for v in values],
    }, index=timestamps)
    return df


def _make_result(
    equity_values: list[float],
    positions: list[PositionSummary] | None = None,
    trades: list[TradeRecord] | None = None,
    initial_capital: float = 1000.0,
) -> BacktestResult:
    """Create a minimal BacktestResult for testing metrics."""
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(minutes=len(equity_values) * 15)

    # Buy-and-hold: assume flat
    bh_value = initial_capital

    return BacktestResult(
        config=BacktestConfig(initial_capital=initial_capital),
        trades=trades or [],
        equity_curve=_make_equity_curve(equity_values, start),
        positions_closed=positions or [],
        start_time=start,
        end_time=end,
        candles_processed=len(equity_values),
        final_portfolio_value=equity_values[-1] if equity_values else initial_capital,
        buy_and_hold_value=bh_value,
    )


class TestReturns:
    def test_positive_return(self) -> None:
        result = _make_result([1000, 1050, 1100, 1150, 1200])
        metrics = MetricsCalculator.calculate(result)

        assert metrics.total_return_pct == pytest.approx(20.0, rel=0.01)
        assert metrics.total_return_usdt == pytest.approx(200.0, rel=0.01)

    def test_negative_return(self) -> None:
        result = _make_result([1000, 950, 900, 850, 800])
        metrics = MetricsCalculator.calculate(result)

        assert metrics.total_return_pct == pytest.approx(-20.0, rel=0.01)

    def test_flat_return(self) -> None:
        result = _make_result([1000, 1000, 1000, 1000])
        metrics = MetricsCalculator.calculate(result)

        assert metrics.total_return_pct == pytest.approx(0.0, abs=0.01)

    def test_alpha_vs_buy_hold(self) -> None:
        result = _make_result([1000, 1100, 1200])
        result = BacktestResult(
            **{**result.__dict__, "buy_and_hold_value": 1100.0}
        )
        metrics = MetricsCalculator.calculate(result)

        # Strategy: +20%, B&H: +10%, Alpha: +10%
        assert metrics.alpha_vs_buy_hold_pct == pytest.approx(10.0, rel=0.01)


class TestWinLoss:
    def test_all_winners(self) -> None:
        positions = [
            PositionSummary(
                position_id=f"p{i}", entry_time=datetime.now(timezone.utc),
                exit_time=datetime.now(timezone.utc), avg_entry_price=100,
                exit_price=110, quantity=1, tranches=1, pnl=10, pnl_pct=10.0,
                duration_hours=2,
            )
            for i in range(5)
        ]
        result = _make_result([1000, 1050, 1100], positions=positions)
        metrics = MetricsCalculator.calculate(result)

        assert metrics.win_rate_pct == 100.0
        assert metrics.winning_trades == 5
        assert metrics.losing_trades == 0

    def test_all_losers(self) -> None:
        positions = [
            PositionSummary(
                position_id=f"p{i}", entry_time=datetime.now(timezone.utc),
                exit_time=datetime.now(timezone.utc), avg_entry_price=100,
                exit_price=90, quantity=1, tranches=1, pnl=-10, pnl_pct=-10.0,
                duration_hours=2,
            )
            for i in range(3)
        ]
        result = _make_result([1000, 970, 940], positions=positions)
        metrics = MetricsCalculator.calculate(result)

        assert metrics.win_rate_pct == 0.0

    def test_no_positions(self) -> None:
        result = _make_result([1000, 1000, 1000])
        metrics = MetricsCalculator.calculate(result)

        assert metrics.win_rate_pct == 0.0
        assert metrics.winning_trades == 0
        assert metrics.losing_trades == 0

    def test_profit_factor(self) -> None:
        positions = [
            PositionSummary(
                position_id="w1", entry_time=datetime.now(timezone.utc),
                exit_time=datetime.now(timezone.utc), avg_entry_price=100,
                exit_price=120, quantity=1, tranches=1, pnl=20, pnl_pct=20.0,
                duration_hours=2,
            ),
            PositionSummary(
                position_id="l1", entry_time=datetime.now(timezone.utc),
                exit_time=datetime.now(timezone.utc), avg_entry_price=100,
                exit_price=90, quantity=1, tranches=1, pnl=-10, pnl_pct=-10.0,
                duration_hours=2,
            ),
        ]
        result = _make_result([1000, 1010, 1010], positions=positions)
        metrics = MetricsCalculator.calculate(result)

        assert metrics.profit_factor == pytest.approx(2.0)


class TestDrawdown:
    def test_no_drawdown(self) -> None:
        # Monotonically increasing
        result = _make_result([1000, 1010, 1020, 1030, 1040])
        metrics = MetricsCalculator.calculate(result)

        assert metrics.max_drawdown_pct == 0.0

    def test_known_drawdown(self) -> None:
        # Peak at 1100, trough at 990 = (1100-990)/1100 = 10%
        result = _make_result([1000, 1100, 1050, 990, 1000])
        metrics = MetricsCalculator.calculate(result)

        assert metrics.max_drawdown_pct == pytest.approx(10.0, rel=0.01)


class TestSharpe:
    def test_flat_equity_zero_sharpe(self) -> None:
        result = _make_result([1000] * 100)
        metrics = MetricsCalculator.calculate(result)

        assert metrics.sharpe_ratio == 0.0

    def test_positive_trending_equity(self) -> None:
        # Steady growth should produce positive Sharpe
        values = [1000 + i * 1 for i in range(100)]
        result = _make_result(values)
        metrics = MetricsCalculator.calculate(result)

        assert metrics.sharpe_ratio > 0


class TestMonthlyReturns:
    def test_single_month(self) -> None:
        # All data in January 2024
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
        values = [1000, 1050, 1100]
        result = _make_result(values)
        metrics = MetricsCalculator.calculate(result)

        assert "2024-01" in metrics.monthly_returns

    def test_empty_equity(self) -> None:
        result = _make_result([])
        result = BacktestResult(
            config=BacktestConfig(),
            trades=[],
            equity_curve=pd.DataFrame(columns=["portfolio_value", "cash", "exposure"]),
            positions_closed=[],
            start_time=datetime.now(timezone.utc),
            end_time=datetime.now(timezone.utc),
            candles_processed=0,
            final_portfolio_value=1000.0,
            buy_and_hold_value=1000.0,
        )
        metrics = MetricsCalculator.calculate(result)

        assert metrics.monthly_returns == {}


class TestFees:
    def test_total_fees_counted(self) -> None:
        trades = [
            TradeRecord(
                timestamp=datetime.now(timezone.utc), side="buy", price=50000,
                quantity=0.01, usdt_value=500, fee=0.5, reason="signal",
                position_id="p1",
            ),
            TradeRecord(
                timestamp=datetime.now(timezone.utc), side="sell", price=51000,
                quantity=0.01, usdt_value=510, fee=0.51, reason="profit_target",
                position_id="p1",
            ),
        ]
        result = _make_result([1000, 1010], trades=trades)
        metrics = MetricsCalculator.calculate(result)

        assert metrics.total_fees_paid == pytest.approx(1.01, rel=0.01)
