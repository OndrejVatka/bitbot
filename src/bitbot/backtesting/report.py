"""Report generation — text summaries and matplotlib charts.

Charts require matplotlib (optional dependency). Text output always works.
"""

from __future__ import annotations

import logging
from pathlib import Path

from bitbot.backtesting.engine import BacktestResult
from bitbot.backtesting.metrics import PerformanceMetrics

logger = logging.getLogger(__name__)


class BacktestReport:
    """Generates text summaries and optional matplotlib visualizations."""

    @staticmethod
    def text_summary(metrics: PerformanceMetrics, result: BacktestResult) -> str:
        """Generate a terminal-friendly text report.

        Args:
            metrics: Computed performance metrics.
            result: Raw backtest result.

        Returns:
            Multi-line formatted string.
        """
        sep = "=" * 60
        lines = [
            sep,
            "  BACKTEST REPORT",
            sep,
            "",
            f"  Period:  {result.start_time:%Y-%m-%d} to {result.end_time:%Y-%m-%d}",
            f"  Symbol:  {result.config.symbol}",
            f"  Capital: ${result.config.initial_capital:,.2f}",
            f"  Candles: {result.candles_processed:,}",
            "",
            "  RETURNS",
            f"  {'Strategy:':<28} {metrics.total_return_pct:>+8.2f}%  (${metrics.total_return_usdt:>+,.2f})",
            f"  {'Buy & Hold:':<28} {metrics.buy_and_hold_return_pct:>+8.2f}%",
            f"  {'Alpha:':<28} {metrics.alpha_vs_buy_hold_pct:>+8.2f}%",
            f"  {'Final Value:':<28} ${result.final_portfolio_value:>12,.2f}",
            "",
            "  RISK-ADJUSTED",
            f"  {'Sharpe Ratio:':<28} {metrics.sharpe_ratio:>8.2f}",
            f"  {'Sortino Ratio:':<28} {metrics.sortino_ratio:>8.2f}",
            f"  {'Calmar Ratio:':<28} {metrics.calmar_ratio:>8.2f}",
            "",
            "  DRAWDOWN",
            f"  {'Max Drawdown:':<28} {metrics.max_drawdown_pct:>8.2f}%",
            f"  {'Max DD Duration:':<28} {metrics.max_drawdown_duration_hours:>7.1f}h",
            f"  {'Avg Drawdown:':<28} {metrics.avg_drawdown_pct:>8.2f}%",
            "",
            "  TRADES",
            f"  {'Total Trades:':<28} {metrics.total_trades:>8d}",
            f"  {'Positions Closed:':<28} {len(result.positions_closed):>8d}",
            f"  {'Win Rate:':<28} {metrics.win_rate_pct:>7.1f}%",
            f"  {'Winning:':<28} {metrics.winning_trades:>8d}",
            f"  {'Losing:':<28} {metrics.losing_trades:>8d}",
            f"  {'Avg Win:':<28} {metrics.avg_win_pct:>+7.2f}%",
            f"  {'Avg Loss:':<28} {metrics.avg_loss_pct:>+7.2f}%",
            f"  {'Profit Factor:':<28} {metrics.profit_factor:>8.2f}",
            f"  {'Gain/Loss Ratio:':<28} {metrics.avg_gain_loss_ratio:>8.2f}",
            "",
            "  ACTIVITY",
            f"  {'Time in Market:':<28} {metrics.time_in_market_pct:>7.1f}%",
            f"  {'Avg Position Duration:':<28} {metrics.avg_position_duration_hours:>7.1f}h",
            f"  {'Total Fees Paid:':<28} ${metrics.total_fees_paid:>10,.2f}",
            "",
        ]

        # Monthly returns table
        if metrics.monthly_returns:
            lines.append("  MONTHLY RETURNS")
            for month, ret in metrics.monthly_returns.items():
                bar = "+" * max(0, int(ret / 2)) if ret > 0 else "-" * max(0, int(abs(ret) / 2))
                lines.append(f"  {month}  {ret:>+7.2f}%  {bar}")
            lines.append("")

        lines.append(sep)
        return "\n".join(lines)

    @staticmethod
    def plot_equity_curve(
        result: BacktestResult,
        save_path: str | None = None,
    ) -> None:
        """Plot portfolio value over time with buy-and-hold comparison.

        Shows equity curve, buy-and-hold line, and drawdown shading.
        Requires matplotlib.

        Args:
            result: Completed BacktestResult.
            save_path: Optional file path to save the chart. Shows interactively if None.
        """
        try:
            import matplotlib.pyplot as plt
            import matplotlib.dates as mdates
        except ImportError:
            logger.warning("matplotlib not installed — skipping equity curve plot")
            return

        equity = result.equity_curve
        if equity.empty:
            logger.warning("No equity data to plot")
            return

        fig, (ax1, ax2) = plt.subplots(
            2, 1, figsize=(14, 8), height_ratios=[3, 1], sharex=True
        )

        # Equity curve
        ax1.plot(equity.index, equity["portfolio_value"], label="Strategy", linewidth=1.5)

        # Buy-and-hold line
        initial = result.config.initial_capital
        start_price = equity["portfolio_value"].iloc[0]
        bh_factor = result.buy_and_hold_value / initial
        bh_line = [initial + (initial * bh_factor - initial) * i / (len(equity) - 1)
                    for i in range(len(equity))]
        ax1.plot(equity.index, bh_line, label="Buy & Hold", linewidth=1, linestyle="--", alpha=0.7)

        # Buy/sell markers
        buys = [t for t in result.trades if t.side == "buy" and t.reason == "signal"]
        sells = [t for t in result.trades if t.side == "sell"]

        if buys:
            buy_times = [t.timestamp for t in buys]
            buy_vals = []
            for t in buys:
                if t.timestamp in equity.index:
                    buy_vals.append(equity.loc[t.timestamp, "portfolio_value"])
                else:
                    buy_vals.append(None)
            valid = [(x, y) for x, y in zip(buy_times, buy_vals) if y is not None]
            if valid:
                ax1.scatter(
                    [v[0] for v in valid],
                    [v[1] for v in valid],
                    marker="^", color="green", s=40, alpha=0.7, label="Buy",
                )

        if sells:
            sell_times = [t.timestamp for t in sells]
            sell_vals = []
            for t in sells:
                if t.timestamp in equity.index:
                    sell_vals.append(equity.loc[t.timestamp, "portfolio_value"])
                else:
                    sell_vals.append(None)
            valid = [(x, y) for x, y in zip(sell_times, sell_vals) if y is not None]
            if valid:
                ax1.scatter(
                    [v[0] for v in valid],
                    [v[1] for v in valid],
                    marker="v", color="red", s=40, alpha=0.7, label="Sell",
                )

        ax1.set_ylabel("Portfolio Value ($)")
        ax1.set_title(f"Backtest: {result.config.symbol} ({result.start_time:%Y-%m-%d} to {result.end_time:%Y-%m-%d})")
        ax1.legend()
        ax1.grid(True, alpha=0.3)

        # Drawdown subplot
        values = equity["portfolio_value"].values
        peak = pd.Series(values).cummax()
        drawdown = (peak - values) / peak * 100

        ax2.fill_between(equity.index, 0, -drawdown, color="red", alpha=0.3)
        ax2.set_ylabel("Drawdown (%)")
        ax2.set_xlabel("Date")
        ax2.grid(True, alpha=0.3)

        ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
        fig.autofmt_xdate()
        plt.tight_layout()

        if save_path:
            Path(save_path).parent.mkdir(parents=True, exist_ok=True)
            plt.savefig(save_path, dpi=150, bbox_inches="tight")
            logger.info("Equity curve saved to %s", save_path)
        else:
            plt.show()

        plt.close(fig)

    @staticmethod
    def plot_monthly_returns(
        metrics: PerformanceMetrics,
        save_path: str | None = None,
    ) -> None:
        """Bar chart of monthly returns.

        Args:
            metrics: Computed PerformanceMetrics.
            save_path: Optional file path to save. Shows interactively if None.
        """
        try:
            import matplotlib.pyplot as plt
        except ImportError:
            logger.warning("matplotlib not installed — skipping monthly returns plot")
            return

        if not metrics.monthly_returns:
            logger.warning("No monthly return data to plot")
            return

        months = list(metrics.monthly_returns.keys())
        returns = list(metrics.monthly_returns.values())
        colors = ["green" if r >= 0 else "red" for r in returns]

        fig, ax = plt.subplots(figsize=(12, 5))
        ax.bar(months, returns, color=colors, alpha=0.7)
        ax.axhline(y=0, color="black", linewidth=0.5)
        ax.set_ylabel("Return (%)")
        ax.set_title("Monthly Returns")
        ax.grid(True, alpha=0.3, axis="y")
        plt.xticks(rotation=45)
        plt.tight_layout()

        if save_path:
            Path(save_path).parent.mkdir(parents=True, exist_ok=True)
            plt.savefig(save_path, dpi=150, bbox_inches="tight")
            logger.info("Monthly returns chart saved to %s", save_path)
        else:
            plt.show()

        plt.close(fig)

    @staticmethod
    def plot_drawdown(
        result: BacktestResult,
        save_path: str | None = None,
    ) -> None:
        """Underwater plot — drawdown from peak over time.

        Args:
            result: Completed BacktestResult.
            save_path: Optional file path to save. Shows interactively if None.
        """
        try:
            import matplotlib.pyplot as plt
            import matplotlib.dates as mdates
        except ImportError:
            logger.warning("matplotlib not installed — skipping drawdown plot")
            return

        equity = result.equity_curve
        if equity.empty:
            logger.warning("No equity data to plot")
            return

        values = equity["portfolio_value"].values
        peak = pd.Series(values).cummax()
        drawdown = (peak - values) / peak * 100

        fig, ax = plt.subplots(figsize=(14, 4))
        ax.fill_between(equity.index, 0, -drawdown, color="red", alpha=0.4)
        ax.plot(equity.index, -drawdown, color="darkred", linewidth=0.5)
        ax.set_ylabel("Drawdown (%)")
        ax.set_xlabel("Date")
        ax.set_title(f"Drawdown: {result.config.symbol}")
        ax.grid(True, alpha=0.3)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
        fig.autofmt_xdate()
        plt.tight_layout()

        if save_path:
            Path(save_path).parent.mkdir(parents=True, exist_ok=True)
            plt.savefig(save_path, dpi=150, bbox_inches="tight")
            logger.info("Drawdown chart saved to %s", save_path)
        else:
            plt.show()

        plt.close(fig)
