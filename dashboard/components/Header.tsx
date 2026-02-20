interface HeaderProps {
  mode: string;
  currentPrice: number | null;
  isConnected: boolean;
  symbol: string;
}

function formatPrice(price: number): string {
  return price.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

export function Header({ mode, currentPrice, isConnected, symbol }: HeaderProps) {
  return (
    <header className="sticky top-0 z-10 border-b border-zinc-800 bg-zinc-950/90 backdrop-blur-sm">
      <div className="mx-auto flex h-14 max-w-7xl items-center justify-between px-6">
        {/* Logo + mode */}
        <div className="flex items-center gap-3">
          <span className="text-lg font-bold tracking-tight text-zinc-100">⚡ BitBot</span>
          <span
            className={`rounded px-2 py-0.5 font-mono text-xs font-bold ${
              mode === "live"
                ? "border border-red-500/30 bg-red-500/10 text-red-400"
                : "border border-amber-500/30 bg-amber-500/10 text-amber-400"
            }`}
          >
            {mode.toUpperCase()}
          </span>
        </div>

        {/* Current price */}
        <div className="flex items-center gap-2">
          <span className="font-mono text-sm text-zinc-500">{symbol}</span>
          <span className="font-mono text-2xl font-bold tabular-nums text-zinc-100">
            {currentPrice != null ? `$${formatPrice(currentPrice)}` : "—"}
          </span>
        </div>

        {/* Connection status */}
        <div className="flex items-center gap-2">
          <span
            className={`h-2 w-2 rounded-full ${
              isConnected ? "animate-pulse bg-emerald-400" : "bg-red-500"
            }`}
          />
          <span
            className={`text-xs font-medium ${
              isConnected ? "text-emerald-400" : "text-red-400"
            }`}
          >
            {isConnected ? "Live" : "Disconnected"}
          </span>
        </div>
      </div>
    </header>
  );
}
