"""Tests for paper trading simulator."""

import pytest

from bitbot.config import FeesConfig
from bitbot.paper_trading.simulator import PaperExecutor
from bitbot.trading.executor import Trade


@pytest.fixture
def executor() -> PaperExecutor:
    return PaperExecutor(fees_config=FeesConfig())


class TestPaperBuy:
    """Test simulated buy execution."""

    async def test_buy_returns_trade(self, executor: PaperExecutor) -> None:
        """Buy should return a Trade object."""
        trade = await executor.buy("BTCUSDT", usdt_amount=100.0, price=50000.0)

        assert isinstance(trade, Trade)
        assert trade.side == "buy"
        assert trade.symbol == "BTCUSDT"
        assert trade.mode == "paper"

    async def test_buy_applies_slippage(self, executor: PaperExecutor) -> None:
        """Buy price should be slightly above market (slippage)."""
        trade = await executor.buy("BTCUSDT", usdt_amount=100.0, price=50000.0)

        # 0.05% slippage → fill at $50025
        assert trade.price > 50000.0
        assert trade.price == pytest.approx(50025.0, rel=1e-6)

    async def test_buy_deducts_fee(self, executor: PaperExecutor) -> None:
        """Fee should be deducted from USDT amount."""
        trade = await executor.buy("BTCUSDT", usdt_amount=100.0, price=50000.0)

        # 0.1% fee on $100 = $0.10
        assert trade.fee == pytest.approx(0.10)

    async def test_buy_quantity_correct(self, executor: PaperExecutor) -> None:
        """Quantity should reflect net USDT after fee divided by fill price."""
        trade = await executor.buy("BTCUSDT", usdt_amount=100.0, price=50000.0)

        expected_qty = (100.0 - 0.10) / 50025.0
        assert trade.quantity == pytest.approx(expected_qty, rel=1e-6)


class TestPaperSell:
    """Test simulated sell execution."""

    async def test_sell_returns_trade(self, executor: PaperExecutor) -> None:
        """Sell should return a Trade object."""
        trade = await executor.sell("BTCUSDT", quantity=0.002, price=50000.0)

        assert isinstance(trade, Trade)
        assert trade.side == "sell"
        assert trade.mode == "paper"

    async def test_sell_applies_slippage(self, executor: PaperExecutor) -> None:
        """Sell price should be slightly below market (slippage)."""
        trade = await executor.sell("BTCUSDT", quantity=0.002, price=50000.0)

        assert trade.price < 50000.0
        assert trade.price == pytest.approx(49975.0, rel=1e-6)

    async def test_sell_deducts_fee(self, executor: PaperExecutor) -> None:
        """Fee should be calculated on sell value."""
        trade = await executor.sell("BTCUSDT", quantity=0.002, price=50000.0)

        # Value = 0.002 * 49975 = 99.95, fee = 99.95 * 0.001 = 0.09995
        assert trade.fee == pytest.approx(0.09995, rel=1e-3)

    async def test_sell_usdt_value(self, executor: PaperExecutor) -> None:
        """USDT value should be quantity * fill price."""
        trade = await executor.sell("BTCUSDT", quantity=0.002, price=50000.0)

        assert trade.usdt_value == pytest.approx(0.002 * 49975.0, rel=1e-6)


class TestTradeMetadata:
    """Test trade metadata fields."""

    async def test_trade_has_id(self, executor: PaperExecutor) -> None:
        """Each trade should have a unique ID."""
        t1 = await executor.buy("BTCUSDT", 100.0, 50000.0)
        t2 = await executor.buy("BTCUSDT", 100.0, 50000.0)

        assert t1.trade_id != t2.trade_id

    async def test_trade_has_timestamp(self, executor: PaperExecutor) -> None:
        """Trade should have a timestamp."""
        trade = await executor.buy("BTCUSDT", 100.0, 50000.0)
        assert trade.timestamp is not None

    async def test_trade_order_type(self, executor: PaperExecutor) -> None:
        """Paper trades should be market orders."""
        trade = await executor.buy("BTCUSDT", 100.0, 50000.0)
        assert trade.order_type == "market"
