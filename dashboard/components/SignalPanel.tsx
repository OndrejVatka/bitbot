import type { LiveSignal, Signal } from "@/types";

type SignalData = LiveSignal | Signal;

interface SignalPanelProps {
  /** The latest signal — either from WebSocket (LiveSignal) or REST (Signal). */
  signal: SignalData | null;
}

const SIGNAL_LABELS: Record<string, string> = {
  rsi: "RSI",
  ma_short: "MA Short",
  ma_long_trend: "MA Trend",
  bollinger: "Bollinger",
  volume: "Volume",
  dip_speed: "Dip Speed",
  dip_magnitude: "Dip Mag.",
};

const SENTIMENT_CONFIG: Record<
  string,
  { label: string; className: string; borderClass: string }
> = {
  temporary_pullback: {
    label: "Healthy Pullback",
    className: "bg-emerald-500/10 text-emerald-400",
    borderClass: "border-emerald-500/30",
  },
  deeper_correction: {
    label: "Deeper Correction",
    className: "bg-amber-500/10 text-amber-400",
    borderClass: "border-amber-500/30",
  },
  fundamental_shift: {
    label: "Fundamental Shift",
    className: "bg-red-500/10 text-red-400",
    borderClass: "border-red-500/30",
  },
};

function getScoreColor(score: number): string {
  if (score >= 85) return "text-amber-400";
  if (score >= 75) return "text-emerald-400";
  if (score >= 60) return "text-sky-400";
  return "text-zinc-500";
}

function getScoreLabel(score: number, action: string): string {
  if (action === "hold" || score < 60) return "HOLD";
  if (score >= 85) return "LARGE BUY";
  if (score >= 75) return "MEDIUM BUY";
  return "SMALL BUY";
}

function getScoreBadgeClass(score: number, action: string): string {
  if (action === "hold" || score < 60)
    return "border-zinc-700 bg-zinc-800 text-zinc-400";
  if (score >= 85)
    return "border-amber-500/40 bg-amber-500/10 text-amber-400";
  if (score >= 75)
    return "border-emerald-500/40 bg-emerald-500/10 text-emerald-400";
  return "border-sky-500/40 bg-sky-500/10 text-sky-400";
}

function SignalBar({ value }: { value: number }) {
  const clamped = Math.max(-1, Math.min(1, value));
  const pct = Math.abs(clamped) * 100;
  const positive = clamped >= 0;

  return (
    <div className="relative h-1.5 w-full overflow-hidden rounded-full bg-zinc-800">
      <div
        className={`h-full rounded-full transition-all duration-500 ${
          positive ? "bg-emerald-500" : "bg-red-500"
        }`}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

interface NormalizedSignal {
  score: number;
  action: string;
  signals: Record<string, number>;
  sentiment?: {
    classification: string;
    confidence: number;
    reasoning: string;
  } | null;
}

function normalizeSignal(s: SignalData): NormalizedSignal {
  if ("confidence_score" in s) {
    // REST Signal shape
    return {
      score: s.confidence_score,
      action: s.action_taken,
      signals: s.technical_signals,
      sentiment: s.sentiment_result ?? null,
    };
  }
  // LiveSignal shape
  return {
    score: s.score,
    action: s.action,
    signals: s.signals,
    sentiment: s.sentiment ?? null,
  };
}

export function SignalPanel({ signal }: SignalPanelProps) {
  if (!signal) {
    return (
      <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
        <h2 className="mb-4 text-xs font-medium uppercase tracking-wider text-zinc-500">
          Live Signal
        </h2>
        <div className="flex h-48 items-center justify-center text-sm text-zinc-600">
          Waiting for first candle close…
        </div>
      </div>
    );
  }

  const { score, action, signals, sentiment } = normalizeSignal(signal);
  const scoreColor = getScoreColor(score);
  const scoreLabel = getScoreLabel(score, action);
  const badgeClass = getScoreBadgeClass(score, action);

  const sentimentCfg = sentiment
    ? SENTIMENT_CONFIG[sentiment.classification] ?? null
    : null;

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-xs font-medium uppercase tracking-wider text-zinc-500">Live Signal</h2>
        <span className={`rounded border px-2 py-0.5 font-mono text-xs font-bold ${badgeClass}`}>
          {scoreLabel}
        </span>
      </div>

      {/* Score gauge */}
      <div className="mb-5 flex items-baseline gap-3">
        <span className={`font-mono text-5xl font-bold tabular-nums ${scoreColor}`}>{score}</span>
        <span className="text-lg text-zinc-600">/ 100</span>
      </div>

      {/* Score bar */}
      <div className="relative mb-5 h-2 overflow-hidden rounded-full bg-zinc-800">
        <div className="absolute inset-0 flex">
          <div className="w-[60%] border-r border-zinc-700" />
          <div className="w-[15%] border-r border-zinc-700" />
          <div className="w-[10%] border-r border-zinc-700" />
        </div>
        <div
          className={`h-full rounded-full transition-all duration-700 ${
            score >= 85
              ? "bg-amber-400"
              : score >= 75
              ? "bg-emerald-400"
              : score >= 60
              ? "bg-sky-400"
              : "bg-zinc-600"
          }`}
          style={{ width: `${score}%` }}
        />
      </div>

      {/* Individual signal bars */}
      <div className="space-y-2.5">
        {Object.entries(SIGNAL_LABELS).map(([key, label]) => {
          const value = signals[key] ?? signals[`${key}_signal`] ?? 0;
          return (
            <div key={key} className="flex items-center gap-3">
              <span className="w-20 shrink-0 font-mono text-xs text-zinc-500">{label}</span>
              <div className="min-w-0 flex-1">
                <SignalBar value={value} />
              </div>
              <span
                className={`w-10 shrink-0 text-right font-mono text-xs tabular-nums ${
                  value >= 0 ? "text-emerald-400" : "text-red-400"
                }`}
              >
                {value >= 0 ? "+" : ""}
                {value.toFixed(2)}
              </span>
            </div>
          );
        })}
      </div>

      {/* Sentiment section (only shown when LLM was triggered) */}
      {sentiment && sentimentCfg && (
        <div className={`mt-4 rounded-md border ${sentimentCfg.borderClass} bg-zinc-800/50 p-3`}>
          <div className="mb-1.5 flex items-center justify-between">
            <span className="text-xs font-medium uppercase tracking-wider text-zinc-500">
              AI Sentiment
            </span>
            <span
              className={`rounded px-1.5 py-0.5 font-mono text-xs font-bold ${sentimentCfg.className}`}
            >
              {sentimentCfg.label}
            </span>
          </div>

          {/* Confidence bar */}
          <div className="mb-2 flex items-center gap-2">
            <span className="font-mono text-xs text-zinc-500">Conf.</span>
            <div className="h-1 flex-1 overflow-hidden rounded-full bg-zinc-700">
              <div
                className={`h-full rounded-full ${sentimentCfg.className.includes("emerald") ? "bg-emerald-500" : sentimentCfg.className.includes("amber") ? "bg-amber-500" : "bg-red-500"}`}
                style={{ width: `${sentiment.confidence}%` }}
              />
            </div>
            <span className="font-mono text-xs tabular-nums text-zinc-400">
              {sentiment.confidence}%
            </span>
          </div>

          {/* Reasoning */}
          {sentiment.reasoning && (
            <p className="text-xs leading-relaxed text-zinc-400">
              {sentiment.reasoning}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
