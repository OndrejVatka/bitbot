"""Trades and signals history routes."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query

from bitbot.api.schemas import SignalSchema, TradeSchema
from bitbot.api.state import bot_state

router = APIRouter()


@router.get("/trades", response_model=list[TradeSchema])
async def get_trades(
    limit: int = Query(default=50, ge=1, le=200),
) -> list[TradeSchema]:
    if bot_state.repo is None:
        raise HTTPException(status_code=503, detail="Bot not initialized")

    rows = await bot_state.repo.get_recent_trades(bot_state.symbol, limit=limit)
    return [
        TradeSchema(
            id=row["id"],
            symbol=row["symbol"],
            timestamp=row["timestamp"],
            side=row["side"],
            price=row["price"],
            quantity=row["quantity"],
            fee=row["fee"],
            position_id=row.get("position_id"),
            mode=row["mode"],
            order_type=row["order_type"],
        )
        for row in rows
    ]


@router.get("/signals", response_model=list[SignalSchema])
async def get_signals(
    limit: int = Query(default=50, ge=1, le=200),
) -> list[SignalSchema]:
    if bot_state.repo is None:
        raise HTTPException(status_code=503, detail="Bot not initialized")

    rows = await bot_state.repo.get_recent_signals(bot_state.symbol, limit=limit)
    result: list[SignalSchema] = []

    for row in rows:
        raw_signals = row.get("technical_signals")
        if isinstance(raw_signals, str):
            try:
                raw_signals = json.loads(raw_signals)
            except (json.JSONDecodeError, TypeError):
                raw_signals = {}

        raw_sentiment = row.get("sentiment_result")
        if isinstance(raw_sentiment, str):
            try:
                raw_sentiment = json.loads(raw_sentiment)
            except (json.JSONDecodeError, TypeError):
                raw_sentiment = None

        result.append(
            SignalSchema(
                id=row["id"],
                symbol=row["symbol"],
                timestamp=row["timestamp"],
                confidence_score=row["confidence_score"],
                action_taken=row["action_taken"],
                price_at_signal=row["price_at_signal"],
                technical_signals=raw_signals or {},
                sentiment_result=raw_sentiment,
            )
        )

    return result
