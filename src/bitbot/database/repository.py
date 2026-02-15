"""Typed database access layer for all BitBot persistence."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass

import aiosqlite


@dataclass
class Candle:
    """Single OHLCV candle."""

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    is_closed: bool = True


class Repository:
    """Async database access layer with typed methods for all BitBot tables."""

    def __init__(self, db: aiosqlite.Connection) -> None:
        self._db = db

    # --- Signals ---

    async def log_signal(
        self,
        symbol: str,
        confidence_score: int,
        action_taken: str,
        technical_signals: dict,
        price_at_signal: float,
        sentiment_result: dict | None = None,
    ) -> str:
        """Log a scoring decision. Returns the signal ID."""
        signal_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        await self._db.execute(
            """
            INSERT INTO signals (id, symbol, timestamp, confidence_score,
                                 action_taken, technical_signals, sentiment_result,
                                 price_at_signal)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                signal_id,
                symbol,
                now,
                confidence_score,
                action_taken,
                json.dumps(technical_signals),
                json.dumps(sentiment_result) if sentiment_result else None,
                price_at_signal,
            ),
        )
        await self._db.commit()
        return signal_id

    async def get_recent_signals(
        self, symbol: str, limit: int = 50
    ) -> list[dict]:
        """Fetch recent signal logs, newest first."""
        cursor = await self._db.execute(
            """
            SELECT * FROM signals
            WHERE symbol = ?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (symbol, limit),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    # --- Trades ---

    async def log_trade(
        self,
        symbol: str,
        side: str,
        price: float,
        quantity: float,
        fee: float,
        position_id: str,
        mode: str,
        order_type: str,
    ) -> str:
        """Log a trade execution. Returns the trade ID."""
        trade_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        await self._db.execute(
            """
            INSERT INTO trades (id, symbol, timestamp, side, price, quantity,
                                fee, position_id, mode, order_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                trade_id,
                symbol,
                now,
                side,
                price,
                quantity,
                fee,
                position_id,
                mode,
                order_type,
            ),
        )
        await self._db.commit()
        return trade_id

    # --- Candle Cache ---

    async def save_candles(
        self, symbol: str, timeframe: str, candles: list[Candle]
    ) -> None:
        """Upsert candles into the cache table."""
        await self._db.executemany(
            """
            INSERT OR REPLACE INTO candles
                (symbol, timeframe, timestamp, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    symbol,
                    timeframe,
                    c.timestamp.isoformat(),
                    c.open,
                    c.high,
                    c.low,
                    c.close,
                    c.volume,
                )
                for c in candles
            ],
        )
        await self._db.commit()

    async def load_cached_candles(
        self, symbol: str, timeframe: str, limit: int = 200
    ) -> list[Candle]:
        """Load cached candles, oldest first (for indicator warm-up)."""
        cursor = await self._db.execute(
            """
            SELECT timestamp, open, high, low, close, volume
            FROM candles
            WHERE symbol = ? AND timeframe = ?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (symbol, timeframe, limit),
        )
        rows = await cursor.fetchall()

        # Reverse so oldest is first (chronological order)
        return [
            Candle(
                timestamp=datetime.fromisoformat(row[0]),
                open=row[1],
                high=row[2],
                low=row[3],
                close=row[4],
                volume=row[5],
            )
            for row in reversed(rows)
        ]

    # --- Risk Events ---

    async def log_risk_event(
        self, symbol: str, event_type: str, details: dict
    ) -> str:
        """Log a risk management event. Returns the event ID."""
        event_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        await self._db.execute(
            """
            INSERT INTO risk_events (id, symbol, timestamp, event_type, details)
            VALUES (?, ?, ?, ?, ?)
            """,
            (event_id, symbol, now, event_type, json.dumps(details)),
        )
        await self._db.commit()
        return event_id

    # --- Portfolio Snapshots ---

    async def save_snapshot(
        self,
        symbol: str,
        total_value: float,
        available_capital: float,
        open_positions_count: int,
        unrealized_pnl: float,
        realized_pnl_cumulative: float,
    ) -> None:
        """Save a portfolio snapshot."""
        now = datetime.now(timezone.utc).isoformat()

        await self._db.execute(
            """
            INSERT INTO portfolio_snapshots
                (symbol, timestamp, total_value, available_capital,
                 open_positions_count, unrealized_pnl, realized_pnl_cumulative)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                symbol,
                now,
                total_value,
                available_capital,
                open_positions_count,
                unrealized_pnl,
                realized_pnl_cumulative,
            ),
        )
        await self._db.commit()
