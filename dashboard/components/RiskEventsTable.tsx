import type { RiskEvent } from "@/types";

interface RiskEventsTableProps {
  events: RiskEvent[];
}

const EVENT_CONFIG: Record<string, { label: string; className: string }> = {
  stop_loss: { label: "Stop Loss", className: "bg-red-500/10 text-red-400" },
  profit_target: { label: "Profit Target", className: "bg-emerald-500/10 text-emerald-400" },
  daily_loss_halt: { label: "Daily Loss Halt", className: "bg-amber-500/10 text-amber-400" },
  drawdown_halt: { label: "Drawdown Halt", className: "bg-amber-500/10 text-amber-400" },
};

function EventBadge({ type }: { type: string }) {
  const cfg = EVENT_CONFIG[type] ?? {
    label: type.replace(/_/g, " "),
    className: "bg-zinc-700 text-zinc-300",
  };
  return (
    <span className={`rounded px-1.5 py-0.5 font-mono text-xs font-bold capitalize ${cfg.className}`}>
      {cfg.label}
    </span>
  );
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

function formatDetails(details: Record<string, unknown>): string {
  const parts: string[] = [];
  if (details.price != null)
    parts.push(`$${Number(details.price).toLocaleString("en-US", { minimumFractionDigits: 2 })}`);
  if (details.pnl != null) {
    const pnl = Number(details.pnl);
    parts.push(`P&L: ${pnl >= 0 ? "+" : ""}$${pnl.toFixed(2)}`);
  }
  if (details.position_id != null)
    parts.push(`pos: ${String(details.position_id).slice(0, 8)}`);
  return parts.join(" · ") || "—";
}

export function RiskEventsTable({ events }: RiskEventsTableProps) {
  if (events.length === 0) {
    return (
      <div className="flex h-32 items-center justify-center text-sm text-zinc-600">
        No risk events — everything running smoothly
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full font-mono text-sm">
        <thead>
          <tr className="border-b border-zinc-800 text-left text-xs uppercase tracking-wider text-zinc-600">
            <th className="pb-2 pr-4">Time</th>
            <th className="pb-2 pr-4">Event</th>
            <th className="pb-2">Details</th>
          </tr>
        </thead>
        <tbody>
          {events.map((ev) => (
            <tr
              key={ev.id}
              className="border-b border-zinc-800/50 text-zinc-300 transition-colors hover:bg-zinc-800/30"
            >
              <td className="py-2 pr-4 text-xs text-zinc-500">{formatTime(ev.timestamp)}</td>
              <td className="py-2 pr-4">
                <EventBadge type={ev.event_type} />
              </td>
              <td className="py-2 text-xs text-zinc-400">{formatDetails(ev.details)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
