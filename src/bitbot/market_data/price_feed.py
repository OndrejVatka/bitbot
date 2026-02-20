"""Real-time WebSocket kline price feed from Binance."""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from datetime import datetime, timezone
from typing import Awaitable, Callable

import pandas as pd
from binance import AsyncClient, BinanceSocketManager

from bitbot.database.repository import Candle
from bitbot.market_data.historical import candles_to_dataframe

logger = logging.getLogger(__name__)

# Callback signature: (symbol, timeframe, candle) -> awaitable or None
CandleCallback = Callable[[str, str, Candle], Awaitable[None] | None]


class PriceFeed:
    """Manages WebSocket kline streams for real-time candle data.

    Supports multiple timeframes simultaneously (e.g., 15m + 4h).
    Maintains rolling in-memory buffers for indicator calculations.
    """

    def __init__(
        self,
        client: AsyncClient,
        symbol: str,
        timeframes: list[str],
        buffer_size: int = 250,
    ) -> None:
        self._client = client
        self._symbol = symbol.upper()
        self._timeframes = timeframes
        self._buffer_size = buffer_size
        self._buffers: dict[str, deque[Candle]] = {
            tf: deque(maxlen=buffer_size) for tf in timeframes
        }
        self._callbacks: list[CandleCallback] = []
        self._tasks: list[asyncio.Task] = []
        self._running = False

    async def start(self) -> None:
        """Start WebSocket streams for all configured timeframes."""
        self._running = True
        for tf in self._timeframes:
            task = asyncio.create_task(
                self._stream_klines(tf), name=f"ws-{self._symbol}-{tf}"
            )
            self._tasks.append(task)
            logger.info("Started kline stream: %s %s", self._symbol, tf)

    async def stop(self) -> None:
        """Gracefully stop all WebSocket streams."""
        self._running = False
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        logger.info("Price feed stopped for %s", self._symbol)

    def get_current_price(self) -> float | None:
        """Return the latest close price from the primary timeframe buffer."""
        primary_tf = self._timeframes[0] if self._timeframes else None
        if primary_tf and self._buffers[primary_tf]:
            return self._buffers[primary_tf][-1].close
        return None

    def get_candles(self, timeframe: str, period: int = 200) -> pd.DataFrame:
        """Return last N candles as a DataFrame for the given timeframe.

        Args:
            timeframe: Which timeframe buffer to read (e.g., '15m').
            period: Max number of candles to return.

        Returns:
            DataFrame with OHLCV columns, indexed by timestamp.
        """
        buffer = self._buffers.get(timeframe, deque())
        candles = list(buffer)[-period:]
        return candles_to_dataframe(candles)

    def warm_up(self, timeframe: str, candles: list[Candle]) -> None:
        """Pre-fill a timeframe buffer with historical candles.

        Call this before start() so indicators have data immediately.

        Args:
            timeframe: Which buffer to fill.
            candles: Historical candles in chronological order (oldest first).
        """
        buffer = self._buffers.get(timeframe)
        if buffer is None:
            logger.warning("Unknown timeframe %s, skipping warm-up", timeframe)
            return

        for candle in candles:
            buffer.append(candle)
        logger.info(
            "Warmed up %s %s buffer with %d candles",
            self._symbol,
            timeframe,
            len(candles),
        )

    def on_candle_close(self, callback: CandleCallback) -> None:
        """Register a callback that fires when a candle closes.

        The callback receives (symbol, timeframe, candle).
        Can be sync or async.
        """
        self._callbacks.append(callback)

    async def _stream_klines(self, timeframe: str) -> None:
        """Run a single kline WebSocket stream with auto-reconnect.

        Binance sends both in-progress and closed candles via kline events.
        We update the buffer on every tick (for current price) but only
        fire callbacks when a candle closes (is_closed=True).
        """
        backoff = 1
        max_backoff = 60

        while self._running:
            try:
                bsm = BinanceSocketManager(self._client)
                stream_name = f"{self._symbol.lower()}@kline_{timeframe}"
                async with bsm.kline_socket(
                    symbol=self._symbol, interval=timeframe
                ) as stream:
                    logger.info("WebSocket connected: %s", stream_name)
                    backoff = 1  # Reset on successful connection

                    while self._running:
                        msg = await stream.recv()

                        if msg.get("e") == "error":
                            logger.error("WebSocket error: %s", msg)
                            break

                        kline = msg.get("k", {})
                        candle = self._parse_ws_kline(kline)
                        buffer = self._buffers[timeframe]

                        if candle.is_closed:
                            buffer.append(candle)
                            await self._fire_callbacks(timeframe, candle)
                        else:
                            # Update the latest in-progress candle for current price
                            if buffer and not buffer[-1].is_closed:
                                buffer[-1] = candle
                            else:
                                buffer.append(candle)

            except asyncio.CancelledError:
                break
            except Exception as e:
                if not self._running:
                    break
                logger.warning(
                    "WebSocket disconnected (%s %s): %s. Reconnecting in %ds...",
                    self._symbol,
                    timeframe,
                    e,
                    backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)

    async def _fire_callbacks(self, timeframe: str, candle: Candle) -> None:
        """Invoke all registered callbacks for a closed candle."""
        for cb in self._callbacks:
            try:
                result = cb(self._symbol, timeframe, candle)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                logger.exception("Error in candle callback")

    @staticmethod
    def _parse_ws_kline(kline: dict) -> Candle:
        """Convert a Binance WebSocket kline event to a Candle.

        kline fields: t (open time), o, h, l, c, v, x (is closed), etc.
        """
        return Candle(
            timestamp=datetime.fromtimestamp(kline["t"] / 1000, tz=timezone.utc),
            open=float(kline["o"]),
            high=float(kline["h"]),
            low=float(kline["l"]),
            close=float(kline["c"]),
            volume=float(kline["v"]),
            is_closed=kline["x"],
        )
