"""Parameter optimization via grid search and walk-forward validation.

Sweeps strategy parameters and finds optimal settings, with walk-forward
analysis to detect overfitting.
"""

from __future__ import annotations

import copy
import itertools
import logging
import random
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field

import pandas as pd

from bitbot.backtesting.data_loader import BacktestDataset
from bitbot.backtesting.engine import BacktestConfig, BacktestEngine, BacktestResult
from bitbot.backtesting.metrics import MetricsCalculator, PerformanceMetrics

logger = logging.getLogger(__name__)


@dataclass
class ParameterSpace:
    """Defines the search space for parameter optimization.

    Each field is a list of values to try in grid search.
    """

    rsi_oversold: list[int] = field(default_factory=lambda: [25, 30, 35])
    rsi_extremely_oversold: list[int] = field(default_factory=lambda: [15, 20, 25])
    buy_threshold: list[int] = field(default_factory=lambda: [50, 55, 60, 65, 70])
    small_buy_pct: list[float] = field(default_factory=lambda: [0.03, 0.05, 0.07])
    medium_buy_pct: list[float] = field(default_factory=lambda: [0.08, 0.10, 0.12])
    large_buy_pct: list[float] = field(default_factory=lambda: [0.15, 0.20, 0.25])
    stop_loss_pct: list[float] = field(default_factory=lambda: [3.0, 5.0, 7.0])
    profit_target_pct: list[float] = field(default_factory=lambda: [3.0, 5.0, 7.0, 10.0])
    dca_tranches: list[int] = field(default_factory=lambda: [1, 2, 3])

    def grid_combinations(self) -> list[dict]:
        """Generate all parameter combinations (cartesian product)."""
        keys = [
            "rsi_oversold", "rsi_extremely_oversold", "buy_threshold",
            "small_buy_pct", "medium_buy_pct", "large_buy_pct",
            "stop_loss_pct", "profit_target_pct", "dca_tranches",
        ]
        values = [getattr(self, k) for k in keys]
        return [dict(zip(keys, combo)) for combo in itertools.product(*values)]

    def random_sample(self, n: int, seed: int = 42) -> list[dict]:
        """Randomly sample n parameter combinations."""
        all_combos = self.grid_combinations()
        rng = random.Random(seed)
        return rng.sample(all_combos, min(n, len(all_combos)))


@dataclass
class OptimizationRun:
    """Result of a single optimization run (parameter set + metrics)."""

    params: dict
    metrics: PerformanceMetrics
    result: BacktestResult


@dataclass
class OptimizationResult:
    """Results of a complete parameter sweep."""

    runs: list[OptimizationRun]
    best_by_sharpe: OptimizationRun | None
    best_by_return: OptimizationRun | None
    best_by_win_rate: OptimizationRun | None
    total_combinations: int


def _apply_params(base: BacktestConfig, params: dict) -> BacktestConfig:
    """Create a new BacktestConfig with overridden parameters."""
    cfg = copy.deepcopy(base)

    if "rsi_oversold" in params:
        cfg.signals.rsi_oversold = params["rsi_oversold"]
    if "rsi_extremely_oversold" in params:
        cfg.signals.rsi_extremely_oversold = params["rsi_extremely_oversold"]
    if "buy_threshold" in params:
        cfg.scoring.buy_threshold = params["buy_threshold"]
        # Update the small buy range lower bound to match
        cfg.scoring.small_buy_range = [params["buy_threshold"], cfg.scoring.medium_buy_range[0] - 1]
    if "small_buy_pct" in params:
        cfg.scoring.small_buy_pct = params["small_buy_pct"]
    if "medium_buy_pct" in params:
        cfg.scoring.medium_buy_pct = params["medium_buy_pct"]
    if "large_buy_pct" in params:
        cfg.scoring.large_buy_pct = params["large_buy_pct"]
    if "stop_loss_pct" in params:
        cfg.risk.stop_loss_pct = params["stop_loss_pct"]
    if "profit_target_pct" in params:
        cfg.selling.profit_target_pct = params["profit_target_pct"]
    if "dca_tranches" in params:
        cfg.dca.tranches = params["dca_tranches"]

    return cfg


def _run_single_backtest(
    config: BacktestConfig, dataset: BacktestDataset
) -> BacktestResult:
    """Run a single backtest (used for process pool execution)."""
    engine = BacktestEngine(config)
    return engine.run(dataset)


class Optimizer:
    """Parameter optimization engine with grid search and walk-forward validation."""

    def __init__(self, dataset: BacktestDataset) -> None:
        self._dataset = dataset

    def grid_search(
        self,
        space: ParameterSpace,
        base_config: BacktestConfig,
        metric: str = "sharpe_ratio",
        max_combinations: int = 500,
        max_workers: int | None = None,
    ) -> OptimizationResult:
        """Run backtest for each parameter combination.

        If the grid exceeds max_combinations, falls back to random sampling.

        Args:
            space: Parameter search space.
            base_config: Base configuration to override.
            metric: Metric to optimize (attribute name on PerformanceMetrics).
            max_combinations: Maximum number of combinations to test.
            max_workers: Max parallel workers (None = CPU count).

        Returns:
            OptimizationResult with all runs and best performers.
        """
        all_combos = space.grid_combinations()
        total = len(all_combos)

        if total > max_combinations:
            logger.info(
                "Grid has %d combos, exceeds max %d — using random sampling",
                total, max_combinations,
            )
            combos = space.random_sample(max_combinations)
        else:
            combos = all_combos

        logger.info("Starting optimization: %d parameter combinations", len(combos))

        runs: list[OptimizationRun] = []

        for idx, params in enumerate(combos):
            config = _apply_params(base_config, params)
            try:
                result = _run_single_backtest(config, self._dataset)
                metrics = MetricsCalculator.calculate(result)
                runs.append(OptimizationRun(
                    params=params, metrics=metrics, result=result,
                ))
            except Exception as e:
                logger.warning("Backtest failed for params %s: %s", params, e)
                continue

            if (idx + 1) % 10 == 0:
                logger.info("Progress: %d/%d combinations tested", idx + 1, len(combos))

        logger.info("Optimization complete: %d/%d runs succeeded", len(runs), len(combos))

        return self._build_result(runs, total)

    def walk_forward(
        self,
        space: ParameterSpace,
        base_config: BacktestConfig,
        in_sample_pct: float = 0.7,
        metric: str = "sharpe_ratio",
        max_combinations: int = 200,
    ) -> tuple[OptimizationResult, OptimizationResult]:
        """Walk-forward optimization to detect overfitting.

        Splits data into in-sample (optimization) and out-of-sample (validation).
        Returns both results for comparison.

        Args:
            space: Parameter search space.
            base_config: Base configuration.
            in_sample_pct: Fraction of data for in-sample optimization.
            metric: Metric to optimize.
            max_combinations: Max combinations per phase.

        Returns:
            (in_sample_result, out_of_sample_result) tuple.
        """
        candles = self._dataset.candles_15m
        split_idx = int(len(candles) * in_sample_pct)
        split_ts = candles.index[split_idx].to_pydatetime()

        logger.info(
            "Walk-forward split: in-sample up to %s (%d candles), "
            "out-of-sample from %s (%d candles)",
            split_ts, split_idx, split_ts, len(candles) - split_idx,
        )

        # In-sample dataset
        is_dataset = BacktestDataset(
            candles_15m=candles.iloc[:split_idx],
            candles_4h=self._dataset.candles_4h[self._dataset.candles_4h.index <= candles.index[split_idx]],
            symbol=self._dataset.symbol,
            start=self._dataset.start,
            end=split_ts,
        )

        # Out-of-sample dataset (includes some lookback for indicator warmup)
        lookback = base_config.primary_window
        oos_start = max(0, split_idx - lookback)
        oos_dataset = BacktestDataset(
            candles_15m=candles.iloc[oos_start:],
            candles_4h=self._dataset.candles_4h,
            symbol=self._dataset.symbol,
            start=split_ts,
            end=self._dataset.end,
        )

        # Optimize on in-sample
        is_optimizer = Optimizer(is_dataset)
        is_result = is_optimizer.grid_search(
            space, base_config, metric, max_combinations
        )

        if not is_result.best_by_sharpe:
            logger.warning("No successful in-sample runs")
            return is_result, is_result

        # Validate best params on out-of-sample
        best_params_list = []
        for run in sorted(
            is_result.runs,
            key=lambda r: getattr(r.metrics, metric, 0),
            reverse=True,
        )[:5]:
            best_params_list.append(run.params)

        oos_runs: list[OptimizationRun] = []
        for params in best_params_list:
            config = _apply_params(base_config, params)
            try:
                result = _run_single_backtest(config, oos_dataset)
                metrics = MetricsCalculator.calculate(result)
                oos_runs.append(OptimizationRun(
                    params=params, metrics=metrics, result=result,
                ))
            except Exception as e:
                logger.warning("OOS backtest failed: %s", e)

        oos_result = self._build_result(oos_runs, len(best_params_list))

        # Log overfitting warning
        if is_result.best_by_sharpe and oos_result.best_by_sharpe:
            is_sharpe = is_result.best_by_sharpe.metrics.sharpe_ratio
            oos_sharpe = oos_result.best_by_sharpe.metrics.sharpe_ratio
            if is_sharpe > 0 and oos_sharpe > 0 and is_sharpe > 2 * oos_sharpe:
                logger.warning(
                    "OVERFITTING WARNING: in-sample Sharpe (%.2f) is >2x "
                    "out-of-sample Sharpe (%.2f)",
                    is_sharpe, oos_sharpe,
                )

        return is_result, oos_result

    @staticmethod
    def _build_result(
        runs: list[OptimizationRun], total_combinations: int
    ) -> OptimizationResult:
        """Build OptimizationResult from completed runs."""
        if not runs:
            return OptimizationResult(
                runs=runs,
                best_by_sharpe=None,
                best_by_return=None,
                best_by_win_rate=None,
                total_combinations=total_combinations,
            )

        best_sharpe = max(runs, key=lambda r: r.metrics.sharpe_ratio)
        best_return = max(runs, key=lambda r: r.metrics.total_return_pct)
        best_winrate = max(runs, key=lambda r: r.metrics.win_rate_pct)

        return OptimizationResult(
            runs=runs,
            best_by_sharpe=best_sharpe,
            best_by_return=best_return,
            best_by_win_rate=best_winrate,
            total_combinations=total_combinations,
        )

    @staticmethod
    def format_results_table(opt_result: OptimizationResult, top_n: int = 10) -> str:
        """Format the top N results as a text table.

        Args:
            opt_result: Completed optimization result.
            top_n: Number of top results to show.

        Returns:
            Formatted text table.
        """
        if not opt_result.runs:
            return "No optimization results."

        sorted_runs = sorted(
            opt_result.runs,
            key=lambda r: r.metrics.sharpe_ratio,
            reverse=True,
        )[:top_n]

        header = (
            f"{'#':>3}  {'Sharpe':>7}  {'Return%':>8}  {'WinRate':>7}  "
            f"{'MaxDD%':>7}  {'Trades':>6}  Parameters"
        )
        sep = "-" * 100

        lines = [sep, header, sep]
        for i, run in enumerate(sorted_runs, 1):
            m = run.metrics
            params_str = ", ".join(f"{k}={v}" for k, v in sorted(run.params.items()))
            lines.append(
                f"{i:>3}  {m.sharpe_ratio:>7.2f}  {m.total_return_pct:>+7.2f}%  "
                f"{m.win_rate_pct:>6.1f}%  {m.max_drawdown_pct:>6.2f}%  "
                f"{m.total_trades:>6d}  {params_str}"
            )
        lines.append(sep)

        return "\n".join(lines)
