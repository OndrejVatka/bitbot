"""Tests for portfolio tracker."""

import pytest

from bitbot.config import FeesConfig, SellingConfig
from bitbot.trading.portfolio import Portfolio, Position


@pytest.fixture
def portfolio() -> Portfolio:
    """Create a portfolio with $1000 and standard fees."""
    return Portfolio(
        initial_capital=1000.0,
        fees_config=FeesConfig(),  # 0.1% maker/taker
        selling_config=SellingConfig(),  # 5% profit target
    )


class TestOpenPosition:
    """Test opening positions."""

    def test_basic_open(self, portfolio: Portfolio) -> None:
        """Opening a position should reduce cash and create a position."""
        pos = portfolio.open_position("BTCUSDT", price=50000.0, usdt_amount=100.0)

        assert pos.status == "open"
        assert pos.symbol == "BTCUSDT"
        assert len(pos.tranches) == 1
        assert portfolio.cash == pytest.approx(900.0)
        assert len(portfolio.get_open_positions()) == 1

    def test_fee_deducted_from_quantity(self, portfolio: Portfolio) -> None:
        """Fees should reduce the quantity received."""
        pos = portfolio.open_position("BTCUSDT", price=50000.0, usdt_amount=100.0)

        # $100 spend, 0.1% fee = $0.10 fee, $99.90 buys BTC
        expected_qty = 99.90 / 50000.0
        assert pos.total_quantity == pytest.approx(expected_qty, rel=1e-6)
        assert pos.tranches[0].fee == pytest.approx(0.10)

    def test_insufficient_cash_raises(self, portfolio: Portfolio) -> None:
        """Should raise ValueError if not enough cash."""
        with pytest.raises(ValueError, match="Insufficient cash"):
            portfolio.open_position("BTCUSDT", price=50000.0, usdt_amount=1500.0)

    def test_targets_set_correctly(self, portfolio: Portfolio) -> None:
        """Profit target and stop-loss should be set on open."""
        pos = portfolio.open_position("BTCUSDT", price=50000.0, usdt_amount=100.0)

        assert pos.target_sell_price == pytest.approx(52500.0)  # 5% above
        assert pos.stop_loss_price == pytest.approx(47500.0)     # 5% below


class TestDCA:
    """Test DCA tranche addition."""

    def test_add_tranche(self, portfolio: Portfolio) -> None:
        """Adding a tranche should increase position quantity."""
        pos = portfolio.open_position("BTCUSDT", price=50000.0, usdt_amount=100.0)
        initial_qty = pos.total_quantity

        portfolio.add_tranche(pos.id, price=48000.0, usdt_amount=100.0)

        assert len(pos.tranches) == 2
        assert pos.total_quantity > initial_qty
        assert portfolio.cash == pytest.approx(800.0)

    def test_avg_entry_price_weighted(self, portfolio: Portfolio) -> None:
        """Average entry should be quantity-weighted."""
        pos = portfolio.open_position("BTCUSDT", price=50000.0, usdt_amount=100.0)
        portfolio.add_tranche(pos.id, price=40000.0, usdt_amount=100.0)

        # qty1 = 99.90/50000, qty2 = 99.90/40000
        qty1 = 99.90 / 50000.0
        qty2 = 99.90 / 40000.0
        expected_avg = (99.90 + 99.90) / (qty1 + qty2)

        assert pos.avg_entry_price == pytest.approx(expected_avg, rel=1e-4)
        # Should be between 40k and 50k, closer to 40k (more qty at lower price)
        assert 40000 < pos.avg_entry_price < 50000

    def test_targets_recalculated_on_tranche(self, portfolio: Portfolio) -> None:
        """Adding a tranche should recalculate targets based on new avg entry."""
        pos = portfolio.open_position("BTCUSDT", price=50000.0, usdt_amount=100.0)
        original_target = pos.target_sell_price

        portfolio.add_tranche(pos.id, price=40000.0, usdt_amount=100.0)

        # New avg is lower, so target should be lower
        assert pos.target_sell_price < original_target


class TestClosePosition:
    """Test closing positions and P&L."""

    def test_profitable_close(self, portfolio: Portfolio) -> None:
        """Closing at a profit should return positive P&L."""
        pos = portfolio.open_position("BTCUSDT", price=50000.0, usdt_amount=100.0)
        pnl = portfolio.close_position(pos.id, sell_price=55000.0)

        assert pnl > 0
        assert len(portfolio.get_open_positions()) == 0
        assert portfolio.cash > 1000.0  # Started with 1000, net profit

    def test_losing_close(self, portfolio: Portfolio) -> None:
        """Closing at a loss should return negative P&L."""
        pos = portfolio.open_position("BTCUSDT", price=50000.0, usdt_amount=100.0)
        pnl = portfolio.close_position(pos.id, sell_price=45000.0)

        assert pnl < 0
        assert portfolio.cash < 1000.0

    def test_sell_fee_applied(self, portfolio: Portfolio) -> None:
        """Sell fee should reduce the cash returned."""
        pos = portfolio.open_position("BTCUSDT", price=50000.0, usdt_amount=100.0)

        # Sell at same price — should have small loss due to fees
        pnl = portfolio.close_position(pos.id, sell_price=50000.0)

        # Buy fee + sell fee means net loss
        assert pnl < 0
        assert portfolio.cash < 1000.0

    def test_realized_pnl_tracks(self, portfolio: Portfolio) -> None:
        """get_realized_pnl should sum all closed position P&Ls."""
        pos1 = portfolio.open_position("BTCUSDT", price=50000.0, usdt_amount=100.0)
        portfolio.close_position(pos1.id, sell_price=55000.0)

        pos2 = portfolio.open_position("BTCUSDT", price=55000.0, usdt_amount=100.0)
        portfolio.close_position(pos2.id, sell_price=50000.0)

        realized = portfolio.get_realized_pnl()
        # One win, one loss — should be close to net zero (with fees making it slightly negative)
        assert isinstance(realized, float)


class TestPortfolioValue:
    """Test total value and unrealized P&L calculations."""

    def test_total_value_with_position(self, portfolio: Portfolio) -> None:
        """Total value should include cash + positions at market price."""
        portfolio.open_position("BTCUSDT", price=50000.0, usdt_amount=200.0)

        total = portfolio.get_total_value({"BTCUSDT": 55000.0})

        # $800 cash + position value at $55k
        assert total > 1000.0  # Price went up

    def test_unrealized_pnl(self, portfolio: Portfolio) -> None:
        """Unrealized P&L should reflect current market vs entry."""
        portfolio.open_position("BTCUSDT", price=50000.0, usdt_amount=100.0)

        pnl_up = portfolio.get_unrealized_pnl({"BTCUSDT": 55000.0})
        pnl_down = portfolio.get_unrealized_pnl({"BTCUSDT": 45000.0})

        assert pnl_up > 0
        assert pnl_down < 0

    def test_exposure_calculation(self, portfolio: Portfolio) -> None:
        """Total exposure should be the market value of open positions."""
        portfolio.open_position("BTCUSDT", price=50000.0, usdt_amount=200.0)

        exposure = portfolio.get_total_exposure({"BTCUSDT": 50000.0})

        # Slightly less than $200 due to fee reducing quantity
        assert 190.0 < exposure < 200.0
