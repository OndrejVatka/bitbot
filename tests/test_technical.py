"""Tests for technical indicator calculations."""

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from bitbot.config import SignalsConfig
from bitbot.signals.technical import TechnicalSignals, TechnicalResult


def _make_candles(
    prices: list[float],
    volumes: list[float] | None = None,
    start: datetime | None = None,
    interval_minutes: int = 15,
) -> pd.DataFrame:
    """Create a synthetic OHLCV DataFrame for testing.

    Uses close prices to generate plausible OHLC data.
    """
    if start is None:
        start = datetime(2025, 1, 1, tzinfo=timezone.utc)
    if volumes is None:
        volumes = [1000.0] * len(prices)

    rows = []
    for i, (price, vol) in enumerate(zip(prices, volumes)):
        ts = start + timedelta(minutes=interval_minutes * i)
        noise = price * 0.005  # 0.5% noise for high/low
        rows.append({
            "timestamp": ts,
            "open": price + np.random.uniform(-noise, noise),
            "high": price + abs(noise),
            "low": price - abs(noise),
            "close": price,
            "volume": vol,
        })

    df = pd.DataFrame(rows)
    df.set_index("timestamp", inplace=True)
    return df


@pytest.fixture
def config() -> SignalsConfig:
    return SignalsConfig()


@pytest.fixture
def tech(config: SignalsConfig) -> TechnicalSignals:
    return TechnicalSignals(config)


class TestRSISignal:
    """Test RSI indicator signal calculation."""

    def test_oversold_gives_positive_signal(self, tech: TechnicalSignals) -> None:
        """RSI below 30 should produce a positive (buy) signal."""
        # Create a strong downtrend to push RSI below 30
        prices = [50000 - i * 200 for i in range(50)]
        df = _make_candles(prices)
        df_4h = _make_candles(prices[:10], interval_minutes=240)

        result = tech.analyze(df, df_4h)
        # Strong downtrend should give oversold RSI
        assert result.rsi_value < 35  # Should be low
        assert result.rsi_signal > 0  # Should be bullish

    def test_neutral_rsi(self, tech: TechnicalSignals) -> None:
        """RSI between 30-70 should produce near-zero signal."""
        # Flat/random prices → neutral RSI
        np.random.seed(42)
        prices = [50000 + np.random.uniform(-100, 100) for _ in range(50)]
        df = _make_candles(prices)
        df_4h = _make_candles(prices[:10], interval_minutes=240)

        result = tech.analyze(df, df_4h)
        assert 30 <= result.rsi_value <= 70
        assert abs(result.rsi_signal) < 0.3


class TestBollingerSignal:
    """Test Bollinger Bands signal calculation."""

    def test_price_below_lower_band(self, tech: TechnicalSignals) -> None:
        """Price dropping below lower Bollinger should give positive signal."""
        # Steady prices then sudden drop
        prices = [50000.0] * 30 + [50000 - i * 500 for i in range(1, 25)]
        df = _make_candles(prices)
        df_4h = _make_candles(prices[:10], interval_minutes=240)

        result = tech.analyze(df, df_4h)
        assert result.bollinger_signal > 0.0

    def test_price_above_upper_band(self, tech: TechnicalSignals) -> None:
        """Price surging above upper Bollinger should give negative signal."""
        prices = [50000.0] * 30 + [50000 + i * 500 for i in range(1, 25)]
        df = _make_candles(prices)
        df_4h = _make_candles(prices[:10], interval_minutes=240)

        result = tech.analyze(df, df_4h)
        assert result.bollinger_signal < 0.0


class TestVolumeSignal:
    """Test volume analysis signal."""

    def test_low_volume_dip_is_bullish(self, tech: TechnicalSignals) -> None:
        """Declining volume during a price drop should be bullish."""
        # 50 candles of normal volume, then 4 candles of low-volume decline
        # Baseline window [-25:-5] is entirely in the normal-volume period
        prices = [50000.0] * 50 + [50000 - i * 200 for i in range(1, 5)]
        volumes = [1000.0] * 50 + [100.0] * 4  # 10x drop in volume
        df = _make_candles(prices, volumes)
        df_4h = _make_candles(prices[:10], interval_minutes=240)

        result = tech.analyze(df, df_4h)
        assert result.volume_signal > 0.0
        assert result.volume_ratio < 0.8

    def test_high_volume_dip_is_bearish(self, tech: TechnicalSignals) -> None:
        """Spiking volume during a price drop should be bearish (panic)."""
        # 50 candles of normal volume, then 4 candles of high-volume decline
        prices = [50000.0] * 50 + [50000 - i * 200 for i in range(1, 5)]
        volumes = [1000.0] * 50 + [5000.0] * 4  # 5x spike in volume
        df = _make_candles(prices, volumes)
        df_4h = _make_candles(prices[:10], interval_minutes=240)

        result = tech.analyze(df, df_4h)
        assert result.volume_signal < 0.0
        assert result.volume_ratio > 1.5


class TestDipDetection:
    """Test dip magnitude and speed signals."""

    def test_moderate_dip_detected(self, tech: TechnicalSignals) -> None:
        """A 5%+ drop from recent high should produce positive magnitude signal."""
        high = 50000.0
        drop_pct = 6.0
        low = high * (1 - drop_pct / 100)
        # Price was at high, then dropped
        prices = [high] * 40 + [high - i * (high - low) / 14 for i in range(1, 15)]
        df = _make_candles(prices)
        df_4h = _make_candles(prices[:10], interval_minutes=240)

        result = tech.analyze(df, df_4h)
        assert result.dip_magnitude > 0.2
        assert result.drop_from_24h_high_pct > 4.0

    def test_flash_crash_gives_negative_speed(self, tech: TechnicalSignals) -> None:
        """A rapid >3% drop should produce negative speed signal (wait)."""
        # 8 candles = 2 hours at 15m. Drop 5% in that window.
        prices = [50000.0] * 46 + [50000 - i * 350 for i in range(1, 9)]
        df = _make_candles(prices)
        df_4h = _make_candles(prices[:10], interval_minutes=240)

        result = tech.analyze(df, df_4h)
        assert result.dip_speed < 0.0  # Negative = too fast


class TestSignalsClamping:
    """Test that all signals are properly clamped to [-1, 1]."""

    def test_all_signals_in_range(self, tech: TechnicalSignals) -> None:
        """Every signal should be between -1.0 and +1.0."""
        # Extreme downtrend
        prices = [50000 - i * 500 for i in range(60)]
        df = _make_candles(prices)
        df_4h = _make_candles(prices[:10], interval_minutes=240)

        result = tech.analyze(df, df_4h)
        for name, value in result.signals_dict.items():
            assert -1.0 <= value <= 1.0, f"Signal {name} out of range: {value}"


class TestTechnicalResult:
    """Test TechnicalResult dataclass."""

    def test_signals_dict_has_all_keys(self, tech: TechnicalSignals) -> None:
        """signals_dict should contain all 7 signal keys."""
        prices = [50000.0] * 55
        df = _make_candles(prices)
        df_4h = _make_candles(prices[:10], interval_minutes=240)

        result = tech.analyze(df, df_4h)
        expected_keys = {
            "rsi", "ma_short", "ma_long_trend", "bollinger",
            "volume", "dip_magnitude", "dip_speed",
        }
        assert set(result.signals_dict.keys()) == expected_keys
