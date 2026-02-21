"""Core backtest engine — replays historical candles through the trading pipeline.

The engine is fully synchronous: no async, no WebSocket, no sleep.
It reuses the production TechnicalSignals, SignalScorer, Portfolio, and
RiskManager modules with a SimulatedClock for time management.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import pandas as pd

from bitbot.backtesting.clock import SimulatedClock
from bitbot.backtesting.data_loader import BacktestDataset
from bitbot.config import (
    DCAConfig,
    FeesConfig,
    RiskConfig,
    ScoringConfig,
    SellingConfig,
    SignalsConfig,
)
from bitbot.signals.scorer import SignalScorer
from bitbot.signals.technical import TechnicalSignals
from bitbot.trading.portfolio import Portfolio
from bitbot.trading.risk_manager import RiskManager

logger = logging.getLogger(__name__)


@dataclass
class BacktestConfig:
    """Overridable parameters for a single backtest run."""

    symbol: str = "BTCUSDT"
    initial_capital: float = 1000.0

    # Strategy parameters (override any config section)
    signals: SignalsConfig = field(default_factory=SignalsConfig)
    scoring: ScoringConfig = field(default_factory=ScoringConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    selling: SellingConfig = field(default_factory=SellingConfig)
    fees: FeesConfig = field(default_factory=FeesConfig)
    dca: DCAConfig = field(default_factory=DCAConfig)

    # Rolling window sizes for indicator calculation
    primary_window: int = 250
    trend_window: int = 250


@dataclass
class TradeRecord:
    """A single trade executed during the backtest."""

    timestamp: datetime
    side: str  # "buy" or "sell"
    price: float
    quantity: float
    usdt_value: float
    fee: float
    reason: str  # "signal", "dca", "stop_loss", "profit_target"
    position_id: str
    score: int | None = None


@dataclass
class PositionSummary:
    """Summary of a closed position."""

    position_id: str
    entry_time: datetime
    exit_time: datetime
    avg_entry_price: float
    exit_price: float
    quantity: float
    tranches: int
    pnl: float
    pnl_pct: float
    duration_hours: float


@dataclass
class BacktestResult:
    """Complete output of a single backtest run."""

    config: BacktestConfig
    trades: list[TradeRecord]
    equity_curve: pd.DataFrame  # columns: timestamp, portfolio_value, cash, exposure
    positions_closed: list[PositionSummary]
    start_time: datetime
    end_time: datetime
    candles_processed: int
    final_portfolio_value: float
    buy_and_hold_value: float


@dataclass
class _PendingDCA:
    """A scheduled DCA tranche waiting for its execution time."""

    position_id: str
    execute_at: datetime
    usdt_amount: float
    tranches_remaining: int
    dip_speed: float


class BacktestEngine:
    """Replays historical candles through the full trading pipeline.

    Uses production modules (TechnicalSignals, SignalScorer, Portfolio,
    RiskManager) with a SimulatedClock for deterministic time progression.
    """

    def __init__(self, config: BacktestConfig) -> None:
        self._config = config

    def run(self, dataset: BacktestDataset) -> BacktestResult:
        """Execute the backtest on a pre-loaded dataset.

        Iterates every 15m candle, running:
        1. Advance simulated clock
        2. Process pending DCA tranches
        3. Calculate technical signals via rolling window
        4. Score confidence → decide buy/hold
        5. Execute buys (risk check → open position → schedule DCA)
        6. Check stop-losses and profit targets
        7. Update risk tracking
        8. Record equity curve point

        Args:
            dataset: Pre-loaded BacktestDataset with 15m and 4h candles.

        Returns:
            BacktestResult with all trades, equity curve, and position summaries.
        """
        cfg = self._config
        candles_15m = dataset.candles_15m
        candles_4h = dataset.candles_4h

        if len(candles_15m) == 0:
            raise ValueError("Dataset has no 15m candles")

        # Initialize simulated clock at first candle
        first_ts = candles_15m.index[0].to_pydatetime()
        if first_ts.tzinfo is None:
            first_ts = first_ts.replace(tzinfo=timezone.utc)
        clock = SimulatedClock(first_ts)

        # Initialize modules with simulated clock
        tech = TechnicalSignals(cfg.signals)
        scorer = SignalScorer(cfg.scoring)
        portfolio = Portfolio(
            initial_capital=cfg.initial_capital,
            fees_config=cfg.fees,
            selling_config=cfg.selling,
            clock=clock,
        )
        risk = RiskManager(
            config=cfg.risk,
            portfolio=portfolio,
            initial_capital=cfg.initial_capital,
            clock=clock,
        )

        # State tracking
        trades: list[TradeRecord] = []
        positions_closed: list[PositionSummary] = []
        equity_points: list[dict] = []
        pending_dcas: list[_PendingDCA] = []

        # Buy-and-hold reference: buy BTC at first scored candle's price
        scored_start_idx = dataset.scored_start_index
        start_price = float(candles_15m["close"].iloc[scored_start_idx])
        bh_quantity = cfg.initial_capital / start_price

        scored_start_ts = candles_15m.index[scored_start_idx].to_pydatetime()
        if scored_start_ts.tzinfo is None:
            scored_start_ts = scored_start_ts.replace(tzinfo=timezone.utc)

        candles_processed = 0

        for i in range(len(candles_15m)):
            current_ts = candles_15m.index[i].to_pydatetime()
            if current_ts.tzinfo is None:
                current_ts = current_ts.replace(tzinfo=timezone.utc)

            clock.advance_to(current_ts)
            current_price = float(candles_15m["close"].iloc[i])
            prices = {cfg.symbol: current_price}

            # --- Process pending DCA tranches ---
            self._process_dcas(
                pending_dcas, current_ts, current_price, prices,
                cfg, portfolio, risk, trades,
            )

            # Skip signal analysis during warmup period
            if i < scored_start_idx:
                continue

            candles_processed += 1

            # --- Slice rolling windows ---
            window_start = max(0, i - cfg.primary_window + 1)
            window_15m = candles_15m.iloc[window_start:i + 1]

            # 4h window: all closed 4h candles up to current time
            mask_4h = candles_4h.index <= candles_15m.index[i]
            window_4h = candles_4h[mask_4h].tail(cfg.trend_window)

            # Need minimum 50 candles for technical analysis
            if len(window_15m) < 50:
                continue

            # --- Technical analysis ---
            try:
                result = tech.analyze(window_15m, window_4h)
            except Exception as e:
                logger.debug("Technical analysis failed at %s: %s", current_ts, e)
                continue

            # --- Score (technical only, no LLM) ---
            score_result = scorer.calculate_score(result.signals_dict)

            # --- Execute buy if score meets threshold ---
            if score_result.action == "buy":
                available = portfolio.get_available_capital()
                buy_amount = available * score_result.position_size_pct
                tranche_count = cfg.dca.tranches
                first_tranche = buy_amount / tranche_count

                risk_check = risk.can_open_position(buy_amount, prices)
                if risk_check.allowed:
                    fill_price, fee, quantity = self._simulate_buy(
                        current_price, first_tranche, cfg.fees
                    )
                    position = portfolio.open_position(cfg.symbol, fill_price, first_tranche)

                    trades.append(TradeRecord(
                        timestamp=current_ts,
                        side="buy",
                        price=fill_price,
                        quantity=quantity,
                        usdt_value=first_tranche,
                        fee=fee,
                        reason="signal",
                        position_id=position.id,
                        score=score_result.score,
                    ))

                    # Schedule remaining DCA tranches
                    if tranche_count > 1:
                        speed_factor = max(0.0, min(1.0, abs(result.dip_speed)))
                        interval_minutes = (
                            cfg.dca.min_interval_minutes
                            + (cfg.dca.max_interval_minutes - cfg.dca.min_interval_minutes)
                            * speed_factor
                        )
                        execute_at = current_ts + timedelta(minutes=interval_minutes)
                        pending_dcas.append(_PendingDCA(
                            position_id=position.id,
                            execute_at=execute_at,
                            usdt_amount=first_tranche,
                            tranches_remaining=tranche_count - 1,
                            dip_speed=result.dip_speed,
                        ))

            # --- Check stop-losses ---
            stop_loss_ids = risk.check_stop_losses(prices)
            for pos_id in stop_loss_ids:
                pos = portfolio.get_position(pos_id)
                if pos:
                    fill_price, fee, _ = self._simulate_sell(
                        current_price, pos.total_quantity, cfg.fees
                    )
                    pnl = portfolio.close_position(pos_id, fill_price)
                    risk.record_stop_loss()

                    # Cancel pending DCAs for this position
                    pending_dcas = [d for d in pending_dcas if d.position_id != pos_id]

                    trades.append(TradeRecord(
                        timestamp=current_ts,
                        side="sell",
                        price=fill_price,
                        quantity=pos.total_quantity,
                        usdt_value=pos.total_quantity * fill_price,
                        fee=fee,
                        reason="stop_loss",
                        position_id=pos_id,
                    ))

                    positions_closed.append(self._summarize_position(pos, fill_price, pnl))

            # --- Check profit targets ---
            profit_ids = risk.check_profit_targets(prices)
            for pos_id in profit_ids:
                pos = portfolio.get_position(pos_id)
                if pos:
                    fill_price, fee, _ = self._simulate_sell(
                        current_price, pos.total_quantity, cfg.fees
                    )
                    pnl = portfolio.close_position(pos_id, fill_price)

                    # Cancel pending DCAs for this position
                    pending_dcas = [d for d in pending_dcas if d.position_id != pos_id]

                    trades.append(TradeRecord(
                        timestamp=current_ts,
                        side="sell",
                        price=fill_price,
                        quantity=pos.total_quantity,
                        usdt_value=pos.total_quantity * fill_price,
                        fee=fee,
                        reason="profit_target",
                        position_id=pos_id,
                    ))

                    positions_closed.append(self._summarize_position(pos, fill_price, pnl))

            # --- Update risk tracking ---
            risk.update_tracking(prices)

            # --- Record equity curve point ---
            total_value = portfolio.get_total_value(prices)
            equity_points.append({
                "timestamp": current_ts,
                "portfolio_value": total_value,
                "cash": portfolio.cash,
                "exposure": portfolio.get_total_exposure(prices),
            })

        # Build final results
        end_price = float(candles_15m["close"].iloc[-1])
        final_prices = {cfg.symbol: end_price}
        final_value = portfolio.get_total_value(final_prices)
        bh_value = bh_quantity * end_price

        equity_df = pd.DataFrame(equity_points)
        if not equity_df.empty:
            equity_df.set_index("timestamp", inplace=True)

        end_ts = candles_15m.index[-1].to_pydatetime()
        if end_ts.tzinfo is None:
            end_ts = end_ts.replace(tzinfo=timezone.utc)

        logger.info(
            "Backtest complete: %d candles, %d trades, final=$%.2f, B&H=$%.2f",
            candles_processed,
            len(trades),
            final_value,
            bh_value,
        )

        return BacktestResult(
            config=cfg,
            trades=trades,
            equity_curve=equity_df,
            positions_closed=positions_closed,
            start_time=scored_start_ts,
            end_time=end_ts,
            candles_processed=candles_processed,
            final_portfolio_value=final_value,
            buy_and_hold_value=bh_value,
        )

    def _process_dcas(
        self,
        pending_dcas: list[_PendingDCA],
        current_ts: datetime,
        current_price: float,
        prices: dict[str, float],
        cfg: BacktestConfig,
        portfolio: Portfolio,
        risk: RiskManager,
        trades: list[TradeRecord],
    ) -> None:
        """Execute any DCA tranches that are due at the current candle time."""
        executed_indices: list[int] = []

        for idx, dca in enumerate(pending_dcas):
            if current_ts < dca.execute_at:
                continue

            # Check position still open
            pos = portfolio.get_position(dca.position_id)
            if pos is None or pos.status != "open":
                executed_indices.append(idx)
                continue

            # Risk check before DCA tranche
            risk_check = risk.can_open_position(dca.usdt_amount, prices)
            if not risk_check.allowed:
                executed_indices.append(idx)
                continue

            # Execute the tranche
            fill_price, fee, quantity = self._simulate_buy(
                current_price, dca.usdt_amount, cfg.fees
            )

            try:
                portfolio.add_tranche(dca.position_id, fill_price, dca.usdt_amount)
            except ValueError:
                executed_indices.append(idx)
                continue

            trades.append(TradeRecord(
                timestamp=current_ts,
                side="buy",
                price=fill_price,
                quantity=quantity,
                usdt_value=dca.usdt_amount,
                fee=fee,
                reason="dca",
                position_id=dca.position_id,
            ))

            # Schedule next tranche or mark as done
            if dca.tranches_remaining > 1:
                speed_factor = max(0.0, min(1.0, abs(dca.dip_speed)))
                interval_minutes = (
                    cfg.dca.min_interval_minutes
                    + (cfg.dca.max_interval_minutes - cfg.dca.min_interval_minutes)
                    * speed_factor
                )
                dca.execute_at = current_ts + timedelta(minutes=interval_minutes)
                dca.tranches_remaining -= 1
            else:
                executed_indices.append(idx)

        # Remove completed DCAs (reverse order to preserve indices)
        for idx in reversed(executed_indices):
            pending_dcas.pop(idx)

    @staticmethod
    def _simulate_buy(
        market_price: float, usdt_amount: float, fees: FeesConfig
    ) -> tuple[float, float, float]:
        """Simulate a buy fill with slippage and fees.

        Returns:
            (fill_price, fee_usdt, quantity)
        """
        fill_price = market_price * (1 + fees.estimated_slippage_pct / 100)
        fee = usdt_amount * fees.taker_pct / 100
        quantity = (usdt_amount - fee) / fill_price
        return fill_price, fee, quantity

    @staticmethod
    def _simulate_sell(
        market_price: float, quantity: float, fees: FeesConfig
    ) -> tuple[float, float, float]:
        """Simulate a sell fill with slippage and fees.

        Returns:
            (fill_price, fee_usdt, usdt_value_after_fee)
        """
        fill_price = market_price * (1 - fees.estimated_slippage_pct / 100)
        usdt_value = quantity * fill_price
        fee = usdt_value * fees.taker_pct / 100
        return fill_price, fee, usdt_value - fee

    @staticmethod
    def _summarize_position(
        pos, exit_price: float, pnl: float
    ) -> PositionSummary:
        """Create a PositionSummary from a closed position."""
        duration = (
            (pos.closed_at - pos.entry_time).total_seconds() / 3600
            if pos.closed_at
            else 0.0
        )
        cost = pos.total_cost
        pnl_pct = (pnl / cost * 100) if cost > 0 else 0.0

        return PositionSummary(
            position_id=pos.id,
            entry_time=pos.entry_time,
            exit_time=pos.closed_at or pos.entry_time,
            avg_entry_price=pos.avg_entry_price,
            exit_price=exit_price,
            quantity=pos.total_quantity,
            tranches=len(pos.tranches),
            pnl=pnl,
            pnl_pct=pnl_pct,
            duration_hours=duration,
        )
