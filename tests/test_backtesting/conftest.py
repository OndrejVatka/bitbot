"""Shared fixtures for backtesting tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from bitbot.backtesting.data_loader import BacktestDataset
from bitbot.backtesting.engine import BacktestConfig


def make_candles_df(
    n: int,
    start_price: float = 50000.0,
    start_time: datetime | None = None,
    interval_minutes: int = 15,
    trend: float = 0.0,
    volatility: float = 0.002,
    seed: int = 42,
) -> pd.DataFrame:
    """Generate synthetic OHLCV candle data.

    Args:
        n: Number of candles.
        start_price: Opening price.
        start_time: Start timestamp (defaults to 2024-01-01 UTC).
        interval_minutes: Minutes between candles.
        trend: Per-candle drift (positive = bullish, negative = bearish).
        volatility: Standard deviation of per-candle returns.
        seed: Random seed for reproducibility.

    Returns:
        DataFrame with columns: open, high, low, close, volume.
        Index: DatetimeIndex.
    """
    if start_time is None:
        start_time = datetime(2024, 1, 1, tzinfo=timezone.utc)

    rng = np.random.RandomState(seed)
    returns = rng.normal(trend, volatility, n)

    timestamps = [
        start_time + timedelta(minutes=i * interval_minutes) for i in range(n)
    ]

    prices = [start_price]
    for r in returns[:-1]:
        prices.append(prices[-1] * (1 + r))

    data = []
    for i in range(n):
        base = prices[i]
        close = base * (1 + returns[i])
        high = max(base, close) * (1 + abs(rng.normal(0, volatility * 0.5)))
        low = min(base, close) * (1 - abs(rng.normal(0, volatility * 0.5)))
        volume = rng.uniform(100, 1000)

        data.append({
            "timestamp": timestamps[i],
            "open": base,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        })

    df = pd.DataFrame(data)
    df.set_index("timestamp", inplace=True)
    return df


def make_declining_candles(
    n: int = 200,
    start_price: float = 50000.0,
    decline_pct: float = 15.0,
    seed: int = 42,
) -> pd.DataFrame:
    """Generate candles with a decline — designed to trigger buy signals.

    Uses higher volatility and stronger trend to push RSI into oversold
    territory and create visible drops from recent highs.
    """
    per_candle_decline = -decline_pct / 100 / n
    return make_candles_df(
        n=n,
        start_price=start_price,
        trend=per_candle_decline,
        volatility=0.005,  # Higher volatility to create oversold RSI conditions
        seed=seed,
    )


def make_rising_candles(
    n: int = 200,
    start_price: float = 50000.0,
    rise_pct: float = 15.0,
    seed: int = 42,
) -> pd.DataFrame:
    """Generate candles with a steady rise — should not trigger buy signals."""
    per_candle_rise = rise_pct / 100 / n
    return make_candles_df(
        n=n,
        start_price=start_price,
        trend=per_candle_rise,
        volatility=0.001,
        seed=seed,
    )


@pytest.fixture
def default_config() -> BacktestConfig:
    """Default backtest config for testing."""
    return BacktestConfig(
        symbol="BTCUSDT",
        initial_capital=1000.0,
    )


@pytest.fixture
def declining_dataset() -> BacktestDataset:
    """Dataset with declining prices — should trigger buy signals."""
    candles_15m = make_declining_candles(n=400, decline_pct=30.0)
    candles_4h = make_candles_df(
        n=250,
        start_price=50000.0,
        interval_minutes=240,
        trend=-0.003,
        volatility=0.008,
        seed=42,
    )
    start_time = candles_15m.index[250].to_pydatetime()
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)

    return BacktestDataset(
        candles_15m=candles_15m,
        candles_4h=candles_4h,
        symbol="BTCUSDT",
        start=start_time,
        end=candles_15m.index[-1].to_pydatetime().replace(tzinfo=timezone.utc),
    )


@pytest.fixture
def rising_dataset() -> BacktestDataset:
    """Dataset with rising prices — should not trigger buy signals."""
    candles_15m = make_rising_candles(n=400, rise_pct=20.0)
    candles_4h = make_candles_df(
        n=250,
        start_price=50000.0,
        interval_minutes=240,
        trend=0.001,
        volatility=0.003,
        seed=42,
    )
    start_time = candles_15m.index[250].to_pydatetime()
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)

    return BacktestDataset(
        candles_15m=candles_15m,
        candles_4h=candles_4h,
        symbol="BTCUSDT",
        start=start_time,
        end=candles_15m.index[-1].to_pydatetime().replace(tzinfo=timezone.utc),
    )
