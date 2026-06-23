"""
run_visualization.py — Entry-point script.

Usage:
    python run_visualization.py [--symbol SYMBOL] [--mode h4_m15|h4_m5]
                                [--start YYYY-MM-DD] [--end YYYY-MM-DD]
                                [--out OUTPUT_DIR]

Example:
    python run_visualization.py --symbol EURUSD --mode h4_m15 \\
                                --start 2024-01-01 --end 2024-12-31 \\
                                --out ./viz_output/EURUSD_2024

Output:
    OUTPUT_DIR/
      dashboard.html         ← Open this in your browser
      trade_001.html         ← Linked from dashboard
      trade_002.html
      ...

Requirements:
    pip install pandas numpy plotly

Data:
    Place these in /mnt/user-data/uploads/ (or update UPLOADS in phase2_engine):
      EURUSD_M15.parquet  EURUSD_M5.parquet
      GBPUSD_M15.parquet  GBPUSD_M5.parquet
      ... etc for each symbol
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path
from viz_engine import run_instrumented_backtest, summarize_trades
from viz_dashboard import generate_dashboard


MODE_MAP = {
    "h4_m15": ("4h",  "15min", "A"),
    "h4_m5":  ("4h",  "5min",  "A"),
}


def main():
    p = argparse.ArgumentParser(description="Generate trade visualization dashboard")
    p.add_argument("--symbol", default="EURUSD",
                    help="Trading symbol (default: EURUSD)")
    p.add_argument("--mode", default="h4_m15", choices=list(MODE_MAP.keys()),
                    help="Strategy mode (default: h4_m15)")
    p.add_argument("--start", default=None,
                    help="Start date YYYY-MM-DD (default: all available)")
    p.add_argument("--end", default=None,
                    help="End date YYYY-MM-DD (default: all available)")
    p.add_argument("--out", default=None,
                    help="Output directory (default: ./viz_output/<symbol>_<mode>)")
    p.add_argument("--account", type=float, default=100_000.0,
                    help="Account size in USD (default: 100000)")
    p.add_argument("--risk", type=float, default=1.0,
                    help="Risk per trade %% (default: 1.0)")
    args = p.parse_args()

    htf_freq, ltf_freq, scheme = MODE_MAP[args.mode]
    out_dir = args.out or f"./viz_output/{args.symbol}_{args.mode}"

    print(f"Running backtest: {args.symbol} {args.mode}")
    print(f"  HTF={htf_freq}  LTF={ltf_freq}  scheme={scheme}")
    print(f"  Period: {args.start or 'beginning'} → {args.end or 'end'}")
    print()

    try:
        trades = run_instrumented_backtest(
            args.symbol, htf_freq, ltf_freq, scheme,
            start=args.start, end=args.end,
        )
    except FileNotFoundError as e:
        print(f"ERROR: data file not found.")
        print(f"  {e}")
        print(f"  Make sure {args.symbol}_M15.parquet and {args.symbol}_M5.parquet")
        print(f"  are in your uploads/data folder.")
        return 1

    stats = summarize_trades(trades)
    completed = [t for t in trades if t.exit_reason not in (None, "no_fill")]
    print(f"Triggers detected: {len(trades)}")
    print(f"Trades completed:  {len(completed)}")
    if stats["n"] > 0:
        print()
        print("=" * 60)
        print("BACKTEST SUMMARY")
        print("=" * 60)
        for k, v in stats.items():
            print(f"  {k:<22} {v}")
        print()
        risk_per_trade = args.account * args.risk / 100.0
        total_pnl = stats["total_r"] * risk_per_trade
        print(f"  Net P&L (${args.account:,.0f} @ {args.risk}% risk): "
              f"${total_pnl:+,.2f}  ({100*total_pnl/args.account:+.2f}%)")
        print("=" * 60)

    print()
    print(f"Generating HTML dashboard in {out_dir}...")
    dash_path = generate_dashboard(
        trades, out_dir,
        title=f"SMC CRT — {args.symbol} {args.mode}",
        account_size=args.account,
        risk_per_trade_pct=args.risk,
    )

    print(f"\n✓ Done. Open in browser:")
    print(f"  {dash_path.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
