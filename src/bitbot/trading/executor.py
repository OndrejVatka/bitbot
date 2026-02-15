"""Abstract executor interface for order execution.

Both PaperExecutor and future LiveExecutor implement this interface,
so the main loop doesn't need to know which one it's using.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime


@dataclass
class Trade:
    """Result of an executed trade."""

    trade_id: str
    symbol: str
    side: str             # "buy" or "sell"
    price: float          # Actual execution price (after slippage)
    quantity: float       # Quantity of base asset
    fee: float            # Fee in USDT
    usdt_value: float     # Total USDT value of the trade
    timestamp: datetime
    order_type: str       # "market" or "limit"
    mode: str             # "paper" or "live"


class Executor(ABC):
    """Abstract base class for order execution."""

    @abstractmethod
    async def buy(
        self,
        symbol: str,
        usdt_amount: float,
        price: float,
    ) -> Trade:
        """Execute a buy order.

        Args:
            symbol: Trading pair (e.g., 'BTCUSDT').
            usdt_amount: Amount of USDT to spend.
            price: Current market price (executor may add slippage).

        Returns:
            Trade result with actual execution details.
        """
        ...

    @abstractmethod
    async def sell(
        self,
        symbol: str,
        quantity: float,
        price: float,
    ) -> Trade:
        """Execute a sell order.

        Args:
            symbol: Trading pair.
            quantity: Quantity of base asset to sell.
            price: Current market price (executor may add slippage).

        Returns:
            Trade result with actual execution details.
        """
        ...
