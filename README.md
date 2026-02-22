# BitBot

Automated Bitcoin dip-buying agent that combines technical analysis with an LLM sentiment layer to identify buying opportunities during price pullbacks.

## Overview

BitBot monitors BTC/USDT price movements in real-time via Binance WebSocket, calculates a multi-signal confidence score, and executes micro-trades in paper or live mode. It uses Claude as a sentiment analysis layer to filter out dangerous dips (crashes, fundamental shifts) from healthy pullbacks.

The system includes a full backtesting engine for strategy validation and a real-time Next.js dashboard for monitoring.

## Architecture

```
Binance WebSocket ──> Price Feed ──> Technical Signals ──> Scorer ──> Executor
                                          |                  |
                                     RSI, MA, BB,      Claude API
                                     Volume, Dip       (sentiment)
                                                          |
                                                    Risk Manager
                                                     (stop-loss,
                                                      drawdown,
                                                      cooldowns)
```

**Signal Engine** — 7 normalized indicators: RSI, short/long MA, Bollinger Bands, volume analysis, dip magnitude, dip speed

**Confidence Scorer** — Combines signals into a 0-100 score with configurable buy thresholds and position sizing tiers

**Risk Manager** — Stop-losses, daily loss halts, max drawdown protection, cooldown periods, LLM sentiment blocks

**Backtesting** — Replays historical candles through the same pipeline with performance metrics, parameter optimization, and stress testing across known crash periods

## Quick Start

```bash
# Clone and setup
git clone https://github.com/OndrejVatka/bitbot.git
cd bitbot
python3 -m venv .venv && source .venv/bin/activate
pip install -e .

# Configure
cp .env.example .env
# Edit .env with your Binance and Anthropic API keys

# Run (paper trading mode)
bitbot
```

The API server starts automatically on port 8000 with Swagger docs at `/docs`.

## Docker Deployment

```bash
cp .env.example .env
# Edit .env with your API keys
mkdir -p data/logs
docker compose up -d --build
```

This starts the bot, dashboard, and nginx reverse proxy. Access the dashboard at `http://localhost`.

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `BINANCE_API_KEY` | Yes | Binance API key (read + spot trading) |
| `BINANCE_API_SECRET` | Yes | Binance API secret |
| `ANTHROPIC_API_KEY` | Yes | Anthropic Claude API key |
| `CRYPTOPANIC_API_KEY` | No | CryptoPanic API key for news headlines |

## Configuration

Strategy parameters are in `config/settings.yaml`. Key settings:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `scoring.buy_threshold` | 30 | Minimum confidence score to buy |
| `risk.stop_loss_pct` | 3.0 | Stop-loss percentage per position |
| `selling.profit_target_pct` | 5.0 | Take-profit percentage |
| `risk.max_daily_loss_pct` | 3.0 | Daily loss halt threshold |
| `risk.max_drawdown_pct` | 10.0 | Max drawdown before halting |
| `dca.tranches` | 1 | Buy tranches per signal |
| `capital.initial_usdt` | 1000.0 | Starting paper trading capital |

## Backtesting

```bash
pip install -e ".[backtest]"

# Run a backtest
bitbot-backtest run --start 2024-01-01 --end 2024-06-30 --threshold 40 --save-charts output/

# Optimize parameters
bitbot-backtest optimize --start 2024-01-01 --end 2024-12-31 --walk-forward

# Stress test across historical crashes
bitbot-backtest stress
```

## Project Structure

```
src/bitbot/
  main.py                 # Entry point, orchestration loop
  config.py               # Pydantic settings (YAML + .env)
  market_data/            # Binance WebSocket + historical fetcher
  signals/                # Technical indicators, LLM sentiment, scorer
  trading/                # Portfolio tracker, risk manager, executor
  paper_trading/          # Simulated order execution
  backtesting/            # Backtest engine, metrics, optimizer, stress tests
  database/               # SQLite schema + repository
  api/                    # FastAPI server + WebSocket broadcaster
dashboard/                # Next.js real-time monitoring UI
tests/                    # pytest suite (118 tests)
```

## Dashboard

Real-time monitoring dashboard built with Next.js, TanStack Query, and Recharts. Shows portfolio value, open positions, trade history, signals, and risk status via WebSocket.

For local development:

```bash
cd dashboard
npm install
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
```

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/health` | Bot status and mode |
| `GET /api/portfolio` | Portfolio value, cash, P&L |
| `GET /api/positions` | Open positions |
| `GET /api/trades` | Trade history |
| `GET /api/signals` | Signal/scoring history |
| `GET /api/risk` | Risk status (halts, drawdown, cooldowns) |
| `WS /ws` | Live event stream (signals, trades, prices) |

## Testing

```bash
pip install -e ".[dev]"
pytest
```

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Runtime | Python 3.12+, asyncio |
| Exchange | Binance API (python-binance) |
| Technical Analysis | pandas, pandas-ta |
| LLM | Anthropic Claude API |
| Database | SQLite (aiosqlite) |
| API | FastAPI, uvicorn |
| Dashboard | Next.js 15, React 19, Recharts, Tailwind CSS |
| Deployment | Docker Compose, nginx |

## Disclaimer

This software is for educational and research purposes. Cryptocurrency trading involves significant risk. Always start with paper trading and never risk more than you can afford to lose. Past backtest performance does not guarantee future results.
