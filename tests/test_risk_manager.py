"""Tests for risk manager."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from bitbot.config import FeesConfig, RiskConfig, SellingConfig
from bitbot.trading.portfolio import Portfolio
from bitbot.trading.risk_manager import RiskManager


@pytest.fixture
def portfolio() -> Portfolio:
    return Portfolio(
        initial_capital=1000.0,
        fees_config=FeesConfig(),
        selling_config=SellingConfig(),
    )


@pytest.fixture
def risk(portfolio: Portfolio) -> RiskManager:
    return RiskManager(
        config=RiskConfig(),
        portfolio=portfolio,
        initial_capital=1000.0,
    )


PRICES = {"BTCUSDT": 50000.0}


class TestPositionLimits:
    """Test max position size and exposure limits."""

    def test_small_position_allowed(self, risk: RiskManager) -> None:
        """A small position should be allowed."""
        check = risk.can_open_position(50.0, PRICES)
        assert check.allowed

    def test_max_position_size_enforced(self, risk: RiskManager) -> None:
        """Position exceeding 20% of portfolio should be rejected."""
        check = risk.can_open_position(250.0, PRICES)  # 25% of $1000
        assert not check.allowed
        assert "exceeds max" in check.reason

    def test_max_exposure_enforced(
        self, risk: RiskManager, portfolio: Portfolio
    ) -> None:
        """Total exposure exceeding 70% should be rejected."""
        # Open 4 positions of $150 each = $600 exposure (60%)
        for _ in range(4):
            portfolio.open_position("BTCUSDT", price=50000.0, usdt_amount=150.0)

        # Another $150 would push exposure to ~75% (> 70% limit)
        check = risk.can_open_position(150.0, PRICES)
        assert not check.allowed
        assert "exposure" in check.reason.lower()

    def test_insufficient_cash(
        self, risk: RiskManager, portfolio: Portfolio
    ) -> None:
        """Should reject if not enough cash even if within limits."""
        portfolio.open_position("BTCUSDT", price=50000.0, usdt_amount=200.0)
        portfolio.open_position("BTCUSDT", price=50000.0, usdt_amount=200.0)
        portfolio.open_position("BTCUSDT", price=50000.0, usdt_amount=200.0)
        portfolio.open_position("BTCUSDT", price=50000.0, usdt_amount=200.0)
        # Cash is now ~$200

        check = risk.can_open_position(150.0, PRICES)
        # Might fail on exposure or cash — either way should be blocked
        # (exposure is already at ~80%, so it'll fail on that first)
        assert not check.allowed


class TestStopLoss:
    """Test stop-loss detection."""

    def test_stop_loss_triggered(
        self, risk: RiskManager, portfolio: Portfolio
    ) -> None:
        """Position below stop-loss price should be flagged."""
        pos = portfolio.open_position("BTCUSDT", price=50000.0, usdt_amount=100.0)
        # stop_loss_price = 50000 * 0.95 = 47500

        # Price dropped below stop-loss
        triggered = risk.check_stop_losses({"BTCUSDT": 47000.0})
        assert pos.id in triggered

    def test_stop_loss_not_triggered(
        self, risk: RiskManager, portfolio: Portfolio
    ) -> None:
        """Position above stop-loss should not be flagged."""
        pos = portfolio.open_position("BTCUSDT", price=50000.0, usdt_amount=100.0)

        triggered = risk.check_stop_losses({"BTCUSDT": 49000.0})
        assert pos.id not in triggered


class TestProfitTarget:
    """Test profit target detection."""

    def test_profit_target_hit(
        self, risk: RiskManager, portfolio: Portfolio
    ) -> None:
        """Position above target should be flagged."""
        pos = portfolio.open_position("BTCUSDT", price=50000.0, usdt_amount=100.0)
        # target_sell_price = 50000 * 1.05 = 52500

        triggered = risk.check_profit_targets({"BTCUSDT": 53000.0})
        assert pos.id in triggered

    def test_profit_target_not_hit(
        self, risk: RiskManager, portfolio: Portfolio
    ) -> None:
        """Position below target should not be flagged."""
        pos = portfolio.open_position("BTCUSDT", price=50000.0, usdt_amount=100.0)

        triggered = risk.check_profit_targets({"BTCUSDT": 51000.0})
        assert pos.id not in triggered


class TestCooldown:
    """Test stop-loss cooldown."""

    def test_cooldown_blocks_new_positions(self, risk: RiskManager) -> None:
        """After a stop-loss, new positions should be blocked for cooldown period."""
        risk.record_stop_loss()

        check = risk.can_open_position(50.0, PRICES)
        assert not check.allowed
        assert "cooldown" in check.reason.lower()

    def test_cooldown_expires(self, risk: RiskManager) -> None:
        """After cooldown period, trading should resume."""
        # Set stop-loss time to 5 hours ago (cooldown is 4h)
        risk._last_stoploss_time = datetime.now(timezone.utc) - timedelta(hours=5)

        check = risk.can_open_position(50.0, PRICES)
        assert check.allowed


class TestSentimentBlock:
    """Test sentiment-based trading block."""

    def test_sentiment_block_active(self, risk: RiskManager) -> None:
        """Sentiment block should prevent new positions."""
        risk.record_sentiment_block()

        check = risk.can_open_position(50.0, PRICES)
        assert not check.allowed
        assert "sentiment" in check.reason.lower()

    def test_sentiment_block_expires(self, risk: RiskManager) -> None:
        """Sentiment block should expire after configured hours."""
        risk._sentiment_block_until = datetime.now(timezone.utc) - timedelta(hours=1)

        check = risk.can_open_position(50.0, PRICES)
        assert check.allowed


class TestDrawdownHalt:
    """Test drawdown and daily loss halts."""

    def test_daily_loss_halt(
        self, risk: RiskManager, portfolio: Portfolio
    ) -> None:
        """Portfolio dropping 3%+ in a day should halt trading."""
        # Simulate a loss: open and close at a loss
        pos = portfolio.open_position("BTCUSDT", price=50000.0, usdt_amount=200.0)
        portfolio.close_position(pos.id, sell_price=42000.0)

        # Update tracking with depressed portfolio value
        risk.update_tracking(PRICES)

        halt = risk.is_trading_halted()
        assert not halt.allowed

    def test_max_drawdown_halt(
        self, risk: RiskManager, portfolio: Portfolio
    ) -> None:
        """Portfolio dropping 10%+ from peak should halt trading."""
        # Set a higher peak
        risk._peak_value = 1200.0

        # Current value is ~$1000 (after no trades), that's ~16.7% drawdown
        risk.update_tracking(PRICES)

        halt = risk.is_trading_halted()
        assert not halt.allowed
        assert "drawdown" in halt.reason.lower()
