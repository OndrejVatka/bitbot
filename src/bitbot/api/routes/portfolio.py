"""Portfolio and positions API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from bitbot.api.schemas import PortfolioSchema, PositionSchema, SnapshotSchema, TrancheSchema
from bitbot.api.state import bot_state

router = APIRouter()


@router.get("/portfolio", response_model=PortfolioSchema)
async def get_portfolio() -> PortfolioSchema:
    if bot_state.portfolio is None or bot_state.settings is None:
        raise HTTPException(status_code=503, detail="Bot not initialized")

    portfolio = bot_state.portfolio
    settings = bot_state.settings
    current_price = bot_state.current_price
    prices = {bot_state.symbol: current_price} if current_price else {}

    total_value = portfolio.get_total_value(prices)
    unrealized = portfolio.get_unrealized_pnl(prices)
    realized = portfolio.get_realized_pnl()
    initial = settings.capital.initial_usdt
    total_pnl = total_value - initial
    total_pnl_pct = (total_pnl / initial * 100) if initial else 0.0

    return PortfolioSchema(
        symbol=bot_state.symbol,
        mode=settings.exchange.mode,
        initial_capital=initial,
        total_value=total_value,
        cash=portfolio.cash,
        unrealized_pnl=unrealized,
        realized_pnl=realized,
        total_pnl=total_pnl,
        total_pnl_pct=total_pnl_pct,
        open_positions_count=len(portfolio.get_open_positions()),
        current_price=current_price,
    )


@router.get("/positions", response_model=list[PositionSchema])
async def get_positions() -> list[PositionSchema]:
    if bot_state.portfolio is None:
        raise HTTPException(status_code=503, detail="Bot not initialized")

    current_price = bot_state.current_price
    result: list[PositionSchema] = []

    for pos in bot_state.portfolio.get_open_positions():
        unrealized = pos.unrealized_pnl(current_price) if current_price else 0.0
        unrealized_pct = (unrealized / pos.total_cost * 100) if pos.total_cost else 0.0

        tranches = [
            TrancheSchema(
                price=t.price,
                quantity=t.quantity,
                fee=t.fee,
                timestamp=t.timestamp.isoformat(),
            )
            for t in pos.tranches
        ]

        result.append(
            PositionSchema(
                id=pos.id,
                symbol=pos.symbol,
                status=pos.status,
                entry_time=pos.entry_time.isoformat(),
                tranches=tranches,
                avg_entry_price=pos.avg_entry_price,
                total_quantity=pos.total_quantity,
                total_cost=pos.total_cost,
                total_fees=pos.total_fees,
                target_sell_price=pos.target_sell_price,
                stop_loss_price=pos.stop_loss_price,
                unrealized_pnl=unrealized,
                unrealized_pnl_pct=unrealized_pct,
                current_price=current_price,
            )
        )

    return result


@router.get("/snapshots", response_model=list[SnapshotSchema])
async def get_snapshots(
    hours: int = Query(default=24, ge=1, le=168),
) -> list[SnapshotSchema]:
    if bot_state.repo is None:
        raise HTTPException(status_code=503, detail="Bot not initialized")

    rows = await bot_state.repo.get_snapshots(bot_state.symbol, hours=hours)
    return [
        SnapshotSchema(
            timestamp=row["timestamp"],
            total_value=row["total_value"],
            available_capital=row["available_capital"],
            open_positions_count=row["open_positions_count"],
            unrealized_pnl=row["unrealized_pnl"],
            realized_pnl_cumulative=row["realized_pnl_cumulative"],
        )
        for row in rows
    ]
