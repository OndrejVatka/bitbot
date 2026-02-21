"""Historical data download, caching, and loading for backtesting.

Downloads candles from Binance REST API in paginated batches, caches them
in the SQLite candles table, and produces aligned multi-timeframe datasets
for the backtest engine.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pandas as pd

from bitbot.database.repository import Candle, Repository
from bitbot.market_data.historical import HistoricalDataFetcher, candles_to_dataframe

logger = logging.getLogger(__name__)

# Binance kline limits
MAX_CANDLES_PER_REQUEST = 1000
REQUEST_DELAY_SECONDS = 0.1  # Courtesy delay between paginated requests

# Timeframe durations for pagination calculations
TIMEFRAME_MINUTES: dict[str, int] = {
    "1m": 1,
    "3m": 3,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "2h": 120,
    "4h": 240,
    "6h": 360,
    "8h": 480,
    "12h": 720,
    "1d": 1440,
    "3d": 4320,
    "1w": 10080,
}


@dataclass
class BacktestDataset:
    """Pre-loaded, aligned candle data for a backtest run.

    The DataFrames include warmup candles before `start` so that
    indicators (e.g., 200-MA) are fully primed from the first scored candle.
    """

    candles_15m: pd.DataFrame
    candles_4h: pd.DataFrame
    symbol: str
    start: datetime
    end: datetime

    @property
    def scored_start_index(self) -> int:
        """Index in candles_15m where the scored period begins (after warmup)."""
        mask = self.candles_15m.index >= self.start
        indices = self.candles_15m.index[mask]
        if len(indices) == 0:
            return len(self.candles_15m)
        return self.candles_15m.index.get_loc(indices[0])


class DataLoader:
    """Downloads and caches historical candle data for backtesting."""

    def __init__(self, fetcher: HistoricalDataFetcher, repo: Repository) -> None:
        self._fetcher = fetcher
        self._repo = repo

    async def ensure_cached(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> int:
        """Download and cache any missing candles in the date range.

        Paginates in 1000-candle chunks. Uses upsert so re-downloads
        are safe (idempotent).

        Returns:
            Total number of candles downloaded.
        """
        tf_minutes = TIMEFRAME_MINUTES.get(timeframe)
        if tf_minutes is None:
            raise ValueError(f"Unsupported timeframe: {timeframe}")

        total_downloaded = 0
        current_start = start

        while current_start < end:
            candles = await self._fetcher.fetch_candles(
                symbol=symbol,
                timeframe=timeframe,
                limit=MAX_CANDLES_PER_REQUEST,
                start_time=current_start,
                end_time=end,
            )

            if not candles:
                break

            await self._repo.save_candles(symbol, timeframe, candles)
            total_downloaded += len(candles)

            # Advance past the last candle we received
            last_ts = candles[-1].timestamp
            current_start = last_ts + timedelta(minutes=tf_minutes)

            logger.info(
                "Cached %d %s candles for %s (up to %s), total: %d",
                len(candles),
                timeframe,
                symbol,
                last_ts.isoformat(),
                total_downloaded,
            )

            # Stop if we got fewer than requested (no more data)
            if len(candles) < MAX_CANDLES_PER_REQUEST:
                break

            await asyncio.sleep(REQUEST_DELAY_SECONDS)

        logger.info(
            "Download complete: %d %s candles for %s (%s to %s)",
            total_downloaded,
            timeframe,
            symbol,
            start.isoformat(),
            end.isoformat(),
        )
        return total_downloaded

    async def load_dataset(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        warmup_candles: int = 250,
    ) -> BacktestDataset:
        """Load aligned 15m + 4h candles for the given backtest range.

        Prepends `warmup_candles` worth of data before `start` so indicators
        have enough history from the first scored candle.

        Args:
            symbol: Trading pair (e.g., 'BTCUSDT').
            start: Start of the scored backtest period.
            end: End of the backtest period.
            warmup_candles: Number of extra 15m candles before start for indicator warm-up.

        Returns:
            BacktestDataset with aligned 15m and 4h DataFrames.
        """
        # Calculate warmup start: warmup_candles * 15min before the scored start
        warmup_duration = timedelta(minutes=warmup_candles * 15)
        data_start = start - warmup_duration

        # Also need 4h warmup: 250 * 4h = 1000h before scored start
        warmup_4h_duration = timedelta(hours=warmup_candles * 4)
        data_start_4h = start - warmup_4h_duration

        # Ensure data is cached
        earliest_start = min(data_start, data_start_4h)
        await self.ensure_cached(symbol, "15m", data_start, end)
        await self.ensure_cached(symbol, "4h", earliest_start, end)

        # Load from cache
        candles_15m = await self._repo.load_candles_range(
            symbol, "15m", data_start, end
        )
        candles_4h = await self._repo.load_candles_range(
            symbol, "4h", data_start_4h, end
        )

        df_15m = candles_to_dataframe(candles_15m)
        df_4h = candles_to_dataframe(candles_4h)

        logger.info(
            "Loaded dataset: %d 15m candles, %d 4h candles (%s to %s, warmup from %s)",
            len(df_15m),
            len(df_4h),
            start.isoformat(),
            end.isoformat(),
            data_start.isoformat(),
        )

        return BacktestDataset(
            candles_15m=df_15m,
            candles_4h=df_4h,
            symbol=symbol,
            start=start,
            end=end,
        )
