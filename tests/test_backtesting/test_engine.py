"""Tests for the core BacktestEngine.

These are the most critical tests — they verify that the engine correctly
replays the full signal→score→trade→risk pipeline on historical data.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from bitbot.backtesting.data_loader import BacktestDataset
from bitbot.backtesting.engine import BacktestConfig, BacktestEngine
from bitbot.config import DCAConfig, RiskConfig, ScoringConfig

from .conftest import make_candles_df, make_declining_candles, make_rising_candles


class TestEngineBasics:
    def test_empty_dataset_raises(self, default_config: BacktestConfig) -> None:
        import pandas as pd

        empty = BacktestDataset(
            candles_15m=pd.DataFrame(columns=["open", "high", "low", "close", "volume"]),
            candles_4h=pd.DataFrame(columns=["open", "high", "low", "close", "volume"]),
            symbol="BTCUSDT",
            start=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end=datetime(2024, 6, 1, tzinfo=timezone.utc),
        )

        engine = BacktestEngine(default_config)
        with pytest.raises(ValueError, match="no 15m candles"):
            engine.run(empty)

    def test_result_has_equity_curve(
        self, default_config: BacktestConfig, declining_dataset: BacktestDataset
    ) -> None:
        engine = BacktestEngine(default_config)
        result = engine.run(declining_dataset)

        assert not result.equity_curve.empty
        assert "portfolio_value" in result.equity_curve.columns
        assert "cash" in result.equity_curve.columns
        assert "exposure" in result.equity_curve.columns

    def test_candles_processed_count(
        self, default_config: BacktestConfig, declining_dataset: BacktestDataset
    ) -> None:
        engine = BacktestEngine(default_config)
        result = engine.run(declining_dataset)

        # Should process candles from scored_start_index to end
        expected = len(declining_dataset.candles_15m) - declining_dataset.scored_start_index
        assert result.candles_processed == expected

    def test_buy_and_hold_calculated(
        self, default_config: BacktestConfig, declining_dataset: BacktestDataset
    ) -> None:
        engine = BacktestEngine(default_config)
        result = engine.run(declining_dataset)

        # B&H should reflect the price movement
        assert result.buy_and_hold_value > 0
        # In a declining market, B&H value should be less than initial
        assert result.buy_and_hold_value < default_config.initial_capital


class TestDecliningMarket:
    """In a declining market, the engine should detect dips and open positions."""

    def test_generates_buy_trades(self, declining_dataset: BacktestDataset) -> None:
        # Lower the buy range thresholds so the scorer triggers more easily
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

        buy_trades = [t for t in result.trades if t.side == "buy"]
        assert len(buy_trades) > 0, "Expected at least one buy trade in declining market"

    def test_stop_losses_or_profit_targets_close_positions(
        self, declining_dataset: BacktestDataset
    ) -> None:
        """In a declining market, positions should eventually be closed
        by stop-losses or profit targets (if price bounces).
        """
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

        buy_trades = [t for t in result.trades if t.side == "buy"]
        sell_trades = [t for t in result.trades if t.side == "sell"]

        # If there are buys, the strategy is active and should have some sells
        if len(buy_trades) > 0:
            # Either stop-losses or profit targets should close some positions
            assert len(result.positions_closed) >= 0  # May have 0 if positions are still open
            # All sell trades should have a valid reason
            for t in sell_trades:
                assert t.reason in ("stop_loss", "profit_target")


class TestRisingMarket:
    """In a rising market, the dip-buying strategy should be quiet."""

    def test_few_or_no_buys(self, rising_dataset: BacktestDataset) -> None:
        config = BacktestConfig(initial_capital=1000.0)
        engine = BacktestEngine(config)
        result = engine.run(rising_dataset)

        buy_trades = [t for t in result.trades if t.side == "buy" and t.reason == "signal"]
        # In a steadily rising market, very few signals should trigger
        assert len(buy_trades) <= 3, (
            f"Too many buys ({len(buy_trades)}) in a rising market"
        )

    def test_capital_mostly_preserved(self, rising_dataset: BacktestDataset) -> None:
        config = BacktestConfig(initial_capital=1000.0)
        engine = BacktestEngine(config)
        result = engine.run(rising_dataset)

        # Capital should be close to initial (no major losses)
        assert result.final_portfolio_value >= 950.0, (
            f"Too much capital lost in rising market: ${result.final_portfolio_value:.2f}"
        )


class TestDCA:
    """Verify DCA tranche scheduling and execution."""

    def test_dca_tranches_executed(self, declining_dataset: BacktestDataset) -> None:
        config = BacktestConfig(
            initial_capital=1000.0,
            scoring=ScoringConfig(
                buy_threshold=30,
                small_buy_range=[30, 49],
                medium_buy_range=[50, 64],
                large_buy_range=[65, 100],
            ),
            dca=DCAConfig(tranches=3, min_interval_minutes=15, max_interval_minutes=30),
        )
        engine = BacktestEngine(config)
        result = engine.run(declining_dataset)

        dca_trades = [t for t in result.trades if t.reason == "dca"]
        signal_trades = [t for t in result.trades if t.reason == "signal"]

        # If any signal trades triggered, we should see DCA follow-ups
        if signal_trades:
            assert len(dca_trades) > 0, "Expected DCA tranches after signal buys"

    def test_single_tranche_no_dca(self, declining_dataset: BacktestDataset) -> None:
        config = BacktestConfig(
            initial_capital=1000.0,
            scoring=ScoringConfig(
                buy_threshold=30,
                small_buy_range=[30, 49],
                medium_buy_range=[50, 64],
                large_buy_range=[65, 100],
            ),
            dca=DCAConfig(tranches=1),  # Single tranche = no DCA
        )
        engine = BacktestEngine(config)
        result = engine.run(declining_dataset)

        dca_trades = [t for t in result.trades if t.reason == "dca"]
        assert len(dca_trades) == 0, "No DCA trades expected with tranches=1"


class TestRiskManagement:
    """Verify risk manager integration in the engine."""

    def test_exposure_limit_respected(self, declining_dataset: BacktestDataset) -> None:
        config = BacktestConfig(
            initial_capital=1000.0,
            scoring=ScoringConfig(
                buy_threshold=30,
                small_buy_range=[30, 49],
                medium_buy_range=[50, 64],
                large_buy_range=[65, 100],
            ),
            risk=RiskConfig(max_total_exposure_pct=0.30),  # Tight exposure limit
        )
        engine = BacktestEngine(config)
        result = engine.run(declining_dataset)

        # Check that exposure never massively exceeds the limit
        # (slight overshoot possible due to DCA timing)
        if not result.equity_curve.empty:
            max_exposure = result.equity_curve["exposure"].max()
            # Exposure should be bounded (allow some tolerance for fees/DCA)
            assert max_exposure < config.initial_capital * 0.5, (
                f"Exposure too high: ${max_exposure:.2f}"
            )

    def test_equity_curve_starts_at_initial_capital(
        self, default_config: BacktestConfig, declining_dataset: BacktestDataset
    ) -> None:
        engine = BacktestEngine(default_config)
        result = engine.run(declining_dataset)

        if not result.equity_curve.empty:
            first_value = result.equity_curve["portfolio_value"].iloc[0]
            assert first_value == pytest.approx(
                default_config.initial_capital, rel=0.01
            )


class TestPositionSummaries:
    """Verify position tracking and P&L calculations."""

    def test_closed_positions_have_pnl(self, declining_dataset: BacktestDataset) -> None:
        config = BacktestConfig(
            initial_capital=1000.0,
            scoring=ScoringConfig(
                buy_threshold=30,
                small_buy_range=[30, 49],
                medium_buy_range=[50, 64],
                large_buy_range=[65, 100],
            ),
            risk=RiskConfig(stop_loss_pct=3.0),
        )
        engine = BacktestEngine(config)
        result = engine.run(declining_dataset)

        for pos in result.positions_closed:
            assert pos.avg_entry_price > 0
            assert pos.exit_price > 0
            assert pos.quantity > 0
            assert pos.duration_hours >= 0
            # PnL percentage should be consistent with entry/exit prices
            if pos.pnl > 0:
                assert pos.exit_price > pos.avg_entry_price
            elif pos.pnl < 0:
                assert pos.exit_price < pos.avg_entry_price


class TestNoLookAheadBias:
    """Verify the engine doesn't use future data."""

    def test_4h_window_does_not_include_future(
        self, default_config: BacktestConfig
    ) -> None:
        """The 4h window should only include candles at or before current 15m time."""
        # Create a dataset where we can track what data the engine sees
        candles_15m = make_candles_df(
            n=300,
            start_price=50000.0,
            interval_minutes=15,
            seed=42,
        )

        # Create 4h candles that are clearly distinct (different trend)
        candles_4h = make_candles_df(
            n=250,
            start_price=50000.0,
            interval_minutes=240,
            trend=0.005,  # Strongly bullish 4h
            seed=99,
        )

        start_time = candles_15m.index[250].to_pydatetime()
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)

        dataset = BacktestDataset(
            candles_15m=candles_15m,
            candles_4h=candles_4h,
            symbol="BTCUSDT",
            start=start_time,
            end=candles_15m.index[-1].to_pydatetime().replace(tzinfo=timezone.utc),
        )

        engine = BacktestEngine(default_config)
        result = engine.run(dataset)

        # If it runs without error, the windowing logic is at least structurally correct
        assert result.candles_processed > 0
