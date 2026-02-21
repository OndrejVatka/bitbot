"""Performance metrics calculator for backtest results.

Computes standard trading performance metrics: returns, risk-adjusted ratios,
drawdown analysis, win/loss statistics, and comparison vs buy-and-hold.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from bitbot.backtesting.engine import BacktestResult

# 15-minute candles per year: 4 * 24 * 365 = 35,040
PERIODS_PER_YEAR_15M = 35_040


@dataclass
class PerformanceMetrics:
    """Complete performance metrics from a backtest run."""

    # --- Returns ---
    total_return_pct: float
    total_return_usdt: float
    buy_and_hold_return_pct: float
    alpha_vs_buy_hold_pct: float

    # --- Win/Loss ---
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate_pct: float
    avg_win_pct: float
    avg_loss_pct: float
    profit_factor: float
    avg_gain_loss_ratio: float

    # --- Risk-adjusted ---
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float

    # --- Drawdown ---
    max_drawdown_pct: float
    max_drawdown_duration_hours: float
    avg_drawdown_pct: float

    # --- Activity ---
    time_in_market_pct: float
    avg_position_duration_hours: float
    total_fees_paid: float

    # --- Per-period ---
    monthly_returns: dict[str, float]


class MetricsCalculator:
    """Calculates comprehensive performance metrics from a BacktestResult."""

    @staticmethod
    def calculate(result: BacktestResult) -> PerformanceMetrics:
        """Compute all performance metrics from a backtest result.

        Args:
            result: Completed BacktestResult from the engine.

        Returns:
            PerformanceMetrics with all computed values.
        """
        initial = result.config.initial_capital
        final = result.final_portfolio_value
        bh = result.buy_and_hold_value

        # Returns
        total_return_pct = (final - initial) / initial * 100
        total_return_usdt = final - initial
        bh_return_pct = (bh - initial) / initial * 100
        alpha = total_return_pct - bh_return_pct

        # Win/Loss from closed positions
        positions = result.positions_closed
        wins = [p for p in positions if p.pnl > 0]
        losses = [p for p in positions if p.pnl <= 0]

        win_rate = (len(wins) / len(positions) * 100) if positions else 0.0
        avg_win = (sum(p.pnl_pct for p in wins) / len(wins)) if wins else 0.0
        avg_loss = (sum(p.pnl_pct for p in losses) / len(losses)) if losses else 0.0

        gross_profit = sum(p.pnl for p in wins)
        gross_loss = abs(sum(p.pnl for p in losses))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")

        gain_loss_ratio = (avg_win / abs(avg_loss)) if avg_loss != 0 else float("inf")

        # Equity curve analysis
        equity = result.equity_curve
        sharpe = MetricsCalculator._calculate_sharpe(equity)
        sortino = MetricsCalculator._calculate_sortino(equity)
        max_dd_pct, max_dd_hours = MetricsCalculator._calculate_max_drawdown(equity)
        avg_dd_pct = MetricsCalculator._calculate_avg_drawdown(equity)

        # Calmar: annualized return / max drawdown
        duration_years = (
            (result.end_time - result.start_time).total_seconds() / (365.25 * 86400)
        )
        annual_return = (
            total_return_pct / duration_years if duration_years > 0 else 0.0
        )
        calmar = (annual_return / max_dd_pct) if max_dd_pct > 0 else float("inf")

        # Activity
        time_in_market = MetricsCalculator._calculate_time_in_market(equity)
        avg_duration = (
            sum(p.duration_hours for p in positions) / len(positions)
            if positions
            else 0.0
        )

        total_fees = sum(t.fee for t in result.trades)

        # Monthly returns
        monthly = MetricsCalculator._calculate_monthly_returns(equity, initial)

        return PerformanceMetrics(
            total_return_pct=round(total_return_pct, 2),
            total_return_usdt=round(total_return_usdt, 2),
            buy_and_hold_return_pct=round(bh_return_pct, 2),
            alpha_vs_buy_hold_pct=round(alpha, 2),
            total_trades=len(result.trades),
            winning_trades=len(wins),
            losing_trades=len(losses),
            win_rate_pct=round(win_rate, 1),
            avg_win_pct=round(avg_win, 2),
            avg_loss_pct=round(avg_loss, 2),
            profit_factor=round(profit_factor, 2),
            avg_gain_loss_ratio=round(gain_loss_ratio, 2),
            sharpe_ratio=round(sharpe, 2),
            sortino_ratio=round(sortino, 2),
            calmar_ratio=round(calmar, 2),
            max_drawdown_pct=round(max_dd_pct, 2),
            max_drawdown_duration_hours=round(max_dd_hours, 1),
            avg_drawdown_pct=round(avg_dd_pct, 2),
            time_in_market_pct=round(time_in_market, 1),
            avg_position_duration_hours=round(avg_duration, 1),
            total_fees_paid=round(total_fees, 2),
            monthly_returns=monthly,
        )

    @staticmethod
    def _calculate_sharpe(equity: pd.DataFrame) -> float:
        """Annualized Sharpe ratio from 15m equity samples (risk-free rate = 0)."""
        if equity.empty or len(equity) < 2:
            return 0.0

        values = equity["portfolio_value"].values
        returns = np.diff(values) / values[:-1]

        mean_ret = np.mean(returns)
        std_ret = np.std(returns, ddof=1)

        if std_ret == 0:
            return 0.0

        return float(mean_ret / std_ret * math.sqrt(PERIODS_PER_YEAR_15M))

    @staticmethod
    def _calculate_sortino(equity: pd.DataFrame) -> float:
        """Annualized Sortino ratio (uses only downside deviation)."""
        if equity.empty or len(equity) < 2:
            return 0.0

        values = equity["portfolio_value"].values
        returns = np.diff(values) / values[:-1]

        mean_ret = np.mean(returns)
        downside = returns[returns < 0]

        if len(downside) == 0:
            return float("inf") if mean_ret > 0 else 0.0

        downside_std = np.std(downside, ddof=1)
        if downside_std == 0:
            return 0.0

        return float(mean_ret / downside_std * math.sqrt(PERIODS_PER_YEAR_15M))

    @staticmethod
    def _calculate_max_drawdown(equity: pd.DataFrame) -> tuple[float, float]:
        """Calculate maximum drawdown percentage and duration in hours.

        Returns:
            (max_drawdown_pct, duration_hours)
        """
        if equity.empty:
            return 0.0, 0.0

        values = equity["portfolio_value"].values
        timestamps = equity.index

        peak = values[0]
        max_dd = 0.0
        dd_start_idx = 0
        max_dd_start = 0
        max_dd_end = 0

        for i in range(len(values)):
            if values[i] > peak:
                peak = values[i]
                dd_start_idx = i

            dd = (peak - values[i]) / peak * 100
            if dd > max_dd:
                max_dd = dd
                max_dd_start = dd_start_idx
                max_dd_end = i

        if max_dd == 0:
            return 0.0, 0.0

        start_ts = pd.Timestamp(timestamps[max_dd_start])
        end_ts = pd.Timestamp(timestamps[max_dd_end])
        duration_hours = (end_ts - start_ts).total_seconds() / 3600

        return max_dd, duration_hours

    @staticmethod
    def _calculate_avg_drawdown(equity: pd.DataFrame) -> float:
        """Calculate average drawdown percentage across all drawdown periods."""
        if equity.empty:
            return 0.0

        values = equity["portfolio_value"].values
        peak = values[0]
        drawdowns: list[float] = []

        for val in values:
            if val > peak:
                peak = val
            dd = (peak - val) / peak * 100
            if dd > 0:
                drawdowns.append(dd)

        return float(np.mean(drawdowns)) if drawdowns else 0.0

    @staticmethod
    def _calculate_time_in_market(equity: pd.DataFrame) -> float:
        """Percentage of time with any capital in open positions."""
        if equity.empty:
            return 0.0

        in_market = (equity["exposure"] > 0).sum()
        return float(in_market / len(equity) * 100)

    @staticmethod
    def _calculate_monthly_returns(
        equity: pd.DataFrame, initial_capital: float
    ) -> dict[str, float]:
        """Calculate return percentage for each calendar month."""
        if equity.empty:
            return {}

        monthly: dict[str, float] = {}
        values = equity["portfolio_value"]

        # Group by year-month (strip timezone to avoid PeriodArray warning)
        idx = values.index.tz_localize(None) if values.index.tz else values.index
        grouped = values.groupby(idx.to_period("M"))

        prev_value = initial_capital
        for period, group in grouped:
            end_value = float(group.iloc[-1])
            ret_pct = (end_value - prev_value) / prev_value * 100
            monthly[str(period)] = round(ret_pct, 2)
            prev_value = end_value

        return monthly
