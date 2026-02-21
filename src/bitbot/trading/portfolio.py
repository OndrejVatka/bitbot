"""Portfolio tracker — positions, tranches, and P&L calculations.

All monetary values are in USDT. Quantities are in the base asset (e.g., BTC).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from bitbot.backtesting.clock import Clock, WallClock
from bitbot.config import FeesConfig, SellingConfig

logger = logging.getLogger(__name__)


@dataclass
class Tranche:
    """A single DCA buy entry within a position."""

    price: float
    quantity: float
    fee: float
    timestamp: datetime


@dataclass
class Position:
    """A trading position composed of one or more DCA tranches."""

    id: str
    symbol: str
    tranches: list[Tranche] = field(default_factory=list)
    target_sell_price: float = 0.0
    stop_loss_price: float = 0.0
    status: str = "open"  # "open" or "closed"
    closed_at: datetime | None = None
    sell_price: float | None = None
    sell_fee: float = 0.0

    @property
    def entry_time(self) -> datetime:
        """Timestamp of the first tranche."""
        return self.tranches[0].timestamp

    @property
    def total_quantity(self) -> float:
        """Total quantity across all tranches."""
        return sum(t.quantity for t in self.tranches)

    @property
    def total_cost(self) -> float:
        """Total USDT spent (price * quantity) across all tranches, excluding fees."""
        return sum(t.price * t.quantity for t in self.tranches)

    @property
    def total_fees(self) -> float:
        """Total fees paid (buy fees + sell fee)."""
        return sum(t.fee for t in self.tranches) + self.sell_fee

    @property
    def avg_entry_price(self) -> float:
        """Weighted average entry price across all tranches."""
        qty = self.total_quantity
        if qty == 0:
            return 0.0
        return self.total_cost / qty

    def unrealized_pnl(self, current_price: float) -> float:
        """Calculate unrealized P&L at a given market price (after fees)."""
        if self.status == "closed":
            return 0.0
        market_value = self.total_quantity * current_price
        return market_value - self.total_cost - sum(t.fee for t in self.tranches)

    @property
    def realized_pnl(self) -> float:
        """Calculate realized P&L for closed positions."""
        if self.status != "closed" or self.sell_price is None:
            return 0.0
        sell_value = self.total_quantity * self.sell_price
        return sell_value - self.total_cost - self.total_fees


class Portfolio:
    """Tracks all positions and capital for a trading account.

    Maintains an in-memory view of positions and balances.
    Callers are responsible for persisting trades via Repository.
    """

    def __init__(
        self,
        initial_capital: float,
        fees_config: FeesConfig,
        selling_config: SellingConfig,
        clock: Clock | None = None,
    ) -> None:
        self._initial_capital = initial_capital
        self._cash = initial_capital
        self._fees = fees_config
        self._selling = selling_config
        self._clock: Clock = clock or WallClock()
        self._positions: dict[str, Position] = {}
        self._closed_positions: list[Position] = []

    @property
    def cash(self) -> float:
        """Available USDT cash (not locked in positions)."""
        return self._cash

    def open_position(
        self,
        symbol: str,
        price: float,
        usdt_amount: float,
    ) -> Position:
        """Open a new position with an initial buy.

        Args:
            symbol: Trading pair (e.g., 'BTCUSDT').
            price: Execution price (after slippage).
            usdt_amount: USDT to spend on this buy.

        Returns:
            The new Position.

        Raises:
            ValueError: If insufficient cash.
        """
        if usdt_amount > self._cash:
            raise ValueError(
                f"Insufficient cash: need {usdt_amount:.2f}, have {self._cash:.2f}"
            )

        fee = usdt_amount * self._fees.taker_pct / 100
        net_usdt = usdt_amount - fee
        quantity = net_usdt / price

        position_id = str(uuid.uuid4())
        tranche = Tranche(
            price=price,
            quantity=quantity,
            fee=fee,
            timestamp=self._clock.now(),
        )

        # Calculate targets based on avg entry
        target_sell = price * (1 + self._selling.profit_target_pct / 100)
        stop_loss = price * (1 - 5.0 / 100)  # 5% stop-loss (from risk config)

        position = Position(
            id=position_id,
            symbol=symbol,
            tranches=[tranche],
            target_sell_price=target_sell,
            stop_loss_price=stop_loss,
        )

        self._positions[position_id] = position
        self._cash -= usdt_amount

        logger.info(
            "Opened position %s: %.6f %s @ $%.2f ($%.2f USDT, fee=$%.2f)",
            position_id[:8],
            quantity,
            symbol,
            price,
            usdt_amount,
            fee,
        )

        return position

    def add_tranche(
        self,
        position_id: str,
        price: float,
        usdt_amount: float,
    ) -> Tranche:
        """Add a DCA tranche to an existing position.

        Args:
            position_id: ID of the existing position.
            price: Execution price.
            usdt_amount: USDT to spend on this tranche.

        Returns:
            The new Tranche.

        Raises:
            ValueError: If position not found or insufficient cash.
        """
        position = self._positions.get(position_id)
        if position is None:
            raise ValueError(f"Position {position_id} not found")
        if usdt_amount > self._cash:
            raise ValueError(
                f"Insufficient cash: need {usdt_amount:.2f}, have {self._cash:.2f}"
            )

        fee = usdt_amount * self._fees.taker_pct / 100
        net_usdt = usdt_amount - fee
        quantity = net_usdt / price

        tranche = Tranche(
            price=price,
            quantity=quantity,
            fee=fee,
            timestamp=self._clock.now(),
        )

        position.tranches.append(tranche)
        self._cash -= usdt_amount

        # Recalculate targets based on new avg entry
        avg = position.avg_entry_price
        position.target_sell_price = avg * (1 + self._selling.profit_target_pct / 100)
        position.stop_loss_price = avg * (1 - 5.0 / 100)

        logger.info(
            "Added tranche to %s: %.6f @ $%.2f (avg entry now $%.2f)",
            position_id[:8],
            quantity,
            price,
            avg,
        )

        return tranche

    def close_position(
        self,
        position_id: str,
        sell_price: float,
    ) -> float:
        """Close a position by selling all quantity.

        Args:
            position_id: ID of the position to close.
            sell_price: Execution price for the sell.

        Returns:
            Realized P&L (USDT, after all fees).

        Raises:
            ValueError: If position not found.
        """
        position = self._positions.get(position_id)
        if position is None:
            raise ValueError(f"Position {position_id} not found")

        sell_value = position.total_quantity * sell_price
        sell_fee = sell_value * self._fees.taker_pct / 100

        position.sell_price = sell_price
        position.sell_fee = sell_fee
        position.status = "closed"
        position.closed_at = self._clock.now()

        # Return cash from sale (minus fee)
        self._cash += sell_value - sell_fee

        # Move to closed positions
        del self._positions[position_id]
        self._closed_positions.append(position)

        pnl = position.realized_pnl
        logger.info(
            "Closed position %s: sold %.6f @ $%.2f, P&L=$%.2f",
            position_id[:8],
            position.total_quantity,
            sell_price,
            pnl,
        )

        return pnl

    def get_open_positions(self) -> list[Position]:
        """Return all open positions."""
        return list(self._positions.values())

    def get_position(self, position_id: str) -> Position | None:
        """Get a specific position by ID."""
        return self._positions.get(position_id)

    def get_available_capital(self) -> float:
        """Return available USDT cash."""
        return self._cash

    def get_total_value(self, current_prices: dict[str, float]) -> float:
        """Calculate total portfolio value (cash + open positions at market).

        Args:
            current_prices: Dict of symbol → current price.
        """
        positions_value = sum(
            pos.total_quantity * current_prices.get(pos.symbol, 0.0)
            for pos in self._positions.values()
        )
        return self._cash + positions_value

    def get_total_exposure(self, current_prices: dict[str, float]) -> float:
        """Calculate total capital locked in open positions (at market value)."""
        return sum(
            pos.total_quantity * current_prices.get(pos.symbol, 0.0)
            for pos in self._positions.values()
        )

    def get_realized_pnl(self) -> float:
        """Sum of realized P&L from all closed positions."""
        return sum(pos.realized_pnl for pos in self._closed_positions)

    def get_unrealized_pnl(self, current_prices: dict[str, float]) -> float:
        """Sum of unrealized P&L from all open positions."""
        return sum(
            pos.unrealized_pnl(current_prices.get(pos.symbol, 0.0))
            for pos in self._positions.values()
        )
