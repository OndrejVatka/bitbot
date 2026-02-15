"""Tests for database schema and repository."""

from datetime import datetime, timezone

import aiosqlite
import pytest

from bitbot.database.schema import initialize_database
from bitbot.database.repository import Candle, Repository


@pytest.fixture
async def db():
    """Create an in-memory database for testing."""
    conn = await initialize_database(":memory:")
    yield conn
    await conn.close()


@pytest.fixture
async def repo(db: aiosqlite.Connection):
    """Create a repository backed by the in-memory database."""
    return Repository(db)


class TestSchema:
    """Test database initialization."""

    async def test_creates_all_tables(self, db: aiosqlite.Connection) -> None:
        """All expected tables should exist after init."""
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [row[0] for row in await cursor.fetchall()]

        assert "trades" in tables
        assert "signals" in tables
        assert "portfolio_snapshots" in tables
        assert "risk_events" in tables
        assert "candles" in tables

    async def test_idempotent_init(self, db: aiosqlite.Connection) -> None:
        """Running schema twice should not error (IF NOT EXISTS)."""
        # The fixture already ran it once; run it again on same connection
        from bitbot.database.schema import SCHEMA_SQL

        await db.executescript(SCHEMA_SQL)
        await db.commit()


class TestCandleCache:
    """Test candle save/load round-trip."""

    async def test_save_and_load_candles(self, repo: Repository) -> None:
        """Candles should round-trip through the database."""
        candles = [
            Candle(
                timestamp=datetime(2025, 1, 1, i, 0, tzinfo=timezone.utc),
                open=100.0 + i,
                high=105.0 + i,
                low=95.0 + i,
                close=102.0 + i,
                volume=1000.0 * (i + 1),
            )
            for i in range(5)
        ]

        await repo.save_candles("BTCUSDT", "15m", candles)
        loaded = await repo.load_cached_candles("BTCUSDT", "15m", limit=10)

        assert len(loaded) == 5
        # Should be in chronological order (oldest first)
        assert loaded[0].timestamp < loaded[-1].timestamp
        assert loaded[0].open == 100.0
        assert loaded[4].close == 106.0

    async def test_upsert_overwrites(self, repo: Repository) -> None:
        """Saving candles with same timestamp should update, not duplicate."""
        ts = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
        candle_v1 = Candle(timestamp=ts, open=100, high=110, low=90, close=105, volume=1000)
        candle_v2 = Candle(timestamp=ts, open=100, high=115, low=88, close=108, volume=1500)

        await repo.save_candles("BTCUSDT", "15m", [candle_v1])
        await repo.save_candles("BTCUSDT", "15m", [candle_v2])

        loaded = await repo.load_cached_candles("BTCUSDT", "15m")
        assert len(loaded) == 1
        assert loaded[0].high == 115.0  # Updated value

    async def test_different_symbols_isolated(self, repo: Repository) -> None:
        """Candles for different symbols should not mix."""
        ts = datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc)
        btc = Candle(timestamp=ts, open=50000, high=51000, low=49000, close=50500, volume=100)
        eth = Candle(timestamp=ts, open=3000, high=3100, low=2900, close=3050, volume=200)

        await repo.save_candles("BTCUSDT", "15m", [btc])
        await repo.save_candles("ETHUSDT", "15m", [eth])

        btc_loaded = await repo.load_cached_candles("BTCUSDT", "15m")
        eth_loaded = await repo.load_cached_candles("ETHUSDT", "15m")

        assert len(btc_loaded) == 1
        assert len(eth_loaded) == 1
        assert btc_loaded[0].open == 50000
        assert eth_loaded[0].open == 3000


class TestSignalLogging:
    """Test signal logging and retrieval."""

    async def test_log_and_retrieve_signal(self, repo: Repository) -> None:
        """Should log a signal and retrieve it."""
        signal_id = await repo.log_signal(
            symbol="BTCUSDT",
            confidence_score=72,
            action_taken="buy",
            technical_signals={"rsi": 0.8, "bollinger": 0.5},
            price_at_signal=48500.0,
        )

        assert signal_id  # Non-empty UUID
        signals = await repo.get_recent_signals("BTCUSDT", limit=1)
        assert len(signals) == 1
        assert signals[0]["confidence_score"] == 72
        assert signals[0]["price_at_signal"] == 48500.0


class TestTradeLogging:
    """Test trade logging."""

    async def test_log_trade(self, repo: Repository) -> None:
        """Should log a trade without errors."""
        trade_id = await repo.log_trade(
            symbol="BTCUSDT",
            side="buy",
            price=48500.0,
            quantity=0.001,
            fee=0.048,
            position_id="pos-123",
            mode="paper",
            order_type="market",
        )

        assert trade_id  # Non-empty UUID


class TestRiskEvents:
    """Test risk event logging."""

    async def test_log_risk_event(self, repo: Repository) -> None:
        """Should log a risk event without errors."""
        event_id = await repo.log_risk_event(
            symbol="BTCUSDT",
            event_type="stop_loss",
            details={"position_id": "pos-123", "loss_pct": 5.2},
        )

        assert event_id
