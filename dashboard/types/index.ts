export interface Portfolio {
  symbol: string;
  mode: "paper" | "live";
  initial_capital: number;
  total_value: number;
  cash: number;
  unrealized_pnl: number;
  realized_pnl: number;
  total_pnl: number;
  total_pnl_pct: number;
  open_positions_count: number;
  current_price: number | null;
}

export interface Tranche {
  price: number;
  quantity: number;
  fee: number;
  timestamp: string;
}

export interface Position {
  id: string;
  symbol: string;
  status: string;
  entry_time: string;
  tranches: Tranche[];
  avg_entry_price: number;
  total_quantity: number;
  total_cost: number;
  total_fees: number;
  target_sell_price: number;
  stop_loss_price: number;
  unrealized_pnl: number;
  unrealized_pnl_pct: number;
  current_price: number | null;
}

export interface Trade {
  id: string;
  symbol: string;
  timestamp: string;
  side: "buy" | "sell";
  price: number;
  quantity: number;
  fee: number;
  position_id: string | null;
  mode: string;
  order_type: string;
}

export interface Signal {
  id: string;
  symbol: string;
  timestamp: string;
  confidence_score: number;
  action_taken: string;
  price_at_signal: number;
  technical_signals: Record<string, number>;
  sentiment_result?: {
    classification: "temporary_pullback" | "deeper_correction" | "fundamental_shift";
    confidence: number;
    reasoning: string;
    recommended_action: string;
  } | null;
}

export interface Snapshot {
  timestamp: string;
  total_value: number;
  available_capital: number;
  open_positions_count: number;
  unrealized_pnl: number;
  realized_pnl_cumulative: number;
}

export interface Risk {
  is_halted: boolean;
  halt_reason: string | null;
  peak_value: number;
  current_value: number | null;
  drawdown_pct: number;
  daily_start_value: number;
  daily_pnl_pct: number;
  cooldown_active: boolean;
  cooldown_remaining_seconds: number;
  sentiment_block_active: boolean;
  sentiment_block_remaining_seconds: number;
}

export interface Config {
  symbol: string;
  mode: string;
  initial_capital: number;
  buy_threshold: number;
  small_buy_range: number[];
  medium_buy_range: number[];
  large_buy_range: number[];
  small_buy_pct: number;
  medium_buy_pct: number;
  large_buy_pct: number;
  profit_target_pct: number;
  stop_loss_pct: number;
  max_daily_loss_pct: number;
  max_drawdown_pct: number;
  dca_tranches: number;
  min_interval_minutes: number;
  max_interval_minutes: number;
  primary_timeframe: string;
  trend_timeframe: string;
}

export interface RiskEvent {
  id: string;
  symbol: string;
  timestamp: string;
  event_type: string;
  details: Record<string, unknown>;
}

/** Shape of a live signal event pushed over WebSocket. */
export interface LiveSignal {
  score: number;
  action: string;
  price: number;
  signals: Record<string, number>;
  reasoning: string;
  timestamp: string;
  sentiment?: {
    classification: "temporary_pullback" | "deeper_correction" | "fundamental_shift";
    confidence: number;
    reasoning: string;
    recommended_action: string;
  } | null;
}

export interface WSMessage {
  type: "signal" | "trade" | "price" | "snapshot" | "risk_event";
  data: Record<string, unknown>;
}
