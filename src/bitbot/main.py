"""BitBot entry point — orchestrates all modules.

Phase 2: Connects to Binance, streams candles, calculates technical
indicators, scores confidence, and executes paper trades with full
risk management.

The API server (FastAPI + uvicorn) runs alongside the bot loop in the
same asyncio event loop, sharing in-memory state via api.state.
"""

from __future__ import annotations

import asyncio
import logging
import logging.handlers
import os
import signal
from datetime import datetime, timezone
from pathlib import Path

import certifi
import uvicorn
from binance import AsyncClient

# Fix SSL certificate verification on macOS Python 3.12+
if not os.environ.get("SSL_CERT_FILE"):
    os.environ["SSL_CERT_FILE"] = certifi.where()

from bitbot.api.server import app as fastapi_app
from bitbot.api.state import bot_state
from bitbot.api.websocket import broadcaster
from bitbot.config import load_settings
from bitbot.database.repository import Repository
from bitbot.database.schema import initialize_database
from bitbot.market_data.historical import HistoricalDataFetcher
from bitbot.market_data.price_feed import PriceFeed
from bitbot.paper_trading.simulator import PaperExecutor
from bitbot.signals.scorer import SignalScorer
from bitbot.signals.sentiment import SentimentAnalyzer
from bitbot.signals.technical import TechnicalSignals
from bitbot.trading.portfolio import Portfolio
from bitbot.trading.risk_manager import RiskManager

logger = logging.getLogger("bitbot")


async def main() -> None:
    """BitBot main loop.

    1. Load config and initialize all modules
    2. Start the API server as a background asyncio task
    3. Fetch historical candles for warm-up
    4. Start WebSocket price feed
    5. On each 15m candle close:
       a. Calculate technical indicators
       b. Score confidence
       c. If score >= threshold: risk check → paper buy (with DCA scheduling)
       d. Check open positions for stop-loss / profit target
       e. Log everything and push WebSocket events
    """
    log_format = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"
    log_datefmt = "%Y-%m-%d %H:%M:%S"

    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        datefmt=log_datefmt,
    )

    # Add rotating file handler for production persistence
    log_dir = Path(os.environ.get("BITBOT_LOG_DIR", "data/logs"))
    log_dir.mkdir(parents=True, exist_ok=True)
    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / "bitbot.log",
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
    )
    file_handler.setFormatter(logging.Formatter(log_format, datefmt=log_datefmt))
    logging.getLogger().addHandler(file_handler)

    settings = load_settings(Path("config/settings.yaml"))
    symbol = settings.exchange.trading_pair
    timeframes = [
        settings.strategy.primary_timeframe,
        settings.strategy.trend_timeframe,
    ]

    logger.info(
        "Starting BitBot — mode=%s, pair=%s, capital=$%.2f",
        settings.exchange.mode,
        symbol,
        settings.capital.initial_usdt,
    )

    # Database
    db_path = os.environ.get("BITBOT_DB_PATH", "data/bitbot.db")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    db = await initialize_database(db_path)
    repo = Repository(db)
    logger.info("Database initialized")

    # Binance client
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

    # Price feed
    feed = PriceFeed(client, symbol, timeframes, buffer_size=300)
    for tf in timeframes:
        cached = await repo.load_cached_candles(
            symbol, tf, limit=settings.strategy.indicator_period + 50
        )
        feed.warm_up(tf, cached)

    # Signal engine
    tech = TechnicalSignals(settings.signals)
    scorer = SignalScorer(settings.scoring)

    # Trading modules
    portfolio = Portfolio(
        initial_capital=settings.capital.initial_usdt,
        fees_config=settings.fees,
        selling_config=settings.selling,
    )
    risk = RiskManager(
        config=settings.risk,
        portfolio=portfolio,
        initial_capital=settings.capital.initial_usdt,
    )
    executor = PaperExecutor(fees_config=settings.fees, repo=repo)

    # LLM sentiment layer
    sentiment_analyzer = SentimentAnalyzer(
        llm_config=settings.llm,
        news_config=settings.news,
        anthropic_api_key=settings.anthropic_api_key,
        cryptopanic_api_key=settings.cryptopanic_api_key,
    )
    logger.info("Sentiment analyzer initialized (model=%s)", settings.llm.model)

    # Populate shared API state so routes can serve live data
    bot_state.portfolio = portfolio
    bot_state.risk = risk
    bot_state.repo = repo
    bot_state.settings = settings
    bot_state.symbol = symbol
    bot_state.is_running = True

    # Start the API server in the same asyncio event loop
    uvicorn_config = uvicorn.Config(
        fastapi_app,
        host="0.0.0.0",
        port=8000,
        loop="asyncio",
        log_level="warning",
    )
    api_server = uvicorn.Server(uvicorn_config)
    asyncio.create_task(api_server.serve())
    logger.info("API server starting on http://0.0.0.0:8000 (Swagger: /docs)")

    # DCA tranche tracking: position_id → remaining tranches count
    pending_tranches: dict[str, int] = {}

    candle_count = 0

    async def schedule_dca_tranche(
        position_id: str,
        sym: str,
        tranche_usdt: float,
        dip_speed: float,
    ) -> None:
        """Schedule remaining DCA tranches with dynamic intervals.

        Faster dips → longer wait between tranches (let price stabilize).
        """
        remaining = pending_tranches.get(position_id, 0)
        if remaining <= 0:
            return

        # Dynamic interval: faster dip = longer wait
        speed_factor = max(0.0, min(1.0, abs(dip_speed)))
        interval_minutes = (
            settings.dca.min_interval_minutes
            + (settings.dca.max_interval_minutes - settings.dca.min_interval_minutes)
            * speed_factor
        )

        logger.info(
            "DCA tranche %d scheduled in %.0f min for %s (dip_speed=%.2f)",
            settings.dca.tranches - remaining + 1,
            interval_minutes,
            position_id[:8],
            dip_speed,
        )

        await asyncio.sleep(interval_minutes * 60)

        # Re-check risk before executing tranche
        position = portfolio.get_position(position_id)
        if position is None or position.status != "open":
            logger.info("DCA cancelled — position %s no longer open", position_id[:8])
            pending_tranches.pop(position_id, None)
            return

        current_price = feed.get_current_price()
        if current_price is None:
            pending_tranches.pop(position_id, None)
            return

        prices = {sym: current_price}
        risk_check = risk.can_open_position(tranche_usdt, prices)
        if not risk_check.allowed:
            logger.info(
                "DCA tranche skipped for %s: %s",
                position_id[:8],
                risk_check.reason,
            )
            pending_tranches.pop(position_id, None)
            return

        # Execute the DCA tranche
        trade = await executor.buy(sym, tranche_usdt, current_price)
        portfolio.add_tranche(position_id, trade.price, tranche_usdt)

        pending_tranches[position_id] = remaining - 1
        logger.info(
            "DCA tranche executed for %s @ $%.2f ($%.2f), %d remaining",
            position_id[:8],
            trade.price,
            tranche_usdt,
            remaining - 1,
        )

        await broadcaster.broadcast(
            "trade",
            {
                "side": "buy",
                "price": trade.price,
                "quantity": trade.quantity,
                "fee": trade.fee,
                "usdt_value": trade.usdt_value,
                "timestamp": trade.timestamp.isoformat(),
                "mode": trade.mode,
                "dca": True,
            },
        )

        # Schedule next tranche if any remain
        if remaining - 1 > 0:
            asyncio.create_task(
                schedule_dca_tranche(position_id, sym, tranche_usdt, dip_speed)
            )

    async def on_candle(sym: str, tf: str, candle) -> None:
        """Handle a closed candle — full analysis and trading loop."""
        nonlocal candle_count

        if tf != settings.strategy.primary_timeframe:
            return

        candle_count += 1
        candles_15m = feed.get_candles(settings.strategy.primary_timeframe)
        candles_4h = feed.get_candles(settings.strategy.trend_timeframe)

        if len(candles_15m) < 50:
            logger.warning("Not enough 15m candles yet (%d/50)", len(candles_15m))
            return

        # 1. Technical analysis
        result = tech.analyze(candles_15m, candles_4h)
        current_price = result.current_price
        prices = {sym: current_price}

        # Update shared state for API routes
        bot_state.current_price = current_price

        # 2a. Technical-only score (to check LLM trigger threshold)
        preliminary = scorer.calculate_score(result.signals_dict)

        # 2b. LLM sentiment layer (if score above trigger threshold)
        sentiment_result = None
        if preliminary.score >= settings.llm.trigger_threshold:
            sentiment_result = await sentiment_analyzer.analyze(result, current_price)

        # 2c. Final score (with sentiment adjustment if available)
        if sentiment_result:
            score_result = scorer.calculate_score(result.signals_dict, sentiment_result)
            # Block all buys if Claude detected a fundamental shift
            if sentiment_result.get("classification") == "fundamental_shift":
                risk.record_sentiment_block()
                await repo.log_risk_event(sym, "sentiment_block", sentiment_result)
                await broadcaster.broadcast(
                    "risk_event",
                    {
                        "event_type": "sentiment_block",
                        "details": sentiment_result,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                )
        else:
            score_result = preliminary

        logger.info(
            "[#%d] $%.2f | score=%d/%d | %s | %s%s",
            candle_count,
            current_price,
            score_result.score,
            100,
            score_result.action.upper(),
            score_result.reasoning,
            f" | sentiment={sentiment_result['classification']}" if sentiment_result else "",
        )

        # Log signal to DB (including sentiment when available)
        await repo.log_signal(
            symbol=sym,
            confidence_score=score_result.score,
            action_taken=score_result.action,
            technical_signals=result.signals_dict,
            price_at_signal=current_price,
            sentiment_result=sentiment_result,
        )

        # Push signal event to dashboard
        await broadcaster.broadcast(
            "signal",
            {
                "score": score_result.score,
                "action": score_result.action,
                "price": current_price,
                "signals": result.signals_dict,
                "reasoning": score_result.reasoning,
                "sentiment": sentiment_result,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

        # 3. Execute buy if score is high enough
        if score_result.action == "buy":
            available = portfolio.get_available_capital()
            buy_amount = available * score_result.position_size_pct

            # Split into DCA tranches
            tranche_count = settings.dca.tranches
            first_tranche_usdt = buy_amount / tranche_count

            risk_check = risk.can_open_position(buy_amount, prices)
            if risk_check.allowed:
                # Execute first tranche immediately
                trade = await executor.buy(sym, first_tranche_usdt, current_price)
                position = portfolio.open_position(sym, trade.price, first_tranche_usdt)

                logger.info(
                    "NEW POSITION %s: $%.2f @ $%.2f (score=%d, %d DCA tranches planned)",
                    position.id[:8],
                    first_tranche_usdt,
                    trade.price,
                    score_result.score,
                    tranche_count,
                )

                await broadcaster.broadcast(
                    "trade",
                    {
                        "side": "buy",
                        "price": trade.price,
                        "quantity": trade.quantity,
                        "fee": trade.fee,
                        "usdt_value": trade.usdt_value,
                        "timestamp": trade.timestamp.isoformat(),
                        "mode": trade.mode,
                        "dca": False,
                    },
                )

                # Schedule remaining DCA tranches
                if tranche_count > 1:
                    pending_tranches[position.id] = tranche_count - 1
                    asyncio.create_task(
                        schedule_dca_tranche(
                            position.id,
                            sym,
                            first_tranche_usdt,
                            result.dip_speed,
                        )
                    )
            else:
                logger.info(
                    "Buy blocked by risk manager: %s", risk_check.reason
                )

        # 4. Check open positions for exits
        # Stop-losses
        stop_loss_ids = risk.check_stop_losses(prices)
        for pos_id in stop_loss_ids:
            pos = portfolio.get_position(pos_id)
            if pos:
                qty = pos.total_quantity
                sell_trade = await executor.sell(sym, qty, current_price)
                pnl = portfolio.close_position(pos_id, current_price)
                risk.record_stop_loss()
                pending_tranches.pop(pos_id, None)
                logger.warning("STOP-LOSS %s: P&L=$%.2f", pos_id[:8], pnl)
                await repo.log_risk_event(
                    sym, "stop_loss", {"position_id": pos_id, "price": current_price, "pnl": pnl}
                )
                await broadcaster.broadcast(
                    "risk_event",
                    {
                        "event_type": "stop_loss",
                        "position_id": pos_id,
                        "price": current_price,
                        "pnl": pnl,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                )
                await broadcaster.broadcast(
                    "trade",
                    {
                        "side": "sell",
                        "price": sell_trade.price,
                        "quantity": sell_trade.quantity,
                        "fee": sell_trade.fee,
                        "usdt_value": sell_trade.usdt_value,
                        "timestamp": sell_trade.timestamp.isoformat(),
                        "mode": sell_trade.mode,
                        "reason": "stop_loss",
                    },
                )

        # Profit targets
        profit_ids = risk.check_profit_targets(prices)
        for pos_id in profit_ids:
            pos = portfolio.get_position(pos_id)
            if pos:
                sell_trade = await executor.sell(sym, pos.total_quantity, current_price)
                pnl = portfolio.close_position(pos_id, current_price)
                pending_tranches.pop(pos_id, None)
                logger.info("PROFIT TAKE %s: P&L=$%.2f", pos_id[:8], pnl)
                await broadcaster.broadcast(
                    "trade",
                    {
                        "side": "sell",
                        "price": sell_trade.price,
                        "quantity": sell_trade.quantity,
                        "fee": sell_trade.fee,
                        "usdt_value": sell_trade.usdt_value,
                        "timestamp": sell_trade.timestamp.isoformat(),
                        "mode": sell_trade.mode,
                        "reason": "profit_target",
                    },
                )

        # 5. Update risk tracking
        risk.update_tracking(prices)

        # Push current price event every candle
        await broadcaster.broadcast(
            "price",
            {
                "price": current_price,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

        # Periodic portfolio summary (every 10 candles)
        if candle_count % 10 == 0:
            total = portfolio.get_total_value(prices)
            realized = portfolio.get_realized_pnl()
            unrealized = portfolio.get_unrealized_pnl(prices)
            open_count = len(portfolio.get_open_positions())

            logger.info(
                "PORTFOLIO: total=$%.2f | cash=$%.2f | open=%d | "
                "realized=$%.2f | unrealized=$%.2f",
                total,
                portfolio.cash,
                open_count,
                realized,
                unrealized,
            )

            await repo.save_snapshot(
                symbol=sym,
                total_value=total,
                available_capital=portfolio.cash,
                open_positions_count=open_count,
                unrealized_pnl=unrealized,
                realized_pnl_cumulative=realized,
            )

            await broadcaster.broadcast(
                "snapshot",
                {
                    "total_value": total,
                    "available_capital": portfolio.cash,
                    "open_positions_count": open_count,
                    "unrealized_pnl": unrealized,
                    "realized_pnl": realized,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )

    feed.on_candle_close(on_candle)

    # Start streaming
    await feed.start()

    # Graceful shutdown
    stop_event = asyncio.Event()

    def handle_shutdown() -> None:
        logger.info("Shutdown signal received...")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, handle_shutdown)

    logger.info(
        "BitBot is running (paper mode). Capital=$%.2f. Press Ctrl+C to stop.",
        settings.capital.initial_usdt,
    )
    await stop_event.wait()

    # Final summary
    current_price = feed.get_current_price()
    if current_price:
        prices = {symbol: current_price}
        total = portfolio.get_total_value(prices)
        logger.info(
            "FINAL: portfolio=$%.2f | realized=$%.2f | unrealized=$%.2f | candles=%d",
            total,
            portfolio.get_realized_pnl(),
            portfolio.get_unrealized_pnl(prices),
            candle_count,
        )

    # Cleanup
    bot_state.is_running = False
    await feed.stop()
    await client.close_connection()
    await db.close()
    logger.info("BitBot shut down cleanly.")


def run() -> None:
    """Synchronous entry point for the 'bitbot' console script."""
    asyncio.run(main())


if __name__ == "__main__":
    run()
