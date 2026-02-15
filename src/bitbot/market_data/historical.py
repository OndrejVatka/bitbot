"""Historical candle data fetcher from Binance REST API."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import pandas as pd
from binance import AsyncClient

from bitbot.database.repository import Candle

logger = logging.getLogger(__name__)


class HistoricalDataFetcher:
    """Fetches historical kline/candlestick data from Binance."""

    def __init__(self, client: AsyncClient) -> None:
        self._client = client

    async def fetch_candles(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 200,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> list[Candle]:
        """Fetch historical klines from Binance REST API.

        Args:
            symbol: Trading pair (e.g., 'BTCUSDT').
            timeframe: Candle interval (e.g., '15m', '4h', '1d').
            limit: Number of candles to fetch (max 1000 per Binance).
            start_time: Optional start time filter.
            end_time: Optional end time filter.

        Returns:
            List of Candle objects in chronological order (oldest first).
        """
        kwargs: dict = {
            "symbol": symbol,
            "interval": timeframe,
            "limit": min(limit, 1000),
        }
        if start_time:
            kwargs["startTime"] = int(start_time.timestamp() * 1000)
        if end_time:
            kwargs["endTime"] = int(end_time.timestamp() * 1000)

        raw_klines = await self._client.get_klines(**kwargs)

        candles = [self._parse_kline(k) for k in raw_klines]
        logger.info(
            "Fetched %d %s candles for %s", len(candles), timeframe, symbol
        )
        return candles

    async def fetch_candles_df(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 200,
    ) -> pd.DataFrame:
        """Fetch candles and return as a DataFrame.

        Returns DataFrame with columns: timestamp, open, high, low, close, volume.
        Index is the timestamp.
        """
        candles = await self.fetch_candles(symbol, timeframe, limit)
        return candles_to_dataframe(candles)

    @staticmethod
    def _parse_kline(raw: list) -> Candle:
        """Convert a Binance raw kline array to a Candle.

        Binance kline format:
        [0] Open time (ms), [1] Open, [2] High, [3] Low, [4] Close,
        [5] Volume, [6] Close time (ms), [7] Quote asset volume,
        [8] Number of trades, [9] Taker buy base vol, [10] Taker buy quote vol,
        [11] Ignore
        """
        return Candle(
            timestamp=datetime.fromtimestamp(raw[0] / 1000, tz=timezone.utc),
            open=float(raw[1]),
            high=float(raw[2]),
            low=float(raw[3]),
            close=float(raw[4]),
            volume=float(raw[5]),
            is_closed=True,  # Historical candles are always closed
        )


def candles_to_dataframe(candles: list[Candle]) -> pd.DataFrame:
    """Convert a list of Candles to a pandas DataFrame.

    Returns DataFrame with columns: open, high, low, close, volume.
    Index is the timestamp (DatetimeIndex).
    """
    if not candles:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    df = pd.DataFrame(
        [
            {
                "timestamp": c.timestamp,
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "volume": c.volume,
            }
            for c in candles
        ]
    )
    df.set_index("timestamp", inplace=True)
    return df
