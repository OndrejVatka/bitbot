"""CLI entry point for backtesting operations.

Usage:
    bitbot-backtest run --start 2024-01-01 --end 2024-06-30
    bitbot-backtest optimize --metric sharpe_ratio
    bitbot-backtest stress
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import certifi

# Fix SSL for macOS
if not os.environ.get("SSL_CERT_FILE"):
    os.environ["SSL_CERT_FILE"] = certifi.where()


def main() -> None:
    """Parse arguments and dispatch to the appropriate command."""
    parser = argparse.ArgumentParser(
        description="BitBot Backtesting Engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- run command ---
    run_parser = subparsers.add_parser("run", help="Run a single backtest")
    run_parser.add_argument(
        "--start", required=True, help="Start date (YYYY-MM-DD)"
    )
    run_parser.add_argument(
        "--end", required=True, help="End date (YYYY-MM-DD)"
    )
    run_parser.add_argument(
        "--symbol", default="BTCUSDT", help="Trading pair (default: BTCUSDT)"
    )
    run_parser.add_argument(
        "--capital", type=float, default=1000.0, help="Initial capital in USDT"
    )
    run_parser.add_argument(
        "--save-charts", default=None, help="Directory to save charts (e.g., output/)"
    )
    run_parser.add_argument(
        "-v", "--verbose", action="store_true", help="Verbose logging"
    )

    # --- optimize command ---
    opt_parser = subparsers.add_parser("optimize", help="Run parameter optimization")
    opt_parser.add_argument(
        "--start", required=True, help="Start date (YYYY-MM-DD)"
    )
    opt_parser.add_argument(
        "--end", required=True, help="End date (YYYY-MM-DD)"
    )
    opt_parser.add_argument(
        "--metric", default="sharpe_ratio",
        help="Metric to optimize (default: sharpe_ratio)",
    )
    opt_parser.add_argument(
        "--max-combos", type=int, default=200,
        help="Max parameter combinations to test",
    )
    opt_parser.add_argument(
        "--walk-forward", action="store_true",
        help="Use walk-forward validation (70/30 split)",
    )
    opt_parser.add_argument(
        "--symbol", default="BTCUSDT", help="Trading pair"
    )
    opt_parser.add_argument(
        "--capital", type=float, default=1000.0, help="Initial capital in USDT"
    )
    opt_parser.add_argument(
        "-v", "--verbose", action="store_true", help="Verbose logging"
    )

    # --- stress command ---
    stress_parser = subparsers.add_parser("stress", help="Run stress tests")
    stress_parser.add_argument(
        "--symbol", default="BTCUSDT", help="Trading pair"
    )
    stress_parser.add_argument(
        "--capital", type=float, default=1000.0, help="Initial capital in USDT"
    )
    stress_parser.add_argument(
        "-v", "--verbose", action="store_true", help="Verbose logging"
    )

    args = parser.parse_args()

    log_level = logging.DEBUG if getattr(args, "verbose", False) else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if args.command == "run":
        asyncio.run(_cmd_run(args))
    elif args.command == "optimize":
        asyncio.run(_cmd_optimize(args))
    elif args.command == "stress":
        asyncio.run(_cmd_stress(args))


async def _setup_loader(symbol: str):
    """Initialize Binance client, database, and data loader."""
    from binance import AsyncClient

    from bitbot.database.repository import Repository
    from bitbot.database.schema import initialize_database
    from bitbot.market_data.historical import HistoricalDataFetcher
    from bitbot.backtesting.data_loader import DataLoader

    db = await initialize_database("data/bitbot.db")
    repo = Repository(db)
    client = await AsyncClient.create()
    fetcher = HistoricalDataFetcher(client)
    loader = DataLoader(fetcher, repo)

    return loader, client, db


async def _cmd_run(args: argparse.Namespace) -> None:
    """Execute a single backtest run."""
    from bitbot.backtesting.engine import BacktestConfig, BacktestEngine
    from bitbot.backtesting.metrics import MetricsCalculator
    from bitbot.backtesting.report import BacktestReport

    start = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end = datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=timezone.utc)

    print(f"\nLoading data for {args.symbol} ({args.start} to {args.end})...")

    loader, client, db = await _setup_loader(args.symbol)

    try:
        dataset = await loader.load_dataset(args.symbol, start, end)

        config = BacktestConfig(
            symbol=args.symbol,
            initial_capital=args.capital,
        )
        engine = BacktestEngine(config)

        print(f"Running backtest ({len(dataset.candles_15m)} candles)...")
        result = engine.run(dataset)

        metrics = MetricsCalculator.calculate(result)
        report = BacktestReport.text_summary(metrics, result)
        print(report)

        if args.save_charts:
            chart_dir = args.save_charts
            print(f"\nSaving charts to {chart_dir}/...")
            BacktestReport.plot_equity_curve(result, f"{chart_dir}/equity_curve.png")
            BacktestReport.plot_monthly_returns(metrics, f"{chart_dir}/monthly_returns.png")
            BacktestReport.plot_drawdown(result, f"{chart_dir}/drawdown.png")
            print("Charts saved.")
    finally:
        await client.close_connection()
        await db.close()


async def _cmd_optimize(args: argparse.Namespace) -> None:
    """Execute parameter optimization."""
    from bitbot.backtesting.engine import BacktestConfig
    from bitbot.backtesting.optimizer import Optimizer, ParameterSpace

    start = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end = datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=timezone.utc)

    print(f"\nLoading data for {args.symbol} ({args.start} to {args.end})...")

    loader, client, db = await _setup_loader(args.symbol)

    try:
        dataset = await loader.load_dataset(args.symbol, start, end)

        config = BacktestConfig(
            symbol=args.symbol,
            initial_capital=args.capital,
        )
        space = ParameterSpace()
        optimizer = Optimizer(dataset)

        if args.walk_forward:
            print("Running walk-forward optimization...")
            is_result, oos_result = optimizer.walk_forward(
                space, config,
                metric=args.metric,
                max_combinations=args.max_combos,
            )

            print("\n--- IN-SAMPLE RESULTS ---")
            print(Optimizer.format_results_table(is_result))

            print("\n--- OUT-OF-SAMPLE VALIDATION ---")
            print(Optimizer.format_results_table(oos_result))
        else:
            print(f"Running grid search (max {args.max_combos} combinations)...")
            result = optimizer.grid_search(
                space, config,
                metric=args.metric,
                max_combinations=args.max_combos,
            )
            print(Optimizer.format_results_table(result))
    finally:
        await client.close_connection()
        await db.close()


async def _cmd_stress(args: argparse.Namespace) -> None:
    """Execute stress tests across crash periods."""
    from bitbot.backtesting.engine import BacktestConfig
    from bitbot.backtesting.stress import StressTester

    print(f"\nRunning stress tests for {args.symbol}...")

    loader, client, db = await _setup_loader(args.symbol)

    try:
        config = BacktestConfig(
            symbol=args.symbol,
            initial_capital=args.capital,
        )
        tester = StressTester(loader, config)
        result = await tester.run_all()
        print(result.format_comparison_table())
    finally:
        await client.close_connection()
        await db.close()


if __name__ == "__main__":
    main()
