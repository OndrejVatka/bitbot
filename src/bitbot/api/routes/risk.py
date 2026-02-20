"""Risk status, config, health, and risk-events routes."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query

from bitbot.api.schemas import ConfigSchema, HealthSchema, RiskEventSchema, RiskSchema
from bitbot.api.state import bot_state

router = APIRouter()


@router.get("/risk", response_model=RiskSchema)
async def get_risk() -> RiskSchema:
    if bot_state.risk is None or bot_state.settings is None:
        raise HTTPException(status_code=503, detail="Bot not initialized")

    risk = bot_state.risk
    now = datetime.now(timezone.utc)
    current_price = bot_state.current_price
    prices = {bot_state.symbol: current_price} if current_price else {}

    current_value = (
        bot_state.portfolio.get_total_value(prices)
        if bot_state.portfolio and current_price
        else None
    )

    peak = risk._peak_value
    drawdown_pct = (
        max(0.0, (peak - (current_value or peak)) / peak * 100) if peak else 0.0
    )

    daily_start = risk._daily_start_value
    daily_pnl_pct = (
        ((current_value or daily_start) - daily_start) / daily_start * 100
        if daily_start
        else 0.0
    )

    cooldown_active = False
    cooldown_remaining = 0
    if risk._last_stoploss_time:
        cooldown_end = risk._last_stoploss_time + timedelta(
            hours=risk._config.cooldown_after_stoploss_hours
        )
        if now < cooldown_end:
            cooldown_active = True
            cooldown_remaining = int((cooldown_end - now).total_seconds())

    sentiment_active = False
    sentiment_remaining = 0
    if risk._sentiment_block_until and now < risk._sentiment_block_until:
        sentiment_active = True
        sentiment_remaining = int((risk._sentiment_block_until - now).total_seconds())

    return RiskSchema(
        is_halted=risk._halted,
        halt_reason=risk._halt_reason if risk._halted else None,
        peak_value=peak,
        current_value=current_value,
        drawdown_pct=drawdown_pct,
        daily_start_value=daily_start,
        daily_pnl_pct=daily_pnl_pct,
        cooldown_active=cooldown_active,
        cooldown_remaining_seconds=cooldown_remaining,
        sentiment_block_active=sentiment_active,
        sentiment_block_remaining_seconds=sentiment_remaining,
    )


@router.get("/config", response_model=ConfigSchema)
async def get_config() -> ConfigSchema:
    if bot_state.settings is None:
        raise HTTPException(status_code=503, detail="Bot not initialized")

    s = bot_state.settings
    return ConfigSchema(
        symbol=s.exchange.trading_pair,
        mode=s.exchange.mode,
        initial_capital=s.capital.initial_usdt,
        buy_threshold=s.scoring.buy_threshold,
        small_buy_range=s.scoring.small_buy_range,
        medium_buy_range=s.scoring.medium_buy_range,
        large_buy_range=s.scoring.large_buy_range,
        small_buy_pct=s.scoring.small_buy_pct,
        medium_buy_pct=s.scoring.medium_buy_pct,
        large_buy_pct=s.scoring.large_buy_pct,
        profit_target_pct=s.selling.profit_target_pct,
        stop_loss_pct=s.risk.stop_loss_pct,
        max_daily_loss_pct=s.risk.max_daily_loss_pct,
        max_drawdown_pct=s.risk.max_drawdown_pct,
        dca_tranches=s.dca.tranches,
        min_interval_minutes=s.dca.min_interval_minutes,
        max_interval_minutes=s.dca.max_interval_minutes,
        primary_timeframe=s.strategy.primary_timeframe,
        trend_timeframe=s.strategy.trend_timeframe,
    )


@router.get("/risk-events", response_model=list[RiskEventSchema])
async def get_risk_events(
    limit: int = Query(default=20, ge=1, le=100),
) -> list[RiskEventSchema]:
    if bot_state.repo is None:
        raise HTTPException(status_code=503, detail="Bot not initialized")

    rows = await bot_state.repo.get_recent_risk_events(bot_state.symbol, limit=limit)
    return [
        RiskEventSchema(
            id=row["id"],
            symbol=row["symbol"],
            timestamp=row["timestamp"],
            event_type=row["event_type"],
            details=(
                json.loads(row["details"])
                if isinstance(row["details"], str)
                else (row["details"] or {})
            ),
        )
        for row in rows
    ]


@router.get("/health", response_model=HealthSchema)
async def health_check() -> HealthSchema:
    mode = bot_state.settings.exchange.mode if bot_state.settings else "unknown"
    return HealthSchema(
        status="ok",
        bot_running=bot_state.is_running,
        symbol=bot_state.symbol,
        mode=mode,
    )
