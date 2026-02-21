"""Risk management — the most critical module.

Enforces position limits, stop-losses, drawdown halts, and cooldowns.
Every trade must pass through the risk manager before execution.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass

from bitbot.backtesting.clock import Clock, WallClock
from bitbot.config import RiskConfig
from bitbot.trading.portfolio import Portfolio, Position

logger = logging.getLogger(__name__)


@dataclass
class RiskCheck:
    """Result of a risk check."""

    allowed: bool
    reason: str


class RiskManager:
    """Enforces all trading risk rules.

    Rules:
    - Max position size (% of total capital)
    - Max total exposure (% of total capital in open positions)
    - Stop-loss per position
    - Max daily loss → halt trading for 24h
    - Max drawdown from peak → halt trading
    - Cooldown after stop-loss
    - Sentiment block after "fundamental_shift"
    """

    def __init__(
        self,
        config: RiskConfig,
        portfolio: Portfolio,
        initial_capital: float,
        clock: Clock | None = None,
    ) -> None:
        self._config = config
        self._portfolio = portfolio
        self._initial_capital = initial_capital
        self._clock: Clock = clock or WallClock()

        # Tracking state
        self._peak_value = initial_capital
        self._daily_start_value = initial_capital
        self._daily_start_time = self._clock.now()
        self._last_stoploss_time: datetime | None = None
        self._sentiment_block_until: datetime | None = None
        self._halted = False
        self._halt_reason = ""

    def can_open_position(
        self,
        size_usdt: float,
        current_prices: dict[str, float],
    ) -> RiskCheck:
        """Check if a new position of the given size is allowed.

        Args:
            size_usdt: Proposed position size in USDT.
            current_prices: Current market prices for exposure calculation.

        Returns:
            RiskCheck with allowed=True or allowed=False with reason.
        """
        # Check halt status first
        if self._halted:
            return RiskCheck(False, f"Trading halted: {self._halt_reason}")

        # Check sentiment block
        if self._sentiment_block_until:
            now = self._clock.now()
            if now < self._sentiment_block_until:
                remaining = (self._sentiment_block_until - now).total_seconds() / 3600
                return RiskCheck(
                    False,
                    f"Sentiment block active ({remaining:.1f}h remaining)",
                )
            else:
                self._sentiment_block_until = None

        # Check cooldown after stop-loss
        if self._last_stoploss_time:
            cooldown_end = self._last_stoploss_time + timedelta(
                hours=self._config.cooldown_after_stoploss_hours
            )
            now = self._clock.now()
            if now < cooldown_end:
                remaining = (cooldown_end - now).total_seconds() / 3600
                return RiskCheck(
                    False,
                    f"Stop-loss cooldown ({remaining:.1f}h remaining)",
                )

        # Check max position size
        total_value = self._portfolio.get_total_value(current_prices)
        max_position = total_value * self._config.max_position_pct
        if size_usdt > max_position:
            return RiskCheck(
                False,
                f"Position size ${size_usdt:.2f} exceeds max "
                f"${max_position:.2f} ({self._config.max_position_pct:.0%} of portfolio)",
            )

        # Check total exposure
        current_exposure = self._portfolio.get_total_exposure(current_prices)
        max_exposure = total_value * self._config.max_total_exposure_pct
        if current_exposure + size_usdt > max_exposure:
            return RiskCheck(
                False,
                f"Total exposure ${current_exposure + size_usdt:.2f} would exceed max "
                f"${max_exposure:.2f} ({self._config.max_total_exposure_pct:.0%} of portfolio)",
            )

        # Check minimum cash reserve
        if size_usdt > self._portfolio.cash:
            return RiskCheck(
                False,
                f"Insufficient cash: ${self._portfolio.cash:.2f} available",
            )

        return RiskCheck(True, "All risk checks passed")

    def check_stop_losses(
        self,
        current_prices: dict[str, float],
    ) -> list[str]:
        """Check all open positions for stop-loss triggers.

        Args:
            current_prices: Current market prices.

        Returns:
            List of position IDs that should be closed (stop-loss triggered).
        """
        triggered: list[str] = []

        for position in self._portfolio.get_open_positions():
            price = current_prices.get(position.symbol, 0.0)
            if price <= 0:
                continue

            if price <= position.stop_loss_price:
                loss_pct = (
                    (position.avg_entry_price - price) / position.avg_entry_price * 100
                )
                logger.warning(
                    "STOP-LOSS triggered for %s: price $%.2f <= stop $%.2f (%.1f%% loss)",
                    position.id[:8],
                    price,
                    position.stop_loss_price,
                    loss_pct,
                )
                triggered.append(position.id)

        return triggered

    def check_profit_targets(
        self,
        current_prices: dict[str, float],
    ) -> list[str]:
        """Check all open positions for profit target hits.

        Args:
            current_prices: Current market prices.

        Returns:
            List of position IDs that have hit their profit target.
        """
        triggered: list[str] = []

        for position in self._portfolio.get_open_positions():
            price = current_prices.get(position.symbol, 0.0)
            if price <= 0:
                continue

            if price >= position.target_sell_price:
                gain_pct = (
                    (price - position.avg_entry_price) / position.avg_entry_price * 100
                )
                logger.info(
                    "PROFIT TARGET hit for %s: price $%.2f >= target $%.2f (%.1f%% gain)",
                    position.id[:8],
                    price,
                    position.target_sell_price,
                    gain_pct,
                )
                triggered.append(position.id)

        return triggered

    def update_tracking(self, current_prices: dict[str, float]) -> None:
        """Update peak value and check for daily loss / max drawdown halts.

        Call this periodically (e.g., every candle close).
        """
        total_value = self._portfolio.get_total_value(current_prices)

        # Update peak
        if total_value > self._peak_value:
            self._peak_value = total_value

        # Reset daily tracking at midnight UTC
        now = self._clock.now()
        if now.date() > self._daily_start_time.date():
            self._daily_start_value = total_value
            self._daily_start_time = now
            # Lift halt if it was a daily loss halt
            if self._halted and "daily loss" in self._halt_reason:
                self._halted = False
                self._halt_reason = ""
                logger.info("Daily loss halt lifted (new trading day)")

        # Check daily loss
        daily_loss_pct = (
            (self._daily_start_value - total_value) / self._daily_start_value * 100
        )
        if daily_loss_pct >= self._config.max_daily_loss_pct and not self._halted:
            self._halted = True
            self._halt_reason = (
                f"Daily loss {daily_loss_pct:.1f}% exceeds "
                f"max {self._config.max_daily_loss_pct}%"
            )
            logger.critical("TRADING HALTED: %s", self._halt_reason)

        # Check max drawdown from peak
        drawdown_pct = (self._peak_value - total_value) / self._peak_value * 100
        if drawdown_pct >= self._config.max_drawdown_pct and not self._halted:
            self._halted = True
            self._halt_reason = (
                f"Max drawdown {drawdown_pct:.1f}% exceeds "
                f"max {self._config.max_drawdown_pct}%"
            )
            logger.critical("TRADING HALTED: %s", self._halt_reason)

    def record_stop_loss(self) -> None:
        """Record that a stop-loss was triggered, starting the cooldown."""
        self._last_stoploss_time = self._clock.now()
        logger.info(
            "Stop-loss cooldown started (%dh)",
            self._config.cooldown_after_stoploss_hours,
        )

    def record_sentiment_block(self) -> None:
        """Block all buys due to LLM 'fundamental_shift' classification."""
        self._sentiment_block_until = self._clock.now() + timedelta(
            hours=self._config.sentiment_block_hours
        )
        logger.warning(
            "Sentiment block activated for %dh",
            self._config.sentiment_block_hours,
        )

    def is_trading_halted(self) -> RiskCheck:
        """Check if trading is currently halted."""
        if self._halted:
            return RiskCheck(False, self._halt_reason)
        return RiskCheck(True, "Trading active")
