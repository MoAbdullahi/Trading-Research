"""
GOLD ICT H4 OB + M5 MSS — Backtest Runner
==========================================
Usage:
    python run_backtest.py                    # default: full available range, RR=3
    python run_backtest.py --start 2024-01-01 --end 2026-06-01
    python run_backtest.py --rr 2.5 --sl-buf 0.15
    python run_backtest.py --tf 1h            # use 1H as entry TF (full ~2y range)
    python run_backtest.py --fetch            # re-download data first

Steps:
    1. pip install -r requirements.txt
    2. python data_fetch/fetch_gold_yahoo.py  (or use --fetch flag)
    3. python run_backtest.py
"""
from __future__ import annotations

import argparse
import sys
import io
from pathlib import Path

# Force UTF-8 output on Windows (avoids cp1252 encode errors)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

import pandas as pd

# Project root
_ROOT = Path(__file__).parent
sys.path.insert(0, str(_ROOT))

from engine.gold_ict_engine import (
    run_backtest, summarize,
    load_h4, load_h1, load_m5, load_m15,
)

DATA_DIR = _ROOT / "data"


def _load_entry_tf(tf_arg: str) -> tuple[pd.DataFrame, str]:
    if tf_arg == "5m":
        try:
            df = load_m5(DATA_DIR)
            if not df.empty:
                return df, "5M"
            print("  [warn] 5M data empty -- falling back to 1H.")
        except FileNotFoundError:
            print("  [warn] 5M file not found -- falling back to 1H.")
    if tf_arg == "15m":
        try:
            df = load_m15(DATA_DIR)
            if not df.empty:
                return df, "15M"
            print("  [warn] 15M data empty -- falling back to 1H.")
        except FileNotFoundError:
            print("  [warn] 15M file not found -- falling back to 1H.")
    df = load_h1(DATA_DIR)
    return df, "1H"


def _print_banner(h4: pd.DataFrame, ltf: pd.DataFrame, ltf_label: str, args) -> None:
    htf_label = args.htf.upper()
    print("=" * 60)
    print(f"  GOLD ICT {htf_label} OB + {ltf_label} MSS  --  Backtest")
    print("=" * 60)
    print(f"  {htf_label} data  : {h4.index.min().date()} -> {h4.index.max().date()}  ({len(h4):,} bars)")
    print(f"  Entry TF  : {ltf_label} -- {ltf.index.min().date()} -> {ltf.index.max().date()}  ({len(ltf):,} bars)")
    print(f"  RR target : {args.rr}")
    print(f"  SL buffer : {args.sl_buf} x ATR")
    print(f"  OB inval. : {args.ob_inv} x ATR")
    print(f"  MSS lookbk: {args.mss_lb} bars")
    print(f"  Date range: {args.start or 'all'} -> {args.end or 'all'}")
    print("=" * 60)


def _print_results(stats: dict, meta: dict, trades: pd.DataFrame) -> None:
    print("\n-- Performance --------------------------------------")
    print(f"  Trades       : {stats['n']}")
    print(f"  Win rate     : {stats['win_rate']}%")
    print(f"  Total R      : {stats['total_r']:+.2f}R")
    print(f"  Avg R/trade  : {stats['avg_r']:+.3f}R")
    print(f"  Profit factor: {stats['pf']}")
    print(f"  Max drawdown : {stats['max_dd']:.2f}R")
    print(f"  Max loss str.: {stats['max_loss_streak']}")
    print(f"  Expectancy   : {stats['expectancy']:.1f}R total")

    print("\n-- Exit breakdown ----------------------------------─")
    for reason, count in stats.get("exits", {}).items():
        print(f"  {reason:<18}: {count}")

    print("\n-- Signal meta --------------------------------------")
    print(f"  4H OBs created   : {meta.get('h4_obs_created', 0)}")
    print(f"  MSS signals seen : {meta.get('mss_signals_seen', 0)}")
    print(f"  Entries taken    : {meta.get('entries_taken', 0)}")

    if stats["n"] > 0:
        print("\n-- Direction split ----------------------------------")
        for d in ["bull", "bear"]:
            sub = trades[trades["direction"] == d]
            if len(sub) == 0:
                continue
            wr = round(100 * (sub["realized_r"] > 0).mean(), 1)
            tr = round(sub["realized_r"].sum(), 2)
            print(f"  {d.capitalize():<6}: {len(sub):>3} trades | WR {wr}% | Total R {tr:+.2f}")

        print("\n-- Last 10 trades ----------------------------------─")
        cols = ["entry_time", "direction", "entry_price", "exit_price", "realized_r", "exit_reason"]
        print(trades[cols].tail(10).to_string(index=False))

    print()


def main() -> int:
    parser = argparse.ArgumentParser(description="GOLD ICT H4 OB + M5 MSS Backtest")
    parser.add_argument("--start",   default=None,  help="Start date YYYY-MM-DD")
    parser.add_argument("--end",     default=None,  help="End date YYYY-MM-DD")
    parser.add_argument("--rr",      type=float, default=3.0,  help="RR target (default 3.0)")
    parser.add_argument("--sl-buf",  type=float, default=0.10, help="SL ATR buffer (default 0.10)")
    parser.add_argument("--ob-inv",  type=float, default=0.20, help="OB invalidation ATR (default 0.20)")
    parser.add_argument("--mss-lb",  type=int,   default=10,   help="MSS lookback bars (default 10)")
    parser.add_argument("--tf",      default="5m", choices=["5m", "15m", "1h"],
                        help="Entry timeframe: 5m, 15m, or 1h (default 5m)")
    parser.add_argument("--htf",     default="4h", choices=["4h", "1h"],
                        help="Higher timeframe for OB detection: 4h or 1h (default 4h)")
    parser.add_argument("--fetch",   action="store_true", help="Re-download Yahoo data first")
    args = parser.parse_args()

    # Optionally re-fetch data
    if args.fetch:
        print("Fetching data from Yahoo Finance...\n")
        import subprocess
        result = subprocess.run(
            [sys.executable, str(_ROOT / "data_fetch" / "fetch_gold_yahoo.py")],
            capture_output=False,
        )
        if result.returncode != 0:
            print("Data fetch failed — aborting.", file=sys.stderr)
            return 1
        print()

    # Load HTF data
    try:
        htf = load_h1(DATA_DIR) if args.htf == "1h" else load_h4(DATA_DIR)
    except FileNotFoundError:
        print(f"ERROR: {args.htf.upper()} data not found. Run: python data_fetch/resample_dukascopy.py", file=sys.stderr)
        return 1

    # Load entry TF data
    try:
        ltf, ltf_label = _load_entry_tf(args.tf)
    except FileNotFoundError:
        print("ERROR: Entry TF data not found. Run: python data_fetch/resample_dukascopy.py", file=sys.stderr)
        return 1

    _print_banner(htf, ltf, ltf_label, args)

    # Infer max_hold_bars from entry TF
    bars_per_h = {"5M": 12, "15M": 4, "1H": 1}
    max_hold = 48 * bars_per_h.get(ltf_label, 12)

    print("\nRunning backtest...", flush=True)
    trades, meta = run_backtest(
        htf, ltf,
        rr_target      = args.rr,
        sl_buffer_atr  = args.sl_buf,
        ob_invalid_atr = args.ob_inv,
        mss_lookback   = args.mss_lb,
        max_hold_bars  = max_hold,
        htf_bar_size   = args.htf,
        start_date     = args.start,
        end_date       = args.end,
    )

    stats = summarize(trades)
    _print_results(stats, meta, trades)

    # Save trades to CSV
    if not trades.empty:
        out = _ROOT / "trades_result.csv"
        trades.to_csv(out, index=False)
        print(f"Trades saved -> {out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
