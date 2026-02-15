# Crypto Dip-Buying Trading Agent — Technical Specification

## Project Overview

Build an automated crypto trading agent that monitors Bitcoin price movements, identifies buying opportunities during price dips using a multi-layered signal system, and executes micro-transactions to accumulate and compound profits over time.

The agent connects to Binance via API, uses technical indicators for dip detection, and integrates Claude's API as a sentiment analysis layer to filter out dangerous dips (crashes, fundamental shifts) from healthy pullbacks.

### Core Philosophy

- **Micro-transactions over big bets** — spread risk across many small trades
- **Confidence-scored decisions** — never act on a single signal
- **Paper trading first** — prove the strategy before risking real capital
- **Log everything** — every decision, every signal, every trade for analysis

---

## Tech Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Runtime | Python 3.12+ | Main application |
| Exchange API | Binance API (python-binance) | Market data + order execution |
| Real-time data | Binance WebSocket | Live price feeds |
| Technical analysis | pandas + ta-lib (or pandas-ta) | Indicator calculations |
| LLM integration | Anthropic Claude API (claude-sonnet-4-20250514) | Sentiment analysis layer |
| Database | SQLite (start simple) | Trade log, signal history, P&L tracking |
| Scheduling | APScheduler or asyncio loops | Periodic checks and analysis |
| Config | YAML or .env | API keys, strategy parameters |
| Logging | Python logging + structured JSON logs | Full audit trail |

---

## Project Structure

```
crypto-agent/
├── config/
│   ├── settings.yaml          # Strategy parameters, thresholds
│   └── .env                   # API keys (Binance, Anthropic) — NEVER commit
├── src/
│   ├── main.py                # Entry point, orchestrator
│   ├── market_data/
│   │   ├── price_feed.py      # WebSocket connection, real-time prices
│   │   └── historical.py      # Fetch historical candles for indicators
│   ├── signals/
│   │   ├── technical.py       # Price, MA, Bollinger, RSI, Volume signals
│   │   ├── sentiment.py       # Claude API sentiment analysis
│   │   └── scorer.py          # Combine signals into confidence score
│   ├── trading/
│   │   ├── executor.py        # Order placement (market/limit orders)
│   │   ├── portfolio.py       # Track positions, balance, P&L
│   │   └── risk_manager.py    # Stop-losses, position limits, drawdown
│   ├── paper_trading/
│   │   └── simulator.py       # Simulated order execution (no real money)
│   └── database/
│       ├── models.py          # SQLite schemas
│       └── logger.py          # Trade and decision logging
├── backtesting/
│   ├── backtest_runner.py     # Run strategy against historical data
│   └── analysis.py            # Performance metrics, charts
├── tests/
│   └── ...                    # Unit tests for signals, scorer, risk manager
├── requirements.txt
└── README.md
```

---

## Module Specifications

### 1. Market Data Module (`src/market_data/`)

#### `price_feed.py` — Real-Time Price Stream

- Connect to Binance WebSocket for BTC/USDT pair
- Stream kline/candlestick data at 1-minute intervals
- Maintain a rolling in-memory buffer of the last 200+ candles (needed for indicator calculation)
- Emit events/callbacks when new candle closes
- Handle reconnection on disconnect gracefully

```python
# Key interface
class PriceFeed:
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    def get_current_price(self) -> float: ...
    def get_candles(self, period: int = 200) -> pd.DataFrame: ...
    def on_candle_close(self, callback: Callable) -> None: ...
```

#### `historical.py` — Historical Data Fetcher

- Fetch historical klines from Binance REST API
- Used for backtesting and initial indicator warm-up
- Support multiple timeframes (1m, 5m, 15m, 1h, 4h, 1d)

---

### 2. Signal Engine (`src/signals/`)

#### `technical.py` — Technical Indicator Signals

Calculate the following indicators and return normalized signal values:

**a) Percentage Drop from Recent High**
- Track rolling 24h and 7d high
- Calculate current drop percentage from each
- Signal strength: 3-5% = mild, 5-10% = moderate, 10%+ = major

**b) Moving Average Analysis**
- Calculate 20-period and 200-period Simple Moving Averages
- Signal: Price below 20-MA but above 200-MA = bullish dip
- Signal: Price below both = potential bear market (caution)

**c) Bollinger Bands (20-period, 2 std dev)**
- Signal: Price at or below lower band = oversold
- Stronger signal the further below the band

**d) RSI (14-period)**
- RSI < 30 = oversold (buy signal)
- RSI < 20 = extremely oversold (stronger signal)
- RSI > 70 = overbought (potential sell signal)

**e) Volume Analysis**
- Compare current volume to 20-period average volume
- Declining volume during price drop = healthy dip (buy)
- Spiking volume during price drop = panic selling (avoid)

**f) Rate of Price Change**
- Measure speed of decline (price change per hour)
- Gradual decline = safer to buy
- Flash crash (>3% in <30 min) = wait for stabilization

```python
# Key interface
class TechnicalSignals:
    def analyze(self, candles: pd.DataFrame) -> dict:
        """Returns dict of signal names -> signal values (-1 to +1)"""
        ...
```

#### `sentiment.py` — LLM Sentiment Layer

- Triggered when technical signals suggest a potential dip (score > 40)
- Calls Claude API with structured prompt including:
  - Current price action summary (last 24h)
  - Key technical indicator readings
  - Recent BTC-related news headlines (fetched via news API or web search)
  - Current Fear & Greed Index value
- Claude responds with structured assessment:
  - Classification: "temporary_pullback" | "deeper_correction" | "fundamental_shift"
  - Confidence: 0-100
  - Key reasoning (logged for audit)

```python
# Prompt template for Claude
SENTIMENT_PROMPT = """
You are a crypto market analyst. Assess the current Bitcoin price action.

CURRENT MARKET DATA:
- BTC Price: ${current_price} (24h change: {pct_change_24h}%)
- RSI (14): {rsi_value}
- Volume trend: {volume_trend}
- Price vs 200-MA: {price_vs_200ma}
- Fear & Greed Index: {fear_greed_value}/100

RECENT NEWS HEADLINES:
{news_headlines}

Based on this data, classify the current price movement:

Respond in JSON format only:
{
  "classification": "temporary_pullback" | "deeper_correction" | "fundamental_shift",
  "confidence": <0-100>,
  "reasoning": "<brief explanation>",
  "recommended_action": "buy" | "wait" | "avoid"
}
"""
```

#### `scorer.py` — Confidence Score Calculator

Combine all signals into a single actionable confidence score:

```
CONFIDENCE SCORE CALCULATION (0-100):

Technical Signals (max 75 points):
  Price below 20-day MA               → +15
  Price near/below lower Bollinger    → +15
  RSI below 30                        → +20
  Volume declining during drop        → +15
  Drop speed is gradual               → +10

LLM Sentiment Adjustment:
  "temporary_pullback" (high conf)    → +25
  "temporary_pullback" (low conf)     → +10
  "deeper_correction"                 → -20
  "fundamental_shift"                 → -40

ACTION THRESHOLDS:
  Score 60-74  → Small buy   (5% of available capital)
  Score 75-84  → Medium buy  (10% of available capital)
  Score 85+    → Large buy   (15-20% of available capital)
  Score < 60   → No action
```

```python
# Key interface
class SignalScorer:
    def calculate_score(
        self,
        technical_signals: dict,
        sentiment_result: dict | None
    ) -> ScoringResult: ...

@dataclass
class ScoringResult:
    score: int                    # 0-100
    action: str                   # "buy", "sell", "hold"
    position_size_pct: float      # % of available capital
    signals_breakdown: dict       # individual signal contributions
    reasoning: str                # human-readable explanation
```

---

### 3. Trading Module (`src/trading/`)

#### `executor.py` — Order Execution

- Place orders via Binance REST API
- Support both MARKET and LIMIT orders
- For buys: use limit orders slightly above current price for better fills
- For sells: use limit orders with configurable profit target
- Handle partial fills gracefully
- Implement retry logic with exponential backoff

**Buy Logic (DCA into dips):**
- When dip detected, don't buy all at once
- Split into 3-5 tranches over configurable time window (e.g., 1h)
- If price reverses up after first tranche → good, caught it early
- If price keeps dropping → average down at better prices
- Cancel remaining tranches if stop-loss hit

**Sell Logic:**
- Set profit target per position (configurable, default 2-3% above avg entry)
- Trailing stop-loss: if price rises past target, trail by 1%
- Time-based exit: if position hasn't hit target in X days, reassess

#### `portfolio.py` — Portfolio Tracker

- Track all open positions with entry prices
- Calculate real-time unrealized P&L
- Track realized P&L (completed trades)
- Account for fees (0.1% maker/taker on Binance)
- Calculate total portfolio value at any point
- Generate performance reports

```python
@dataclass
class Position:
    id: str
    entry_price: float
    quantity: float
    entry_time: datetime
    tranches: list[Tranche]       # DCA entries
    avg_entry_price: float        # weighted average
    target_sell_price: float
    stop_loss_price: float
    status: str                   # "open", "partial", "closed"

class Portfolio:
    def get_available_capital(self) -> float: ...
    def get_total_value(self) -> float: ...
    def get_open_positions(self) -> list[Position]: ...
    def get_realized_pnl(self) -> float: ...
    def get_unrealized_pnl(self) -> float: ...
```

#### `risk_manager.py` — Risk Management (CRITICAL MODULE)

This is the most important module. Without proper risk management, the agent will eventually blow up.

**Rules to enforce:**
- **Max position size**: Never allocate more than 20% of total capital to a single trade
- **Max total exposure**: Never have more than 70% of capital in open positions (keep 30% as reserve)
- **Stop-loss per position**: Auto-sell if position drops 5% below average entry (configurable)
- **Max daily loss**: If total portfolio drops more than 3% in a day, halt all trading for 24h
- **Max drawdown**: If portfolio drops more than 10% from peak, halt trading and alert user
- **Minimum trade size**: Respect Binance minimums (currently ~$10 for BTC/USDT)
- **Cooldown period**: After a stop-loss is triggered, wait minimum 4h before next buy
- **LLM override**: If Claude flags "fundamental_shift", block all buys for configurable period

```python
class RiskManager:
    def can_open_position(self, size_usdt: float) -> tuple[bool, str]: ...
    def check_stop_losses(self, positions: list[Position]) -> list[str]: ...
    def is_trading_halted(self) -> tuple[bool, str]: ...
    def daily_loss_check(self) -> bool: ...
    def max_drawdown_check(self) -> bool: ...
```

---

### 4. Paper Trading Module (`src/paper_trading/`)

#### `simulator.py` — Simulated Trading

- Mirrors the real executor interface exactly
- Uses real-time price data but executes fake orders
- Simulates:
  - Order fills at market price + estimated slippage (0.05%)
  - Trading fees (0.1% per side)
  - Partial fills on limit orders
- Logs everything identically to real trading
- Produces same performance reports

**This module must be used first. Do not connect to real trading until paper trading shows consistent profitability over at least 2-4 weeks across different market conditions.**

---

### 5. Database & Logging (`src/database/`)

#### SQLite Tables

```sql
-- Every trade executed (real or paper)
CREATE TABLE trades (
    id TEXT PRIMARY KEY,
    timestamp DATETIME,
    side TEXT,              -- 'buy' or 'sell'
    price FLOAT,
    quantity FLOAT,
    fee FLOAT,
    position_id TEXT,
    mode TEXT,              -- 'paper' or 'live'
    order_type TEXT         -- 'market' or 'limit'
);

-- Every scoring decision
CREATE TABLE signals (
    id TEXT PRIMARY KEY,
    timestamp DATETIME,
    confidence_score INT,
    action_taken TEXT,
    technical_signals JSON, -- full breakdown
    sentiment_result JSON,  -- Claude's response
    price_at_signal FLOAT
);

-- Portfolio snapshots (hourly)
CREATE TABLE portfolio_snapshots (
    timestamp DATETIME PRIMARY KEY,
    total_value FLOAT,
    available_capital FLOAT,
    open_positions_count INT,
    unrealized_pnl FLOAT,
    realized_pnl_cumulative FLOAT
);

-- Risk events
CREATE TABLE risk_events (
    id TEXT PRIMARY KEY,
    timestamp DATETIME,
    event_type TEXT,        -- 'stop_loss', 'halt', 'max_drawdown'
    details JSON
);
```

---

### 6. Configuration (`config/settings.yaml`)

```yaml
# Exchange
exchange:
  name: binance
  trading_pair: BTCUSDT
  mode: paper                     # 'paper' or 'live'

# Strategy Parameters
strategy:
  check_interval_seconds: 60      # How often to evaluate signals
  candle_timeframe: 5m            # Primary candle timeframe
  indicator_period: 200           # Candles to keep in buffer

# Signal Thresholds
signals:
  dip_mild_pct: 3.0
  dip_moderate_pct: 5.0
  dip_major_pct: 10.0
  rsi_oversold: 30
  rsi_extremely_oversold: 20
  volume_decline_threshold: 0.8   # Below 80% of avg = declining

# Scoring
scoring:
  buy_threshold: 60
  small_buy_range: [60, 74]
  medium_buy_range: [75, 84]
  large_buy_range: [85, 100]
  small_buy_pct: 0.05             # 5% of available capital
  medium_buy_pct: 0.10            # 10%
  large_buy_pct: 0.20             # 20%

# DCA Settings
dca:
  tranches: 3                     # Split buy into 3 parts
  tranche_interval_minutes: 20    # 20 min between tranches

# Sell Targets
selling:
  profit_target_pct: 2.5          # Sell when 2.5% above avg entry
  trailing_stop_pct: 1.0          # Trail by 1% once target hit
  time_exit_days: 7               # Reassess after 7 days

# Risk Management
risk:
  max_position_pct: 0.20          # Max 20% per position
  max_total_exposure_pct: 0.70    # Max 70% in open positions
  stop_loss_pct: 5.0              # Stop-loss at 5% below entry
  max_daily_loss_pct: 3.0         # Halt if 3% daily loss
  max_drawdown_pct: 10.0          # Halt if 10% from peak
  cooldown_after_stoploss_hours: 4
  sentiment_block_hours: 12       # Block buys after "fundamental_shift"

# LLM Settings
llm:
  provider: anthropic
  model: claude-sonnet-4-20250514
  trigger_threshold: 40           # Only call LLM if tech score > 40
  max_calls_per_hour: 10          # Rate limit to manage costs

# Fees
fees:
  maker_pct: 0.10
  taker_pct: 0.10
  estimated_slippage_pct: 0.05

# Initial Capital
capital:
  initial_usdt: 1000.0            # Starting budget
```

---

## Main Loop Logic (`src/main.py`)

```
INITIALIZATION:
1. Load config
2. Connect to Binance WebSocket (price feed)
3. Warm up indicators with historical data (200+ candles)
4. Initialize portfolio tracker with initial capital
5. Start main evaluation loop

MAIN LOOP (every check_interval):
1. Get latest candle data
2. Calculate all technical signals
3. Calculate preliminary confidence score (technical only)

4. IF preliminary score > 40:
   a. Fetch news headlines / Fear & Greed Index
   b. Call Claude API for sentiment analysis
   c. Recalculate final confidence score with sentiment

5. IF final score >= buy_threshold:
   a. Check risk manager → can we open a new position?
   b. Calculate position size based on score tier
   c. Execute buy (DCA tranches via executor)
   d. Log signal + trade to database

6. CHECK OPEN POSITIONS:
   a. For each open position:
      - Has profit target been reached? → Execute sell
      - Has trailing stop been triggered? → Execute sell
      - Has stop-loss been hit? → Execute sell
      - Has time limit expired? → Reassess (call Claude?)
   b. Log any sells

7. RISK CHECKS:
   a. Check daily P&L → halt if threshold breached
   b. Check max drawdown → halt if threshold breached
   c. Update portfolio snapshot

8. REPEAT
```

---

## Implementation Order (Suggested Phases)

### Phase 1: Foundation (Week 1)
- [ ] Project scaffolding and config setup
- [ ] Binance WebSocket price feed connection
- [ ] Historical data fetcher
- [ ] SQLite database schemas and logging
- [ ] Basic technical indicator calculations (RSI, MA, Bollinger)

### Phase 2: Signal Engine (Week 2)
- [ ] Full technical signal module with all indicators
- [ ] Confidence scorer (technical signals only, no LLM yet)
- [ ] Paper trading simulator
- [ ] Basic buy/sell logic with paper executor

### Phase 3: Risk Management (Week 3)
- [ ] Complete risk manager implementation
- [ ] Stop-loss monitoring
- [ ] Position sizing and DCA logic
- [ ] Portfolio tracker with P&L calculations

### Phase 4: LLM Integration (Week 4)
- [ ] Claude API integration for sentiment analysis
- [ ] News headline fetching (API or web scraping)
- [ ] Fear & Greed Index integration
- [ ] Combined scoring (technical + sentiment)

### Phase 5: Backtesting & Optimization (Week 5-6)
- [ ] Backtest runner against historical BTC data
- [ ] Performance analysis and visualization
- [ ] Parameter optimization
- [ ] Stress testing against known crash periods (May 2021, Nov 2022, etc.)

### Phase 6: Live Trading (After Successful Paper Trading)
- [ ] Switch executor from paper to live Binance API
- [ ] Start with minimal capital ($100-200)
- [ ] Monitor closely for first 2 weeks
- [ ] Gradual capital increase if profitable

---

## Important Notes

- **Security**: Store API keys in `.env` file, NEVER commit to git. Use Binance API key restrictions (IP whitelist, no withdrawal permission).
- **Rate limits**: Binance allows 1200 requests/minute for REST API. WebSocket has no rate limit for receiving data.
- **Minimum order size**: Binance BTC/USDT minimum is approximately $10 notional value.
- **Anthropic API costs**: Claude Sonnet costs roughly $3 per million input tokens and $15 per million output tokens. With 10 calls/hour max, daily cost should stay under $1-2.
- **Tax implications**: Every trade is a taxable event in most jurisdictions. The trade log database is essential for tax reporting.

---

## Success Metrics

Track these to evaluate the strategy:

- **Win rate**: % of positions closed in profit (target: >60%)
- **Average gain vs average loss**: Gain should be > 1.5x loss
- **Sharpe ratio**: Risk-adjusted return (target: >1.5)
- **Max drawdown**: Largest peak-to-trough decline (target: <10%)
- **Comparison vs buy-and-hold**: Is the agent beating simple holding?
- **Total fees paid**: Keep this as low as possible relative to gains
