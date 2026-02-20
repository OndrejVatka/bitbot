"""Shared in-memory state exposed from the bot loop to the API server.

The main loop populates this after initialization.
FastAPI routes read from it to serve live portfolio and risk data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from bitbot.config import Settings
from bitbot.database.repository import Repository
from bitbot.trading.portfolio import Portfolio
from bitbot.trading.risk_manager import RiskManager


@dataclass
class BotState:
    """Mutable state shared between the main bot loop and the API routes."""

    portfolio: Optional[Portfolio] = None
    risk: Optional[RiskManager] = None
    repo: Optional[Repository] = None
    settings: Optional[Settings] = None
    current_price: Optional[float] = None
    symbol: str = "BTCUSDT"
    is_running: bool = False


# Module-level singleton — populated by main.py on startup, read by API routes.
bot_state = BotState()
