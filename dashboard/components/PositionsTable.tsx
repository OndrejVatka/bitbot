import type { Position } from "@/types";

interface PositionsTableProps {
  positions: Position[];
}

function fmt(n: number, decimals = 2): string {
  return n.toLocaleString("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

function PnlBadge({ value, pct }: { value: number; pct: number }) {
  const positive = value >= 0;
  return (
    <div className={`font-mono tabular-nums ${positive ? "text-emerald-400" : "text-red-400"}`}>
      <div>
        {positive ? "+" : ""}${fmt(value)}
      </div>
      <div className="text-xs opacity-75">
        ({positive ? "+" : ""}
        {fmt(pct, 2)}%)
      </div>
    </div>
  );
}

export function PositionsTable({ positions }: PositionsTableProps) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
      <h2 className="mb-4 text-xs font-medium uppercase tracking-wider text-zinc-500">
        Open Positions ({positions.length})
      </h2>

      {positions.length === 0 ? (
        <div className="flex h-48 items-center justify-center text-sm text-zinc-600">
          No open positions
        </div>
      ) : (
        <div className="space-y-3 overflow-y-auto" style={{ maxHeight: "340px" }}>
          {positions.map((pos) => (
            <div
              key={pos.id}
              className="rounded-md border border-zinc-700/50 bg-zinc-800/50 p-3"
            >
              {/* Header row */}
              <div className="mb-2 flex items-center justify-between">
                <div>
                  <span className="font-mono text-sm font-bold text-zinc-100">{pos.symbol}</span>
                  <span className="ml-2 font-mono text-xs text-zinc-500">
                    {pos.total_quantity.toFixed(6)} BTC
                  </span>
                </div>
                <PnlBadge value={pos.unrealized_pnl} pct={pos.unrealized_pnl_pct} />
              </div>

              {/* Details grid */}
              <div className="grid grid-cols-2 gap-x-4 gap-y-1 font-mono text-xs">
                <div className="flex justify-between">
                  <span className="text-zinc-600">Avg Entry</span>
                  <span className="text-zinc-300">${fmt(pos.avg_entry_price)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-zinc-600">Tranches</span>
                  <span className="text-zinc-300">{pos.tranches.length}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-zinc-600">Stop Loss</span>
                  <span className="text-red-400">${fmt(pos.stop_loss_price)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-zinc-600">Target</span>
                  <span className="text-emerald-400">${fmt(pos.target_sell_price)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-zinc-600">Cost</span>
                  <span className="text-zinc-300">${fmt(pos.total_cost)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-zinc-600">Fees</span>
                  <span className="text-zinc-400">${fmt(pos.total_fees, 4)}</span>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
