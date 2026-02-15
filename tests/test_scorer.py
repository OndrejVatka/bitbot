"""Tests for the confidence scorer."""

import pytest

from bitbot.config import ScoringConfig
from bitbot.signals.scorer import SignalScorer, ScoringResult


@pytest.fixture
def config() -> ScoringConfig:
    return ScoringConfig()


@pytest.fixture
def scorer(config: ScoringConfig) -> SignalScorer:
    return SignalScorer(config)


def _neutral_signals() -> dict[str, float]:
    """All signals at zero — no buy signal."""
    return {
        "rsi": 0.0,
        "ma_short": 0.0,
        "ma_long_trend": 0.0,
        "bollinger": 0.0,
        "volume": 0.0,
        "dip_magnitude": 0.0,
        "dip_speed": 0.0,
    }


def _strong_buy_signals() -> dict[str, float]:
    """All signals maxed out — strongest possible buy."""
    return {
        "rsi": 1.0,
        "ma_short": 1.0,
        "ma_long_trend": 1.0,
        "bollinger": 1.0,
        "volume": 1.0,
        "dip_magnitude": 1.0,
        "dip_speed": 1.0,
    }


class TestScoringBasics:
    """Test basic scoring behavior."""

    def test_neutral_signals_give_hold(self, scorer: SignalScorer) -> None:
        """All-zero signals should produce a hold action."""
        result = scorer.calculate_score(_neutral_signals())
        assert result.action == "hold"
        assert result.score < 60
        assert result.position_size_pct == 0.0

    def test_strong_buy_signals(self, scorer: SignalScorer) -> None:
        """Maxed-out bullish signals should produce a large buy."""
        result = scorer.calculate_score(_strong_buy_signals())
        assert result.action == "buy"
        assert result.score >= 85
        assert result.position_size_pct == 0.20  # large buy

    def test_score_clamped_to_0_100(self, scorer: SignalScorer) -> None:
        """Score should never exceed 0-100 range."""
        # All bearish — might go negative
        bearish = {k: -1.0 for k in _neutral_signals()}
        result = scorer.calculate_score(bearish)
        assert 0 <= result.score <= 100

    def test_score_is_integer(self, scorer: SignalScorer) -> None:
        """Score should be an integer."""
        result = scorer.calculate_score(_strong_buy_signals())
        assert isinstance(result.score, int)


class TestActionThresholds:
    """Test that score ranges map to correct actions."""

    def test_small_buy_range(self, scorer: SignalScorer) -> None:
        """Score 60-74 should produce a small buy (5%)."""
        # Moderate signals to land in 60-74 range
        signals = _neutral_signals()
        signals["rsi"] = 0.8       # +16
        signals["bollinger"] = 0.8  # +12
        signals["ma_short"] = 0.8   # +12
        signals["ma_long_trend"] = 0.5  # +7.5
        signals["dip_magnitude"] = 0.5  # +5
        # Total ~52.5 + dip_speed/volume adjustments

        # Fine-tune to get into 60-74 range
        signals["volume"] = 0.5     # +7.5
        # Total ~60

        result = scorer.calculate_score(signals)
        assert 60 <= result.score <= 74
        assert result.action == "buy"
        assert result.position_size_pct == 0.05

    def test_medium_buy_range(self, scorer: SignalScorer) -> None:
        """Score 75-84 should produce a medium buy (10%)."""
        signals = _neutral_signals()
        signals["rsi"] = 1.0       # +20
        signals["bollinger"] = 1.0  # +15
        signals["ma_short"] = 1.0   # +15
        signals["volume"] = 0.5     # +7.5
        signals["dip_speed"] = 0.5  # +5
        signals["ma_long_trend"] = 0.5  # +7.5
        signals["dip_magnitude"] = 0.5  # +5
        # Total = 75

        result = scorer.calculate_score(signals)
        assert 75 <= result.score <= 84
        assert result.action == "buy"
        assert result.position_size_pct == 0.10

    def test_bearish_trend_reduces_score(self, scorer: SignalScorer) -> None:
        """Negative ma_long_trend should reduce the score."""
        bullish = _neutral_signals()
        bullish["rsi"] = 1.0
        bullish["bollinger"] = 1.0
        bullish["ma_short"] = 1.0

        score_neutral = scorer.calculate_score(bullish).score

        bullish["ma_long_trend"] = -1.0  # Bearish long-term trend
        score_bearish = scorer.calculate_score(bullish).score

        assert score_bearish < score_neutral


class TestScoringResult:
    """Test ScoringResult structure."""

    def test_has_all_fields(self, scorer: SignalScorer) -> None:
        """Result should have score, action, position_size_pct, breakdown, reasoning."""
        result = scorer.calculate_score(_neutral_signals())

        assert isinstance(result.score, int)
        assert result.action in ("buy", "hold")
        assert isinstance(result.position_size_pct, float)
        assert isinstance(result.signals_breakdown, dict)
        assert isinstance(result.reasoning, str)
        assert len(result.reasoning) > 0

    def test_breakdown_includes_all_signals(self, scorer: SignalScorer) -> None:
        """Breakdown should have entries for all signal components."""
        result = scorer.calculate_score(_strong_buy_signals())
        expected_keys = {"rsi", "ma_short", "bollinger", "volume", "dip_speed",
                         "ma_long_trend", "dip_magnitude"}
        assert expected_keys.issubset(set(result.signals_breakdown.keys()))


class TestSentimentAdjustment:
    """Test sentiment (LLM) score adjustments."""

    def test_temporary_pullback_boosts_score(self, scorer: SignalScorer) -> None:
        """A 'temporary_pullback' sentiment should increase the score."""
        signals = _neutral_signals()
        signals["rsi"] = 0.8
        signals["bollinger"] = 0.5
        signals["ma_short"] = 0.5

        base = scorer.calculate_score(signals).score

        sentiment = {"classification": "temporary_pullback", "confidence": 80}
        boosted = scorer.calculate_score(signals, sentiment).score

        assert boosted > base

    def test_fundamental_shift_tanks_score(self, scorer: SignalScorer) -> None:
        """A 'fundamental_shift' sentiment should heavily reduce the score."""
        signals = _strong_buy_signals()
        base = scorer.calculate_score(signals).score

        sentiment = {"classification": "fundamental_shift", "confidence": 90}
        tanked = scorer.calculate_score(signals, sentiment).score

        assert tanked < base
        assert base - tanked >= 30  # At least 30-point penalty
