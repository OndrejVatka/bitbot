"""Stress testing against known historical crash periods.

Runs the backtest strategy across major Bitcoin crash events to evaluate
how the risk management system handles extreme market conditions.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from bitbot.backtesting.data_loader import DataLoader
from bitbot.backtesting.engine import BacktestConfig, BacktestEngine, BacktestResult
from bitbot.backtesting.metrics import MetricsCalculator, PerformanceMetrics

logger = logging.getLogger(__name__)

# Named historical crash/volatility periods for BTC
CRASH_PERIODS: dict[str, tuple[datetime, datetime]] = {
    "covid_crash_2020": (
        datetime(2020, 2, 12, tzinfo=timezone.utc),
        datetime(2020, 3, 25, tzinfo=timezone.utc),
    ),
    "may_crash_2021": (
        datetime(2021, 5, 8, tzinfo=timezone.utc),
        datetime(2021, 6, 22, tzinfo=timezone.utc),
    ),
    "luna_collapse_2022": (
        datetime(2022, 5, 5, tzinfo=timezone.utc),
        datetime(2022, 6, 20, tzinfo=timezone.utc),
    ),
    "ftx_collapse_2022": (
        datetime(2022, 11, 1, tzinfo=timezone.utc),
        datetime(2022, 12, 15, tzinfo=timezone.utc),
    ),
    "svb_crisis_2023": (
        datetime(2023, 3, 8, tzinfo=timezone.utc),
        datetime(2023, 3, 20, tzinfo=timezone.utc),
    ),
}


@dataclass
class StressTestResult:
    """Results across all crash scenarios."""

    results: dict[str, tuple[BacktestResult, PerformanceMetrics]]

    def format_comparison_table(self) -> str:
        """Format a comparison table across all scenarios.

        Returns:
            Multi-line text table: scenario | return | max_dd | sharpe | trades | win_rate
        """
        if not self.results:
            return "No stress test results."

        sep = "=" * 90
        header = (
            f"{'Scenario':<24}  {'Return%':>8}  {'MaxDD%':>7}  {'Sharpe':>7}  "
            f"{'Trades':>6}  {'WinRate':>7}  {'B&H%':>7}"
        )

        lines = [sep, "  STRESS TEST RESULTS", sep, header, "-" * 90]

        for name, (result, metrics) in self.results.items():
            lines.append(
                f"{name:<24}  {metrics.total_return_pct:>+7.2f}%  "
                f"{metrics.max_drawdown_pct:>6.2f}%  {metrics.sharpe_ratio:>7.2f}  "
                f"{metrics.total_trades:>6d}  {metrics.win_rate_pct:>6.1f}%  "
                f"{metrics.buy_and_hold_return_pct:>+6.2f}%"
            )

        lines.append(sep)

        # Summary
        all_returns = [m.total_return_pct for _, m in self.results.values()]
        all_dds = [m.max_drawdown_pct for _, m in self.results.values()]
        survived = sum(1 for _, m in self.results.values() if m.total_return_pct > -10)

        lines.extend([
            "",
            f"  Scenarios tested:    {len(self.results)}",
            f"  Survived (>-10%):    {survived}/{len(self.results)}",
            f"  Avg return:          {sum(all_returns) / len(all_returns):+.2f}%",
            f"  Worst drawdown:      {max(all_dds):.2f}%",
            "",
        ])

        return "\n".join(lines)


class StressTester:
    """Runs backtests across known crash periods to evaluate strategy resilience."""

    def __init__(self, data_loader: DataLoader, config: BacktestConfig) -> None:
        self._loader = data_loader
        self._config = config

    async def run_all(
        self,
        scenarios: dict[str, tuple[datetime, datetime]] | None = None,
    ) -> StressTestResult:
        """Run backtest for each crash scenario.

        Downloads data if not cached, then runs the engine for each period.

        Args:
            scenarios: Custom scenarios dict. Uses CRASH_PERIODS if None.

        Returns:
            StressTestResult with per-scenario results and metrics.
        """
        periods = scenarios or CRASH_PERIODS
        results: dict[str, tuple[BacktestResult, PerformanceMetrics]] = {}

        for name, (start, end) in periods.items():
            logger.info("Stress testing: %s (%s to %s)", name, start.date(), end.date())

            try:
                dataset = await self._loader.load_dataset(
                    symbol=self._config.symbol,
                    start=start,
                    end=end,
                )

                engine = BacktestEngine(self._config)
                result = engine.run(dataset)
                metrics = MetricsCalculator.calculate(result)

                results[name] = (result, metrics)

                logger.info(
                    "  %s: return=%+.2f%%, max_dd=%.2f%%, trades=%d",
                    name, metrics.total_return_pct, metrics.max_drawdown_pct,
                    metrics.total_trades,
                )
            except Exception as e:
                logger.error("  %s FAILED: %s", name, e)

        return StressTestResult(results=results)
