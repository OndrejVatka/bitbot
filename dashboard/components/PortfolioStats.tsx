"use client";

import { useEffect, useState } from "react";
import type { Portfolio, Risk } from "@/types";

interface PortfolioStatsProps {
  portfolio: Portfolio | undefined;
  risk: Risk | undefined;
}

function fmt(n: number, decimals = 2): string {
  return n.toLocaleString("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

function formatCountdown(seconds: number): string {
  if (seconds <= 0) return "0m";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

function PnlValue({ value, suffix = "" }: { value: number; suffix?: string }) {
  const positive = value >= 0;
  return (
    <span className={`font-mono tabular-nums ${positive ? "text-emerald-400" : "text-red-400"}`}>
      {positive ? "+" : ""}
      {fmt(value)}
      {suffix}
    </span>
  );
}

interface StatCardProps {
  label: string;
  children: React.ReactNode;
  sub?: React.ReactNode;
}

function StatCard({ label, children, sub }: StatCardProps) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900 p-4">
      <p className="mb-1 text-xs font-medium uppercase tracking-wider text-zinc-500">{label}</p>
      <div className="text-2xl font-bold tabular-nums text-zinc-100">{children}</div>
      {sub && <div className="mt-1 text-sm text-zinc-400">{sub}</div>}
    </div>
  );
}

/** Risk status card with a live-ticking countdown for cooldown/sentiment block. */
function RiskStatusCard({ risk }: { risk: Risk | undefined }) {
  const [secondsLeft, setSecondsLeft] = useState(0);

  // Sync countdown from the latest REST value
  useEffect(() => {
    const initial = risk?.cooldown_active
      ? risk.cooldown_remaining_seconds
      : risk?.sentiment_block_active
      ? risk.sentiment_block_remaining_seconds
      : 0;
    setSecondsLeft(initial);
  }, [risk]);

  // Tick down once per second while a countdown is active
  useEffect(() => {
    if (secondsLeft <= 0) return;
    const id = setInterval(() => setSecondsLeft((s) => Math.max(0, s - 1)), 1000);
    return () => clearInterval(id);
  }, [secondsLeft]);

  if (!risk) {
    return (
      <StatCard label="Risk Status">
        <span className="text-zinc-500">—</span>
      </StatCard>
    );
  }

  const sub = (
    <span className="font-mono text-sm text-zinc-400">Peak: ${fmt(risk.peak_value)}</span>
  );

  let content: React.ReactNode;

  if (risk.is_halted) {
    content = <span className="text-red-400">⛔ HALTED</span>;
  } else if (risk.cooldown_active || risk.sentiment_block_active) {
    const label = risk.cooldown_active ? "Cooldown" : "Sentiment Block";
    content = (
      <span className="flex items-baseline gap-2">
        <span className="text-amber-400">⏳ {label}</span>
        <span className="font-mono text-base text-zinc-400">{formatCountdown(secondsLeft)}</span>
      </span>
    );
  } else {
    content = (
      <span className="flex items-baseline gap-2">
        <span className="text-emerald-400">Active</span>
        <span className="font-mono text-base text-zinc-400">↓{fmt(risk.drawdown_pct, 1)}%</span>
      </span>
    );
  }

  return (
    <StatCard label="Risk Status" sub={sub}>
      {content}
    </StatCard>
  );
}

export function PortfolioStats({ portfolio, risk }: PortfolioStatsProps) {
  if (!portfolio) {
    return (
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {["Portfolio Value", "Cash Available", "Total P&L", "Risk Status"].map((label) => (
          <div key={label} className="h-24 animate-pulse rounded-lg border border-zinc-800 bg-zinc-900" />
        ))}
      </div>
    );
  }

  const cashPct = portfolio.total_value > 0 ? (portfolio.cash / portfolio.total_value) * 100 : 0;

  return (
    <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
      <StatCard
        label="Portfolio Value"
        sub={<span className="font-mono">Initial: ${fmt(portfolio.initial_capital)}</span>}
      >
        <span className="font-mono">${fmt(portfolio.total_value)}</span>
      </StatCard>

      <StatCard
        label="Cash Available"
        sub={<span className="font-mono text-zinc-400">{fmt(cashPct, 1)}% of portfolio</span>}
      >
        <span className="font-mono">${fmt(portfolio.cash)}</span>
      </StatCard>

      <StatCard
        label="Total P&L"
        sub={
          <span className="font-mono text-sm text-zinc-400">
            R: <PnlValue value={portfolio.realized_pnl} /> &nbsp;U:{" "}
            <PnlValue value={portfolio.unrealized_pnl} />
          </span>
        }
      >
        <PnlValue value={portfolio.total_pnl} />
        <span className="ml-2 text-sm font-normal">
          (<PnlValue value={portfolio.total_pnl_pct} suffix="%" />)
        </span>
      </StatCard>

      <RiskStatusCard risk={risk} />
    </div>
  );
}
