import type { Trade } from "@/types";

interface TradesTableProps {
  trades: Trade[];
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

export function TradesTable({ trades }: TradesTableProps) {
  if (trades.length === 0) {
    return (
      <div className="flex h-32 items-center justify-center text-sm text-zinc-600">
        No trades yet
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full font-mono text-sm">
        <thead>
          <tr className="border-b border-zinc-800 text-left text-xs uppercase tracking-wider text-zinc-600">
            <th className="pb-2 pr-4">Time</th>
            <th className="pb-2 pr-4">Side</th>
            <th className="pb-2 pr-4">Price</th>
            <th className="pb-2 pr-4">Qty (BTC)</th>
            <th className="pb-2 pr-4">Fee</th>
            <th className="pb-2">Mode</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((trade) => (
            <tr
              key={trade.id}
              className="border-b border-zinc-800/50 text-zinc-300 transition-colors hover:bg-zinc-800/30"
            >
              <td className="py-2 pr-4 text-xs text-zinc-500">{formatTime(trade.timestamp)}</td>
              <td className="py-2 pr-4">
                <span
                  className={`rounded px-1.5 py-0.5 text-xs font-bold ${
                    trade.side === "buy"
                      ? "bg-emerald-500/10 text-emerald-400"
                      : "bg-red-500/10 text-red-400"
                  }`}
                >
                  {trade.side.toUpperCase()}
                </span>
              </td>
              <td className="py-2 pr-4 tabular-nums">
                ${trade.price.toLocaleString("en-US", { minimumFractionDigits: 2 })}
              </td>
              <td className="py-2 pr-4 tabular-nums">{trade.quantity.toFixed(6)}</td>
              <td className="py-2 pr-4 tabular-nums text-zinc-500">
                ${trade.fee.toFixed(4)}
              </td>
              <td className="py-2">
                <span className="rounded border border-zinc-700 px-1.5 py-0.5 text-xs text-zinc-500">
                  {trade.mode}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
