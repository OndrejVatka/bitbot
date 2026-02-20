"""LLM sentiment analysis layer — Phase 4.

Uses Claude to classify price dips as healthy pullbacks vs dangerous
corrections based on technical indicators, recent news, and market fear.
Triggered only when the technical score exceeds the configured threshold.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

import aiohttp
import anthropic

from bitbot.config import LLMConfig, NewsConfig
from bitbot.signals.technical import TechnicalResult

logger = logging.getLogger(__name__)

# Prompt sent to Claude for sentiment classification
SENTIMENT_PROMPT = """\
You are a crypto market analyst. Assess the current Bitcoin price action.

CURRENT MARKET DATA:
- BTC Price: ${current_price:,.2f} (24h drop: {drop_24h:.1f}%)
- RSI (14): {rsi:.1f}
- 20-MA: ${ma_short:,.2f} (price {ma_short_relation} short MA)
- 200-MA (4h): ${ma_long:,.2f} (price {ma_long_relation} long MA)
- Bollinger Bands: Lower ${bb_lower:,.2f}, Upper ${bb_upper:,.2f}
- Volume: {volume_ratio:.2f}x average
- 7d drop: {drop_7d:.1f}%
- Fear & Greed Index: {fg_value}/100 ({fg_label})

RECENT NEWS:
{news_section}

Classify the current dip. Respond ONLY with valid JSON, no other text:
{{"classification": "temporary_pullback" | "deeper_correction" | "fundamental_shift", "confidence": <0-100>, "reasoning": "<1-2 sentences>", "recommended_action": "buy" | "wait" | "avoid"}}"""


class SentimentAnalyzer:
    """Fetches news + Fear & Greed, calls Claude, returns structured sentiment.

    All external calls are wrapped in try/except — failures return ``None``
    so the main loop is never blocked.
    """

    def __init__(
        self,
        llm_config: LLMConfig,
        news_config: NewsConfig,
        anthropic_api_key: str,
        cryptopanic_api_key: str,
    ) -> None:
        self._model = llm_config.model
        self._max_calls = llm_config.max_calls_per_hour
        self._news_config = news_config
        self._cryptopanic_key = cryptopanic_api_key

        self._client = anthropic.AsyncAnthropic(api_key=anthropic_api_key)

        # Simple sliding-window rate limiter
        self._call_timestamps: list[datetime] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def analyze(
        self,
        technical: TechnicalResult,
        current_price: float,
    ) -> dict | None:
        """Run the full sentiment pipeline.

        Returns a dict with keys ``classification``, ``confidence``,
        ``reasoning``, ``recommended_action`` — or ``None`` if rate-limited
        or any step fails.
        """
        if self._is_rate_limited():
            logger.info("Sentiment call skipped — rate limit (%d/h)", self._max_calls)
            return None

        headlines = await self._fetch_headlines()
        fg_value, fg_label = await self._fetch_fear_greed()
        prompt = self._build_prompt(technical, current_price, headlines, fg_value, fg_label)
        result = await self._call_claude(prompt)

        if result:
            logger.info(
                "LLM sentiment: classification=%s confidence=%d reasoning=%s",
                result.get("classification"),
                result.get("confidence", 0),
                result.get("reasoning", "")[:80],
            )

        return result

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------

    def _is_rate_limited(self) -> bool:
        """Return True if we've hit the hourly call cap."""
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=1)
        self._call_timestamps = [t for t in self._call_timestamps if t > cutoff]
        return len(self._call_timestamps) >= self._max_calls

    def _record_call(self) -> None:
        self._call_timestamps.append(datetime.now(timezone.utc))

    # ------------------------------------------------------------------
    # News headlines (CryptoPanic)
    # ------------------------------------------------------------------

    async def _fetch_headlines(self) -> list[str]:
        """Fetch recent BTC news from CryptoPanic. Returns [] on failure."""
        if not self._cryptopanic_key:
            return []

        url = "https://cryptopanic.com/api/v1/posts/"
        params = {
            "auth_token": self._cryptopanic_key,
            "currencies": "BTC",
            "kind": "news",
            "filter": "important",
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        logger.warning("CryptoPanic returned %d", resp.status)
                        return []
                    data = await resp.json()
                    results = data.get("results", [])
                    return [
                        r["title"]
                        for r in results[: self._news_config.max_headlines]
                        if "title" in r
                    ]
        except Exception as exc:
            logger.warning("CryptoPanic fetch failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Fear & Greed Index (alternative.me)
    # ------------------------------------------------------------------

    async def _fetch_fear_greed(self) -> tuple[int, str]:
        """Fetch the current Fear & Greed Index. Returns (50, "Neutral") on failure."""
        url = "https://api.alternative.me/fng/"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        logger.warning("Fear & Greed API returned %d", resp.status)
                        return 50, "Neutral"
                    data = await resp.json()
                    entry = data.get("data", [{}])[0]
                    value = int(entry.get("value", 50))
                    label = entry.get("value_classification", "Neutral")
                    return value, label
        except Exception as exc:
            logger.warning("Fear & Greed fetch failed: %s", exc)
            return 50, "Neutral"

    # ------------------------------------------------------------------
    # Prompt construction
    # ------------------------------------------------------------------

    def _build_prompt(
        self,
        tech: TechnicalResult,
        current_price: float,
        headlines: list[str],
        fg_value: int,
        fg_label: str,
    ) -> str:
        news_section = (
            "\n".join(f"{i + 1}. {h}" for i, h in enumerate(headlines))
            if headlines
            else "No recent headlines available."
        )

        return SENTIMENT_PROMPT.format(
            current_price=current_price,
            drop_24h=tech.drop_from_24h_high_pct,
            rsi=tech.rsi_value,
            ma_short=tech.ma_short_value,
            ma_short_relation="below" if current_price < tech.ma_short_value else "above",
            ma_long=tech.ma_long_value,
            ma_long_relation="below" if current_price < tech.ma_long_value else "above",
            bb_lower=tech.bollinger_lower,
            bb_upper=tech.bollinger_upper,
            volume_ratio=tech.volume_ratio,
            drop_7d=tech.drop_from_7d_high_pct,
            fg_value=fg_value,
            fg_label=fg_label,
            news_section=news_section,
        )

    # ------------------------------------------------------------------
    # Claude API call
    # ------------------------------------------------------------------

    async def _call_claude(self, prompt: str) -> dict | None:
        """Send the prompt to Claude and parse the JSON response."""
        try:
            self._record_call()

            response = await self._client.messages.create(
                model=self._model,
                max_tokens=256,
                messages=[{"role": "user", "content": prompt}],
            )

            raw = response.content[0].text.strip()

            # Strip markdown code fences if present
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3].strip()
            if raw.startswith("json"):
                raw = raw[4:].strip()

            result = json.loads(raw)

            # Validate required fields
            if "classification" not in result or "confidence" not in result:
                logger.warning("Claude response missing required fields: %s", raw[:120])
                return None

            # Clamp confidence to 0-100
            result["confidence"] = max(0, min(100, int(result["confidence"])))

            valid_classifications = {"temporary_pullback", "deeper_correction", "fundamental_shift"}
            if result["classification"] not in valid_classifications:
                logger.warning("Unknown classification: %s", result["classification"])
                return None

            return result

        except json.JSONDecodeError as exc:
            logger.warning("Claude returned non-JSON: %s", exc)
            return None
        except anthropic.APIError as exc:
            logger.warning("Claude API error: %s", exc)
            return None
        except Exception as exc:
            logger.warning("Sentiment call failed: %s", exc)
            return None
