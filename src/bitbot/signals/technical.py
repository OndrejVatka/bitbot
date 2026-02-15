"""Technical indicator calculations for dip detection.

All signals are normalized to [-1.0, +1.0] where:
  +1.0 = strongest bullish/buy signal
  -1.0 = strongest bearish/sell signal
   0.0 = neutral
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
import pandas_ta as ta

from bitbot.config import SignalsConfig

logger = logging.getLogger(__name__)


@dataclass
class TechnicalResult:
    """Complete technical analysis output."""

    # Normalized signals (-1.0 to +1.0)
    rsi_signal: float
    ma_short_signal: float
    ma_long_trend: float
    bollinger_signal: float
    volume_signal: float
    dip_magnitude: float
    dip_speed: float

    # Raw indicator values (for logging, display, and LLM context)
    rsi_value: float
    ma_short_value: float
    ma_long_value: float
    bollinger_lower: float
    bollinger_upper: float
    current_price: float
    volume_ratio: float
    drop_from_24h_high_pct: float
    drop_from_7d_high_pct: float

    @property
    def signals_dict(self) -> dict[str, float]:
        """All normalized signals as a flat dict for the scorer."""
        return {
            "rsi": self.rsi_signal,
            "ma_short": self.ma_short_signal,
            "ma_long_trend": self.ma_long_trend,
            "bollinger": self.bollinger_signal,
            "volume": self.volume_signal,
            "dip_magnitude": self.dip_magnitude,
            "dip_speed": self.dip_speed,
        }


class TechnicalSignals:
    """Calculates technical indicators and produces normalized signals.

    Uses 15m candles for short-term indicators (RSI, 20-MA, Bollinger, volume)
    and 4h candles for the long-term 200-MA trend filter.
    """

    def __init__(self, config: SignalsConfig) -> None:
        self._config = config

    def analyze(
        self,
        candles_15m: pd.DataFrame,
        candles_4h: pd.DataFrame,
    ) -> TechnicalResult:
        """Run full technical analysis on both timeframes.

        Args:
            candles_15m: Primary timeframe OHLCV DataFrame (50+ rows expected).
            candles_4h: Trend timeframe OHLCV DataFrame (200+ rows ideal).

        Returns:
            TechnicalResult with all signals and raw values.
        """
        current_price = float(candles_15m["close"].iloc[-1])

        rsi_signal, rsi_value = self._calculate_rsi(candles_15m)
        ma_short_signal, ma_short_value = self._calculate_short_ma(candles_15m)
        ma_long_trend, ma_long_value = self._calculate_long_ma(candles_4h, current_price)
        boll_signal, boll_lower, boll_upper = self._calculate_bollinger(candles_15m)
        vol_signal, vol_ratio = self._calculate_volume(candles_15m)
        dip_mag, dip_spd, drop_24h, drop_7d = self._calculate_dip(candles_15m)

        return TechnicalResult(
            rsi_signal=rsi_signal,
            ma_short_signal=ma_short_signal,
            ma_long_trend=ma_long_trend,
            bollinger_signal=boll_signal,
            volume_signal=vol_signal,
            dip_magnitude=dip_mag,
            dip_speed=dip_spd,
            rsi_value=rsi_value,
            ma_short_value=ma_short_value,
            ma_long_value=ma_long_value,
            bollinger_lower=boll_lower,
            bollinger_upper=boll_upper,
            current_price=current_price,
            volume_ratio=vol_ratio,
            drop_from_24h_high_pct=drop_24h,
            drop_from_7d_high_pct=drop_7d,
        )

    def _calculate_rsi(self, df: pd.DataFrame) -> tuple[float, float]:
        """Calculate RSI signal and raw value.

        RSI < 20 (extremely oversold) → +1.0
        RSI < 30 (oversold)           → +0.5 to +1.0 (scaled)
        RSI 30-70 (neutral)           → 0.0
        RSI > 70 (overbought)         → -0.5 to -1.0 (scaled)
        """
        rsi_series = ta.rsi(df["close"], length=self._config.rsi_period)
        if rsi_series is None or rsi_series.dropna().empty:
            return 0.0, 50.0

        rsi_value = float(rsi_series.iloc[-1])

        if rsi_value <= self._config.rsi_extremely_oversold:
            signal = 1.0
        elif rsi_value <= self._config.rsi_oversold:
            # Scale linearly from +0.5 (at 30) to +1.0 (at 20)
            signal = 0.5 + 0.5 * (self._config.rsi_oversold - rsi_value) / (
                self._config.rsi_oversold - self._config.rsi_extremely_oversold
            )
        elif rsi_value >= 70:
            # Scale from -0.5 (at 70) to -1.0 (at 100)
            signal = -0.5 - 0.5 * min((rsi_value - 70) / 30, 1.0)
        else:
            signal = 0.0

        return _clamp(signal), rsi_value

    def _calculate_short_ma(self, df: pd.DataFrame) -> tuple[float, float]:
        """Calculate price vs 20-period MA signal on primary timeframe.

        Price below MA → bullish (buy the dip)
        Price above MA → neutral to bearish
        """
        ma = ta.sma(df["close"], length=self._config.ma_short_period)
        if ma is None or ma.dropna().empty:
            return 0.0, 0.0

        ma_value = float(ma.iloc[-1])
        current_price = float(df["close"].iloc[-1])

        if ma_value == 0:
            return 0.0, 0.0

        pct_from_ma = (current_price - ma_value) / ma_value * 100

        # Below MA: signal scales from 0 to +1 as price drops further
        # Above MA: signal is 0 to -0.5
        if pct_from_ma < 0:
            signal = min(abs(pct_from_ma) / 5.0, 1.0)  # Max signal at 5% below
        else:
            signal = -min(pct_from_ma / 5.0, 0.5)

        return _clamp(signal), ma_value

    def _calculate_long_ma(
        self, df_4h: pd.DataFrame, current_price: float
    ) -> tuple[float, float]:
        """Calculate price vs 200-period MA on 4h timeframe (long-term trend).

        Price above 200-MA → bullish trend (dips are buy opportunities) → +0.5
        Price below 200-MA → bearish trend (dips may continue) → -0.5 to -1.0
        """
        if len(df_4h) < self._config.ma_long_period:
            # Not enough data for 200-MA — return neutral
            logger.debug(
                "Only %d 4h candles, need %d for long MA",
                len(df_4h),
                self._config.ma_long_period,
            )
            return 0.0, 0.0

        ma = ta.sma(df_4h["close"], length=self._config.ma_long_period)
        if ma is None or ma.dropna().empty:
            return 0.0, 0.0

        ma_value = float(ma.iloc[-1])
        if ma_value == 0:
            return 0.0, 0.0

        pct_from_ma = (current_price - ma_value) / ma_value * 100

        if pct_from_ma > 0:
            # Above 200-MA: bullish trend, dips are healthy
            signal = min(pct_from_ma / 10.0, 0.5)
        else:
            # Below 200-MA: bearish caution
            signal = max(pct_from_ma / 10.0, -1.0)

        return _clamp(signal), ma_value

    def _calculate_bollinger(
        self, df: pd.DataFrame
    ) -> tuple[float, float, float]:
        """Calculate Bollinger Bands signal.

        Price at/below lower band → oversold → +0.5 to +1.0
        Price between bands → neutral
        Price at/above upper band → overbought → -0.5 to -1.0
        """
        bbands = ta.bbands(
            df["close"],
            length=self._config.bollinger_period,
            std=self._config.bollinger_std,
        )
        if bbands is None or bbands.dropna().empty:
            return 0.0, 0.0, 0.0

        # pandas-ta uses format: BBL_{length}_{std}_{std} (std appears twice)
        std = self._config.bollinger_std
        length = self._config.bollinger_period
        col_prefix = f"BBL_{length}_{std}_{std}"
        col_upper = f"BBU_{length}_{std}_{std}"
        col_mid = f"BBM_{length}_{std}_{std}"

        # Fallback: find columns dynamically if naming convention changes
        if col_prefix not in bbands.columns:
            bb_cols = [c for c in bbands.columns if c.startswith("BBL_")]
            if not bb_cols:
                return 0.0, 0.0, 0.0
            col_prefix = bb_cols[0]
            col_upper = col_prefix.replace("BBL_", "BBU_")
            col_mid = col_prefix.replace("BBL_", "BBM_")

        lower = float(bbands[col_prefix].iloc[-1])
        upper = float(bbands[col_upper].iloc[-1])
        mid = float(bbands[col_mid].iloc[-1])
        current_price = float(df["close"].iloc[-1])

        band_width = upper - lower
        if band_width == 0:
            return 0.0, lower, upper

        # Position within the bands: 0 = at lower, 1 = at upper
        position = (current_price - lower) / band_width

        if position <= 0:
            # At or below lower band
            signal = min(0.5 + abs(position) * 0.5, 1.0)
        elif position >= 1:
            # At or above upper band
            signal = max(-0.5 - (position - 1) * 0.5, -1.0)
        elif position < 0.5:
            # Lower half of bands
            signal = (0.5 - position) / 0.5 * 0.3
        else:
            # Upper half of bands
            signal = -(position - 0.5) / 0.5 * 0.3

        return _clamp(signal), lower, upper

    def _calculate_volume(self, df: pd.DataFrame) -> tuple[float, float]:
        """Analyze volume relative to baseline average.

        Declining volume during drop → healthy dip (bullish) → +0.5
        Normal volume → neutral → 0.0
        Spiking volume during drop → panic selling (bearish) → -0.5 to -1.0

        Uses a baseline average from candles [-(n+20):-n] where n=5,
        avoiding contamination from the recent volume shift itself.
        """
        if len(df) < 30:
            return 0.0, 1.0

        # Recent volume: average of last 3 candles (captures current regime)
        recent_vol = float(df["volume"].iloc[-3:].mean())
        # Baseline volume: 20-period average ending 5 candles ago
        baseline_vol = float(df["volume"].iloc[-25:-5].mean())

        if baseline_vol == 0:
            return 0.0, 1.0

        vol_ratio = recent_vol / baseline_vol

        # Check if price is declining (last 3 candles)
        price_declining = float(df["close"].iloc[-1]) < float(df["close"].iloc[-3])

        threshold = self._config.volume_decline_threshold

        if price_declining:
            if vol_ratio < threshold:
                # Low volume during dip → healthy pullback
                signal = 0.5
            elif vol_ratio > 1.5:
                # High volume during dip → panic selling
                signal = -min((vol_ratio - 1.5) / 1.5, 1.0)
            else:
                signal = 0.0
        else:
            # Price not declining — volume less relevant for dip detection
            signal = 0.0

        return _clamp(signal), vol_ratio

    def _calculate_dip(
        self, df: pd.DataFrame
    ) -> tuple[float, float, float, float]:
        """Calculate dip magnitude and speed.

        Returns: (magnitude_signal, speed_signal, drop_24h_pct, drop_7d_pct)

        Magnitude: larger drops from recent highs → stronger buy signal
        Speed: gradual drops → bullish, flash crashes → wait
        """
        # Rolling 24h high on 15m candles = 96 candles
        candles_24h = min(96, len(df))
        high_24h = float(df["high"].iloc[-candles_24h:].max())
        current_price = float(df["close"].iloc[-1])

        drop_24h = (high_24h - current_price) / high_24h * 100 if high_24h > 0 else 0

        # Use all available data for 7d high (may be less than 7d on 15m)
        high_7d = float(df["high"].max())
        drop_7d = (high_7d - current_price) / high_7d * 100 if high_7d > 0 else 0

        # Magnitude signal: scale based on config thresholds
        mild = self._config.dip_mild_pct
        moderate = self._config.dip_moderate_pct
        major = self._config.dip_major_pct

        if drop_24h >= major:
            mag_signal = 1.0
        elif drop_24h >= moderate:
            mag_signal = 0.5 + 0.5 * (drop_24h - moderate) / (major - moderate)
        elif drop_24h >= mild:
            mag_signal = 0.2 + 0.3 * (drop_24h - mild) / (moderate - mild)
        else:
            mag_signal = 0.0

        # Speed signal: measure rate of decline over last 2 hours (8 candles at 15m)
        lookback = min(8, len(df))
        price_start = float(df["close"].iloc[-lookback])
        pct_change = (current_price - price_start) / price_start * 100 if price_start > 0 else 0

        # Gradual decline (0 to -3% over 2h) → safe → positive signal
        # Flash crash (>3% in 2h) → dangerous → negative signal
        if pct_change < -3:
            speed_signal = -min(abs(pct_change + 3) / 5.0, 1.0)
        elif pct_change < 0:
            speed_signal = min(abs(pct_change) / 3.0, 0.5)
        else:
            speed_signal = 0.0

        return _clamp(mag_signal), _clamp(speed_signal), drop_24h, drop_7d


def _clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
    """Clamp a value to [low, high]."""
    return max(low, min(high, value))
