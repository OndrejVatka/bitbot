"""Tests for the parameter optimizer."""

from __future__ import annotations

import pytest

from bitbot.backtesting.data_loader import BacktestDataset
from bitbot.backtesting.engine import BacktestConfig
from bitbot.backtesting.optimizer import Optimizer, ParameterSpace


class TestParameterSpace:
    def test_grid_combinations_count(self) -> None:
        space = ParameterSpace(
            rsi_oversold=[30],
            rsi_extremely_oversold=[20],
            buy_threshold=[50, 60],
            small_buy_pct=[0.05],
            medium_buy_pct=[0.10],
            large_buy_pct=[0.20],
            stop_loss_pct=[5.0],
            profit_target_pct=[3.0, 5.0],
            dca_tranches=[1],
        )

        combos = space.grid_combinations()
        # 1*1*2*1*1*1*1*2*1 = 4
        assert len(combos) == 4

    def test_random_sample_respects_limit(self) -> None:
        space = ParameterSpace()  # Default has many combinations
        all_combos = space.grid_combinations()

        sample = space.random_sample(5)
        assert len(sample) == 5
        assert len(sample) <= len(all_combos)

    def test_random_sample_deterministic(self) -> None:
        space = ParameterSpace()
        sample1 = space.random_sample(10, seed=42)
        sample2 = space.random_sample(10, seed=42)

        assert sample1 == sample2


class TestOptimizer:
    def test_small_grid_search(self, declining_dataset: BacktestDataset) -> None:
        """Run a tiny 2-combo optimization to verify it works end-to-end."""
        space = ParameterSpace(
            rsi_oversold=[30],
            rsi_extremely_oversold=[20],
            buy_threshold=[40, 60],
            small_buy_pct=[0.05],
            medium_buy_pct=[0.10],
            large_buy_pct=[0.20],
            stop_loss_pct=[5.0],
            profit_target_pct=[5.0],
            dca_tranches=[1],
        )

        config = BacktestConfig(initial_capital=1000.0)
        optimizer = Optimizer(declining_dataset)
        result = optimizer.grid_search(space, config, max_combinations=10)

        assert len(result.runs) == 2
        assert result.best_by_sharpe is not None
        assert result.best_by_return is not None

    def test_format_results_table(self, declining_dataset: BacktestDataset) -> None:
        space = ParameterSpace(
            rsi_oversold=[30],
            rsi_extremely_oversold=[20],
            buy_threshold=[40],
            small_buy_pct=[0.05],
            medium_buy_pct=[0.10],
            large_buy_pct=[0.20],
            stop_loss_pct=[5.0],
            profit_target_pct=[5.0],
            dca_tranches=[1],
        )

        config = BacktestConfig(initial_capital=1000.0)
        optimizer = Optimizer(declining_dataset)
        result = optimizer.grid_search(space, config)

        table = Optimizer.format_results_table(result)
        assert "Sharpe" in table
        assert "Return%" in table

    def test_empty_results(self) -> None:
        table = Optimizer.format_results_table(
            __import__("bitbot.backtesting.optimizer", fromlist=["OptimizationResult"]).OptimizationResult(
                runs=[], best_by_sharpe=None, best_by_return=None,
                best_by_win_rate=None, total_combinations=0,
            )
        )
        assert "No optimization results" in table
