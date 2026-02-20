import type { Config, Portfolio, Position, Risk, RiskEvent, Signal, Snapshot, Trade } from "@/types";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function fetchJson<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`API error ${res.status}: ${path}`);
  return res.json() as Promise<T>;
}

export const fetchPortfolio = (): Promise<Portfolio> => fetchJson("/api/portfolio");
export const fetchPositions = (): Promise<Position[]> => fetchJson("/api/positions");
export const fetchTrades = (limit = 50): Promise<Trade[]> => fetchJson(`/api/trades?limit=${limit}`);
export const fetchSignals = (limit = 50): Promise<Signal[]> => fetchJson(`/api/signals?limit=${limit}`);
export const fetchSnapshots = (hours = 24): Promise<Snapshot[]> => fetchJson(`/api/snapshots?hours=${hours}`);
export const fetchRisk = (): Promise<Risk> => fetchJson("/api/risk");
export const fetchConfig = (): Promise<Config> => fetchJson("/api/config");
export const fetchRiskEvents = (limit = 20): Promise<RiskEvent[]> =>
  fetchJson(`/api/risk-events?limit=${limit}`);
