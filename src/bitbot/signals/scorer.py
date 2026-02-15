"""Confidence score calculator — combines signals into actionable decisions.

Maps normalized technical signals (-1 to +1) to a 0–100 confidence score,
then determines the trading action and position size.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from bitbot.config import ScoringConfig

logger = logging.getLogger(__name__)

# Max point contributions per signal (total max = 75 from technical alone)
SIGNAL_WEIGHTS: dict[str, float] = {
    "rsi": 20.0,
    "ma_short": 15.0,
    "bollinger": 15.0,
    "volume": 15.0,
    "dip_speed": 10.0,
}

# These signals contribute as adjustments rather than base points
ADJUSTMENT_WEIGHTS: dict[str, float] = {
    "ma_long_trend": 15.0,   # Penalty/bonus for long-term trend
    "dip_magnitude": 10.0,   # Bonus for significant dips
}


@dataclass
class ScoringResult:
    """Output of the confidence scorer."""

    score: int                         # 0-100 confidence score
    action: str                        # "buy" or "hold"
    position_size_pct: float           # % of available capital (0 if hold)
    signals_breakdown: dict[str, float]  # signal name → point contribution
    reasoning: str                     # Human-readable explanation


class SignalScorer:
    """Combines technical signals into a single confidence score.

    Scoring logic:
    - Base score starts at 0
    - Each positive technical signal contributes points up to its weight
    - Negative signals contribute 0 (they don't subtract from base)
    - Long-term trend and dip magnitude act as adjustments (can add or subtract)
    - Sentiment adjustment is applied on top (Phase 4, stubbed for now)
    """

    def __init__(self, config: ScoringConfig) -> None:
        self._config = config

    def calculate_score(
        self,
        technical_signals: dict[str, float],
        sentiment_result: dict | None = None,
    ) -> ScoringResult:
        """Calculate confidence score from technical signals.

        Args:
            technical_signals: Dict of signal names → values in [-1, +1].
                Expected keys: rsi, ma_short, bollinger, volume, dip_speed,
                ma_long_trend, dip_magnitude.
            sentiment_result: LLM sentiment output (Phase 4, ignored for now).

        Returns:
            ScoringResult with score, action, and position sizing.
        """
        breakdown: dict[str, float] = {}
        base_score = 0.0

        # Base points from primary signals (only positive values contribute)
        for signal_name, max_points in SIGNAL_WEIGHTS.items():
            value = technical_signals.get(signal_name, 0.0)
            points = max(0.0, value) * max_points
            breakdown[signal_name] = round(points, 1)
            base_score += points

        # Adjustments (can be positive or negative)
        for signal_name, max_points in ADJUSTMENT_WEIGHTS.items():
            value = technical_signals.get(signal_name, 0.0)
            points = value * max_points
            breakdown[signal_name] = round(points, 1)
            base_score += points

        # Sentiment adjustment (Phase 4 — stubbed)
        sentiment_adj = self._calculate_sentiment_adjustment(sentiment_result)
        if sentiment_adj != 0:
            breakdown["sentiment"] = sentiment_adj
            base_score += sentiment_adj

        # Clamp to [0, 100]
        final_score = max(0, min(100, round(base_score)))

        # Determine action and position size
        action, size_pct = self._determine_action(final_score)

        # Build reasoning string
        reasoning = self._build_reasoning(final_score, action, breakdown)

        return ScoringResult(
            score=final_score,
            action=action,
            position_size_pct=size_pct,
            signals_breakdown=breakdown,
            reasoning=reasoning,
        )

    def _determine_action(self, score: int) -> tuple[str, float]:
        """Map score to action and position size percentage.

        Returns:
            (action, position_size_pct) tuple.
        """
        cfg = self._config

        if score >= cfg.large_buy_range[0]:
            return "buy", cfg.large_buy_pct
        elif score >= cfg.medium_buy_range[0]:
            return "buy", cfg.medium_buy_pct
        elif score >= cfg.small_buy_range[0]:
            return "buy", cfg.small_buy_pct
        else:
            return "hold", 0.0

    def _calculate_sentiment_adjustment(
        self, sentiment_result: dict | None
    ) -> float:
        """Calculate sentiment score adjustment from LLM output.

        Phase 4 implementation — currently returns 0.
        """
        if sentiment_result is None:
            return 0.0

        classification = sentiment_result.get("classification", "")
        confidence = sentiment_result.get("confidence", 50) / 100.0

        if classification == "temporary_pullback":
            # High confidence pullback → +25, low confidence → +10
            return 10.0 + 15.0 * confidence
        elif classification == "deeper_correction":
            return -20.0
        elif classification == "fundamental_shift":
            return -40.0

        return 0.0

    def _build_reasoning(
        self, score: int, action: str, breakdown: dict[str, float]
    ) -> str:
        """Build a human-readable reasoning string."""
        parts = []

        # Top contributors
        sorted_signals = sorted(
            breakdown.items(), key=lambda x: abs(x[1]), reverse=True
        )
        positive = [(k, v) for k, v in sorted_signals if v > 0]
        negative = [(k, v) for k, v in sorted_signals if v < 0]

        if positive:
            top = ", ".join(f"{k}(+{v:.0f})" for k, v in positive[:3])
            parts.append(f"Bullish: {top}")

        if negative:
            top = ", ".join(f"{k}({v:.0f})" for k, v in negative[:2])
            parts.append(f"Bearish: {top}")

        parts.append(f"Score: {score}/100 → {action.upper()}")

        return " | ".join(parts)
