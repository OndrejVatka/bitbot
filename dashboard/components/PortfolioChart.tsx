"use client";

import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { Snapshot } from "@/types";

interface PortfolioChartProps {
  snapshots: Snapshot[];
}

function formatTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false });
}

function formatDollar(v: number): string {
  return `$${v.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;
}

export function PortfolioChart({ snapshots }: PortfolioChartProps) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
      <h2 className="mb-4 text-xs font-medium uppercase tracking-wider text-zinc-500">
        Portfolio Value (24h)
      </h2>

      {snapshots.length === 0 ? (
        <div className="flex h-40 items-center justify-center text-sm text-zinc-600">
          No snapshots yet — data appears every 10 candles (~2.5h)
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={180}>
          <AreaChart data={snapshots} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
            <defs>
              <linearGradient id="portfolioGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#34d399" stopOpacity={0.15} />
                <stop offset="95%" stopColor="#34d399" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#27272a" vertical={false} />
            <XAxis
              dataKey="timestamp"
              tickFormatter={formatTime}
              tick={{ fill: "#71717a", fontSize: 11, fontFamily: "monospace" }}
              axisLine={false}
              tickLine={false}
              interval="preserveStartEnd"
            />
            <YAxis
              tickFormatter={formatDollar}
              tick={{ fill: "#71717a", fontSize: 11, fontFamily: "monospace" }}
              axisLine={false}
              tickLine={false}
              width={72}
              domain={["auto", "auto"]}
            />
            <Tooltip
              contentStyle={{
                background: "#18181b",
                border: "1px solid #3f3f46",
                borderRadius: "6px",
                fontSize: "12px",
                fontFamily: "monospace",
              }}
              labelStyle={{ color: "#a1a1aa" }}
              itemStyle={{ color: "#34d399" }}
              formatter={(value: number) => [formatDollar(value), "Portfolio"]}
              labelFormatter={formatTime}
            />
            <Area
              type="monotone"
              dataKey="total_value"
              stroke="#34d399"
              strokeWidth={1.5}
              fill="url(#portfolioGradient)"
              dot={false}
              activeDot={{ r: 3, fill: "#34d399" }}
            />
          </AreaChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
