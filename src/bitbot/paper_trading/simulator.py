"""Paper trading simulator — fake order execution with realistic modeling.

Simulates slippage, fees, and instant fills using real market prices.
Implements the same Executor interface as the future live executor.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from bitbot.config import FeesConfig
from bitbot.database.repository import Repository
from bitbot.trading.executor import Executor, Trade

logger = logging.getLogger(__name__)


class PaperExecutor(Executor):
    """Simulated order executor for paper trading.

    Models:
    - Slippage: buys fill slightly above market, sells slightly below
    - Fees: maker/taker fees deducted from trade value
    - Instant fills: no partial fills or order book simulation
    """

    def __init__(
        self,
        fees_config: FeesConfig,
        repo: Repository | None = None,
    ) -> None:
        self._fees = fees_config
        self._repo = repo

    async def buy(
        self,
        symbol: str,
        usdt_amount: float,
        price: float,
    ) -> Trade:
        """Execute a simulated buy order.

        Buy fills at price + slippage (slightly worse price for buyer).
        """
        slippage_pct = self._fees.estimated_slippage_pct / 100
        fill_price = price * (1 + slippage_pct)

        fee = usdt_amount * self._fees.taker_pct / 100
        net_usdt = usdt_amount - fee
        quantity = net_usdt / fill_price

        trade = Trade(
            trade_id=str(uuid.uuid4()),
            symbol=symbol,
            side="buy",
            price=fill_price,
            quantity=quantity,
            fee=fee,
            usdt_value=usdt_amount,
            timestamp=datetime.now(timezone.utc),
            order_type="market",
            mode="paper",
        )

        logger.info(
            "[PAPER BUY] %s: %.6f @ $%.2f ($%.2f, fee=$%.4f, slippage=%.3f%%)",
            symbol,
            quantity,
            fill_price,
            usdt_amount,
            fee,
            slippage_pct * 100,
        )

        if self._repo:
            await self._repo.log_trade(
                symbol=symbol,
                side="buy",
                price=fill_price,
                quantity=quantity,
                fee=fee,
                position_id="",
                mode="paper",
                order_type="market",
            )

        return trade

    async def sell(
        self,
        symbol: str,
        quantity: float,
        price: float,
    ) -> Trade:
        """Execute a simulated sell order.

        Sell fills at price - slippage (slightly worse price for seller).
        """
        slippage_pct = self._fees.estimated_slippage_pct / 100
        fill_price = price * (1 - slippage_pct)

        usdt_value = quantity * fill_price
        fee = usdt_value * self._fees.taker_pct / 100

        trade = Trade(
            trade_id=str(uuid.uuid4()),
            symbol=symbol,
            side="sell",
            price=fill_price,
            quantity=quantity,
            fee=fee,
            usdt_value=usdt_value,
            timestamp=datetime.now(timezone.utc),
            order_type="market",
            mode="paper",
        )

        logger.info(
            "[PAPER SELL] %s: %.6f @ $%.2f ($%.2f, fee=$%.4f)",
            symbol,
            quantity,
            fill_price,
            usdt_value,
            fee,
        )

        if self._repo:
            await self._repo.log_trade(
                symbol=symbol,
                side="sell",
                price=fill_price,
                quantity=quantity,
                fee=fee,
                position_id="",
                mode="paper",
                order_type="market",
            )

        return trade
