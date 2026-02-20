"""Pydantic response schemas for all BitBot API endpoints."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class TrancheSchema(BaseModel):
    price: float
    quantity: float
    fee: float
    timestamp: str


class PositionSchema(BaseModel):
    id: str
    symbol: str
    status: str
    entry_time: str
    tranches: list[TrancheSchema]
    avg_entry_price: float
    total_quantity: float
    total_cost: float
    total_fees: float
    target_sell_price: float
    stop_loss_price: float
    unrealized_pnl: float
    unrealized_pnl_pct: float
    current_price: Optional[float]


class PortfolioSchema(BaseModel):
    symbol: str
    mode: str
    initial_capital: float
    total_value: float
    cash: float
    unrealized_pnl: float
    realized_pnl: float
    total_pnl: float
    total_pnl_pct: float
    open_positions_count: int
    current_price: Optional[float]


class TradeSchema(BaseModel):
    id: str
    symbol: str
    timestamp: str
    side: str
    price: float
    quantity: float
    fee: float
    position_id: Optional[str]
    mode: str
    order_type: str


class SignalSchema(BaseModel):
    id: str
    symbol: str
    timestamp: str
    confidence_score: int
    action_taken: str
    price_at_signal: float
    technical_signals: dict[str, float]
    sentiment_result: Optional[dict[str, object]] = None


class SnapshotSchema(BaseModel):
    timestamp: str
    total_value: float
    available_capital: float
    open_positions_count: int
    unrealized_pnl: float
    realized_pnl_cumulative: float


class RiskSchema(BaseModel):
    is_halted: bool
    halt_reason: Optional[str]
    peak_value: float
    current_value: Optional[float]
    drawdown_pct: float
    daily_start_value: float
    daily_pnl_pct: float
    cooldown_active: bool
    cooldown_remaining_seconds: int
    sentiment_block_active: bool
    sentiment_block_remaining_seconds: int


class ConfigSchema(BaseModel):
    symbol: str
    mode: str
    initial_capital: float
    buy_threshold: int
    small_buy_range: list[int]
    medium_buy_range: list[int]
    large_buy_range: list[int]
    small_buy_pct: float
    medium_buy_pct: float
    large_buy_pct: float
    profit_target_pct: float
    stop_loss_pct: float
    max_daily_loss_pct: float
    max_drawdown_pct: float
    dca_tranches: int
    min_interval_minutes: int
    max_interval_minutes: int
    primary_timeframe: str
    trend_timeframe: str


class HealthSchema(BaseModel):
    status: str
    bot_running: bool
    symbol: str
    mode: str


class RiskEventSchema(BaseModel):
    id: str
    symbol: str
    timestamp: str
    event_type: str
    details: dict[str, object]
