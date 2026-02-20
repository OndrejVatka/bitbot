"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { Header } from "@/components/Header";
import { PortfolioChart } from "@/components/PortfolioChart";
import { PortfolioStats } from "@/components/PortfolioStats";
import { PositionsTable } from "@/components/PositionsTable";
import { RiskEventsTable } from "@/components/RiskEventsTable";
import { SignalPanel } from "@/components/SignalPanel";
import { SignalsTable } from "@/components/SignalsTable";
import { TradesTable } from "@/components/TradesTable";
import { useWebSocket } from "@/hooks/useWebSocket";
import {
  fetchPortfolio,
  fetchPositions,
  fetchRisk,
  fetchRiskEvents,
  fetchSignals,
  fetchSnapshots,
  fetchTrades,
} from "@/lib/api";
import type { LiveSignal } from "@/types";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type Tab = "trades" | "signals" | "risk";

export default function DashboardPage() {
  const queryClient = useQueryClient();

  // WebSocket — live events from the bot loop
  const wsUrl = `${API_URL}/ws`;
  const { isConnected, lastMessage } = useWebSocket(wsUrl);

  // Live state updated instantly via WebSocket
  const [liveSignal, setLiveSignal] = useState<LiveSignal | null>(null);
  const [livePrice, setLivePrice] = useState<number | null>(null);
  const [activeTab, setActiveTab] = useState<Tab>("trades");

  // REST queries — moderate polling intervals
  const { data: portfolio, error: portfolioError } = useQuery({
    queryKey: ["portfolio"],
    queryFn: fetchPortfolio,
    refetchInterval: 30_000,
    retry: 1,
  });

  const { data: positions = [] } = useQuery({
    queryKey: ["positions"],
    queryFn: fetchPositions,
    refetchInterval: 30_000,
    retry: 1,
  });

  const { data: trades = [] } = useQuery({
    queryKey: ["trades"],
    queryFn: () => fetchTrades(50),
    refetchInterval: 60_000,
    retry: 1,
  });

  const { data: signals = [] } = useQuery({
    queryKey: ["signals"],
    queryFn: () => fetchSignals(50),
    refetchInterval: 60_000,
    retry: 1,
  });

  const { data: snapshots = [] } = useQuery({
    queryKey: ["snapshots"],
    queryFn: () => fetchSnapshots(24),
    refetchInterval: 300_000,
    retry: 1,
  });

  const { data: risk } = useQuery({
    queryKey: ["risk"],
    queryFn: fetchRisk,
    refetchInterval: 30_000,
    retry: 1,
  });

  const { data: riskEvents = [] } = useQuery({
    queryKey: ["risk-events"],
    queryFn: () => fetchRiskEvents(20),
    refetchInterval: 60_000,
    retry: 1,
  });

  // Handle WebSocket events — update local state and invalidate queries
  useEffect(() => {
    if (!lastMessage) return;

    switch (lastMessage.type) {
      case "signal":
        setLiveSignal(lastMessage.data as unknown as LiveSignal);
        void queryClient.invalidateQueries({ queryKey: ["signals"] });
        break;

      case "trade":
        void queryClient.invalidateQueries({ queryKey: ["trades"] });
        void queryClient.invalidateQueries({ queryKey: ["portfolio"] });
        void queryClient.invalidateQueries({ queryKey: ["positions"] });
        break;

      case "price":
        setLivePrice(lastMessage.data.price as number);
        break;

      case "snapshot":
        void queryClient.invalidateQueries({ queryKey: ["snapshots"] });
        void queryClient.invalidateQueries({ queryKey: ["portfolio"] });
        break;

      case "risk_event":
        void queryClient.invalidateQueries({ queryKey: ["risk"] });
        void queryClient.invalidateQueries({ queryKey: ["risk-events"] });
        break;
    }
  }, [lastMessage, queryClient]);

  // API not reachable
  if (portfolioError) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-zinc-950 px-6 text-center">
        <span className="text-5xl">⚡</span>
        <h1 className="text-xl font-bold text-zinc-100">BitBot API not reachable</h1>
        <p className="max-w-sm text-sm text-zinc-500">
          Make sure the bot is running and the API server is up at{" "}
          <code className="rounded bg-zinc-800 px-1.5 py-0.5 font-mono text-zinc-300">
            {API_URL}
          </code>
        </p>
        <p className="text-xs text-zinc-600">
          Start the bot with <code className="font-mono">bitbot</code> — the API starts
          automatically on port 8000.
        </p>
      </div>
    );
  }

  // Prefer live WebSocket data over REST-polled data
  const displaySignal = liveSignal ?? (signals.length > 0 ? signals[0] : null);
  const displayPrice = livePrice ?? portfolio?.current_price ?? null;

  const TABS: { id: Tab; label: string; count: number }[] = [
    { id: "trades", label: "Recent Trades", count: trades.length },
    { id: "signals", label: "Signal History", count: signals.length },
    { id: "risk", label: "Risk Events", count: riskEvents.length },
  ];

  return (
    <div className="min-h-screen bg-zinc-950">
      <Header
        mode={portfolio?.mode ?? "paper"}
        currentPrice={displayPrice}
        isConnected={isConnected}
        symbol={portfolio?.symbol ?? "BTCUSDT"}
      />

      <main className="mx-auto max-w-7xl space-y-6 px-6 py-6">
        {/* KPI cards */}
        <PortfolioStats portfolio={portfolio} risk={risk} />

        {/* Portfolio value chart */}
        <PortfolioChart snapshots={snapshots} />

        {/* Signal panel + open positions */}
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <SignalPanel signal={displaySignal} />
          <PositionsTable positions={positions} />
        </div>

        {/* History tabs */}
        <div className="rounded-lg border border-zinc-800 bg-zinc-900">
          <div className="flex border-b border-zinc-800">
            {TABS.map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`px-6 py-3 text-sm font-medium transition-colors ${
                  activeTab === tab.id
                    ? "border-b-2 border-emerald-500 text-zinc-100"
                    : "text-zinc-500 hover:text-zinc-300"
                }`}
              >
                {tab.label} ({tab.count})
              </button>
            ))}
          </div>

          <div className="p-4">
            {activeTab === "trades" && <TradesTable trades={trades} />}
            {activeTab === "signals" && <SignalsTable signals={signals} />}
            {activeTab === "risk" && <RiskEventsTable events={riskEvents} />}
          </div>
        </div>
      </main>
    </div>
  );
}
