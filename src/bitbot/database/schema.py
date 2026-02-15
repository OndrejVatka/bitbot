"""SQLite database schema and initialization."""

from pathlib import Path

import aiosqlite

SCHEMA_SQL = """
-- Every trade executed (real or paper)
CREATE TABLE IF NOT EXISTS trades (
    id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    side TEXT NOT NULL CHECK(side IN ('buy', 'sell')),
    price REAL NOT NULL,
    quantity REAL NOT NULL,
    fee REAL NOT NULL DEFAULT 0,
    position_id TEXT,
    mode TEXT NOT NULL CHECK(mode IN ('paper', 'live')),
    order_type TEXT NOT NULL CHECK(order_type IN ('market', 'limit')),
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Every scoring decision
CREATE TABLE IF NOT EXISTS signals (
    id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    confidence_score INTEGER NOT NULL,
    action_taken TEXT,
    technical_signals TEXT NOT NULL,
    sentiment_result TEXT,
    price_at_signal REAL NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Portfolio snapshots (periodic)
CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    total_value REAL NOT NULL,
    available_capital REAL NOT NULL,
    open_positions_count INTEGER NOT NULL,
    unrealized_pnl REAL NOT NULL,
    realized_pnl_cumulative REAL NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Risk events
CREATE TABLE IF NOT EXISTS risk_events (
    id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    event_type TEXT NOT NULL,
    details TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Candle data cache (warm-up + backtesting)
CREATE TABLE IF NOT EXISTS candles (
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL NOT NULL,
    PRIMARY KEY (symbol, timeframe, timestamp)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);
CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(timestamp);
CREATE INDEX IF NOT EXISTS idx_signals_symbol ON signals(symbol);
CREATE INDEX IF NOT EXISTS idx_signals_timestamp ON signals(timestamp);
CREATE INDEX IF NOT EXISTS idx_candles_lookup ON candles(symbol, timeframe, timestamp);
"""


async def initialize_database(db_path: str) -> aiosqlite.Connection:
    """Create database file and ensure schema exists.

    Args:
        db_path: Path to SQLite file (e.g., 'data/bitbot.db').

    Returns:
        Open aiosqlite connection ready for use.
    """
    # Ensure parent directory exists
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    db = await aiosqlite.connect(db_path)
    db.row_factory = aiosqlite.Row
    await db.executescript(SCHEMA_SQL)
    await db.commit()
    return db
