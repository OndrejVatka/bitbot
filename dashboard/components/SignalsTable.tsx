import type { Signal } from "@/types";

interface SignalsTableProps {
  signals: Signal[];
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

function ScoreBadge({ score, action }: { score: number; action: string }) {
  const isHold = action === "hold" || score < 60;
  const colorClass = isHold
    ? "bg-zinc-800 text-zinc-500"
    : score >= 85
    ? "bg-amber-500/10 text-amber-400"
    : score >= 75
    ? "bg-emerald-500/10 text-emerald-400"
    : "bg-sky-500/10 text-sky-400";

  return (
    <span className={`inline-block rounded px-1.5 py-0.5 font-mono text-xs font-bold ${colorClass}`}>
      {score}
    </span>
  );
}

export function SignalsTable({ signals }: SignalsTableProps) {
  if (signals.length === 0) {
    return (
      <div className="flex h-32 items-center justify-center text-sm text-zinc-600">
        No signals yet
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full font-mono text-sm">
        <thead>
          <tr className="border-b border-zinc-800 text-left text-xs uppercase tracking-wider text-zinc-600">
            <th className="pb-2 pr-4">Time</th>
            <th className="pb-2 pr-4">Score</th>
            <th className="pb-2 pr-4">Action</th>
            <th className="pb-2 pr-4">Price</th>
            <th className="pb-2">Top Signal</th>
          </tr>
        </thead>
        <tbody>
          {signals.map((sig) => {
            // Find the highest-valued signal for a quick insight
            const topSignal = Object.entries(sig.technical_signals).sort(
              ([, a], [, b]) => b - a
            )[0];

            return (
              <tr
                key={sig.id}
                className="border-b border-zinc-800/50 text-zinc-300 transition-colors hover:bg-zinc-800/30"
              >
                <td className="py-2 pr-4 text-xs text-zinc-500">{formatTime(sig.timestamp)}</td>
                <td className="py-2 pr-4">
                  <ScoreBadge score={sig.confidence_score} action={sig.action_taken} />
                </td>
                <td className="py-2 pr-4">
                  <span
                    className={
                      sig.action_taken === "buy" ? "text-emerald-400" : "text-zinc-500"
                    }
                  >
                    {sig.action_taken.toUpperCase()}
                  </span>
                </td>
                <td className="py-2 pr-4 tabular-nums">
                  ${sig.price_at_signal.toLocaleString("en-US", { minimumFractionDigits: 2 })}
                </td>
                <td className="py-2 text-xs text-zinc-500">
                  {topSignal ? (
                    <span>
                      {topSignal[0]}: <span className="text-emerald-400">+{topSignal[1].toFixed(2)}</span>
                    </span>
                  ) : (
                    "—"
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
