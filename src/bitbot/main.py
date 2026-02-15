"""BitBot entry point — orchestrates all modules.

Phase 1: Connects to Binance, streams candles, calculates technical
indicators, and logs everything to SQLite.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from pathlib import Path

import certifi
from binance import AsyncClient

# Fix SSL certificate verification on macOS Python 3.12+
if not os.environ.get("SSL_CERT_FILE"):
    os.environ["SSL_CERT_FILE"] = certifi.where()

from bitbot.config import Settings, load_settings
from bitbot.database.repository import Repository
from bitbot.database.schema import initialize_database
from bitbot.market_data.historical import HistoricalDataFetcher
from bitbot.market_data.price_feed import PriceFeed
from bitbot.signals.technical import TechnicalSignals

logger = logging.getLogger("bitbot")


async def main() -> None:
    """BitBot Phase 1 main loop.

    1. Load config
    2. Initialize database
    3. Connect to Binance
    4. Fetch historical candles for warm-up
    5. Start WebSocket price feed
    6. On each 15m candle close: calculate indicators and log to DB
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    settings = load_settings(Path("config/settings.yaml"))
    symbol = settings.exchange.trading_pair
    timeframes = [
        settings.strategy.primary_timeframe,
        settings.strategy.trend_timeframe,
    ]

    logger.info(
        "Starting BitBot — mode=%s, pair=%s, timeframes=%s",
        settings.exchange.mode,
        symbol,
        timeframes,
    )

    # Database
    db = await initialize_database("data/bitbot.db")
    repo = Repository(db)
    logger.info("Database initialized at data/bitbot.db")

    # Binance client (empty keys are fine for public market data)
    client = await AsyncClient.create(
        api_key=settings.binance_api_key or None,
        api_secret=settings.binance_api_secret or None,
    )
    logger.info("Binance client connected")

    # Historical warm-up
    fetcher = HistoricalDataFetcher(client)
    for tf in timeframes:
        candles = await fetcher.fetch_candles(
            symbol, tf, limit=settings.strategy.indicator_period + 50
        )
        await repo.save_candles(symbol, tf, candles)

    # Price feed with warm-up
    feed = PriceFeed(client, symbol, timeframes, buffer_size=300)
    for tf in timeframes:
        cached = await repo.load_cached_candles(
            symbol, tf, limit=settings.strategy.indicator_period + 50
        )
        feed.warm_up(tf, cached)

    # Technical signals engine
    tech = TechnicalSignals(settings.signals)

    # Track candle count for logging
    candle_count = 0

    async def on_candle(sym: str, tf: str, candle) -> None:
        """Handle a closed candle — run analysis on primary timeframe."""
        nonlocal candle_count

        if tf != settings.strategy.primary_timeframe:
            return

        candle_count += 1
        candles_15m = feed.get_candles(settings.strategy.primary_timeframe)
        candles_4h = feed.get_candles(settings.strategy.trend_timeframe)

        if len(candles_15m) < 50:
            logger.warning("Not enough 15m candles yet (%d/50)", len(candles_15m))
            return

        result = tech.analyze(candles_15m, candles_4h)

        logger.info(
            "[#%d] price=%.2f | RSI=%.1f (sig=%.2f) | BB=%.2f | "
            "MA_short=%.2f | MA_long=%.2f | vol_ratio=%.2f (sig=%.2f) | "
            "dip_24h=%.1f%% speed=%.2f",
            candle_count,
            result.current_price,
            result.rsi_value,
            result.rsi_signal,
            result.bollinger_signal,
            result.ma_short_signal,
            result.ma_long_trend,
            result.volume_ratio,
            result.volume_signal,
            result.drop_from_24h_high_pct,
            result.dip_speed,
        )

        await repo.log_signal(
            symbol=sym,
            confidence_score=0,  # Scorer not implemented yet (Phase 2)
            action_taken="observe",
            technical_signals=result.signals_dict,
            price_at_signal=result.current_price,
        )

    feed.on_candle_close(on_candle)

    # Start streaming
    await feed.start()

    # Graceful shutdown on Ctrl+C / SIGTERM
    stop_event = asyncio.Event()

    def handle_shutdown() -> None:
        logger.info("Shutdown signal received...")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, handle_shutdown)

    logger.info("BitBot is running. Press Ctrl+C to stop.")
    await stop_event.wait()

    # Cleanup
    await feed.stop()
    await client.close_connection()
    await db.close()
    logger.info("BitBot shut down cleanly. Processed %d candles.", candle_count)


def run() -> None:
    """Synchronous entry point for the 'bitbot' console script."""
    asyncio.run(main())


if __name__ == "__main__":
    run()
