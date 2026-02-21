"""Integration test — full pipeline from dataset to report.

Verifies that all modules work together end-to-end using synthetic data.
"""

from __future__ import annotations

import pytest

from bitbot.backtesting.data_loader import BacktestDataset
from bitbot.backtesting.engine import BacktestConfig, BacktestEngine
from bitbot.backtesting.metrics import MetricsCalculator
from bitbot.backtesting.report import BacktestReport
from bitbot.config import DCAConfig, ScoringConfig


class TestFullPipeline:
    """End-to-end: dataset → engine → metrics → report."""

    def test_declining_market_full_pipeline(
        self, declining_dataset: BacktestDataset
    ) -> None:
        config = BacktestConfig(
            initial_capital=1000.0,
            scoring=ScoringConfig(
                buy_threshold=30,
                small_buy_range=[30, 49],
                medium_buy_range=[50, 64],
                large_buy_range=[65, 100],
            ),
            dca=DCAConfig(tranches=2, min_interval_minutes=15, max_interval_minutes=30),
        )

        # Run engine
        engine = BacktestEngine(config)
        result = engine.run(declining_dataset)

        # Validate result structure
        assert result.candles_processed > 0
        assert not result.equity_curve.empty
        assert result.final_portfolio_value > 0
        assert result.buy_and_hold_value > 0

        # Compute metrics
        metrics = MetricsCalculator.calculate(result)

        # Validate metrics are populated
        assert isinstance(metrics.total_return_pct, float)
        assert isinstance(metrics.sharpe_ratio, float)
        assert isinstance(metrics.max_drawdown_pct, float)
        assert isinstance(metrics.win_rate_pct, float)
        assert metrics.total_trades >= 0

        # Generate report
        report = BacktestReport.text_summary(metrics, result)

        # Validate report is non-empty and contains key sections
        assert len(report) > 100
        assert "BACKTEST REPORT" in report
        assert "RETURNS" in report
        assert "RISK-ADJUSTED" in report
        assert "DRAWDOWN" in report
        assert "TRADES" in report

    def test_rising_market_full_pipeline(
        self, rising_dataset: BacktestDataset
    ) -> None:
        config = BacktestConfig(initial_capital=1000.0)

        engine = BacktestEngine(config)
        result = engine.run(rising_dataset)
        metrics = MetricsCalculator.calculate(result)
        report = BacktestReport.text_summary(metrics, result)

        assert len(report) > 100
        # In a rising market with few trades, capital should be mostly preserved
        assert result.final_portfolio_value >= 900.0

    def test_trades_have_consistent_ids(
        self, declining_dataset: BacktestDataset
    ) -> None:
        """Every trade should reference a valid position ID."""
        config = BacktestConfig(
            initial_capital=1000.0,
            scoring=ScoringConfig(
                buy_threshold=30,
                small_buy_range=[30, 49],
                medium_buy_range=[50, 64],
                large_buy_range=[65, 100],
            ),
        )

        engine = BacktestEngine(config)
        result = engine.run(declining_dataset)

        # All position IDs from trades should be non-empty
        for trade in result.trades:
            assert trade.position_id, "Trade missing position_id"

        # Buy signal trades should have scores
        for trade in result.trades:
            if trade.reason == "signal":
                assert trade.score is not None, "Signal trade missing score"

    def test_equity_curve_monotonic_timestamps(
        self, declining_dataset: BacktestDataset
    ) -> None:
        """Equity curve timestamps should be strictly increasing."""
        config = BacktestConfig(initial_capital=1000.0)
        engine = BacktestEngine(config)
        result = engine.run(declining_dataset)

        if len(result.equity_curve) > 1:
            timestamps = result.equity_curve.index.tolist()
            for i in range(1, len(timestamps)):
                assert timestamps[i] > timestamps[i - 1], (
                    f"Non-monotonic timestamps at index {i}"
                )
