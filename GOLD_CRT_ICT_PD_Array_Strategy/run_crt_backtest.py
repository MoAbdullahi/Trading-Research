"""
GOLD CRT (Candle Range Theory) — Backtest Runner
=================================================
Strategy:  3-candle CRT rule (Reference → Sweep → Re-entry = Entry)
Trend filter: HTF price vs SMA-200  (bull-only above, bear-only below)
Session:   London 02-08 NY / New York 08-13 NY

Usage:
    python run_crt_backtest.py                                          # 4H ref + 5M entry, full range
    python run_crt_backtest.py --htf 1h --tf 5m                        # 1H reference candle
    python run_crt_backtest.py --tf 15m                                 # 15M entry timeframe
    python run_crt_backtest.py --start 2023-01-01 --end 2024-12-31
    python run_crt_backtest.py --session-mode tight --min-rr 1.5        # improved quality filters
    python run_crt_backtest.py --session-mode tight --min-rr 1.5 --vol-filter  # all filters

Fixed (not tunable to avoid overfitting):
    --trend-sma 200   SMA period for trend bias
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

import pandas as pd

_ROOT = Path(__file__).parent
sys.path.insert(0, str(_ROOT))

from engine.gold_ict_engine import load_h4, load_h1, load_m5, load_m15, summarize
from engine.crt_engine import run_crt_backtest

DATA_DIR   = _ROOT / "data"
BARS_PER_H = {"5M": 12, "15M": 4, "1H": 1}


def _load_entry_tf(label: str, symbol: str) -> tuple[pd.DataFrame, str]:
    if label == "5m":
        return load_m5(DATA_DIR, symbol=symbol), "5M"
    if label == "15m":
        return load_m15(DATA_DIR, symbol=symbol), "15M"
    return load_h1(DATA_DIR, symbol=symbol), "1H"


def _load_htf(label: str, symbol: str) -> pd.DataFrame:
    return load_h1(DATA_DIR, symbol=symbol) if label == "1h" else load_h4(DATA_DIR, symbol=symbol)


def _print_banner(htf: pd.DataFrame, ltf: pd.DataFrame, ltf_label: str, args) -> None:
    htf_label = args.htf.upper()
    symbol    = args.symbol.upper()
    session_desc = {
        "broad": "02-13 NY (London open + full NY)",
        "tight": "04-11 NY (core London + NY AM)",
        "kz":    "05-10 NY (kill zone only)",
    }.get(args.session_mode, args.session_mode)
    print("=" * 62)
    print(f"  {symbol} CRT  |  {htf_label} reference  +  {ltf_label} entry")
    print("=" * 62)
    print(f"  {htf_label} data    : {htf.index.min().date()} -> {htf.index.max().date()}  ({len(htf):,} bars)")
    print(f"  Entry TF  : {ltf_label} | {ltf.index.min().date()} -> {ltf.index.max().date()}  ({len(ltf):,} bars)")
    print(f"  SL buffer : {args.sl_buf} x ATR14 beyond sweep extreme")
    print(f"  Min range : {args.min_range} x ATR14  (ref candle qualifier)")
    print(f"  Trend SMA : {args.trend_sma}-period HTF SMA  (trend bias filter)")
    print(f"  Session   : {session_desc}")
    print(f"  Min RR    : {args.min_rr if args.min_rr > 0 else 'off'}")
    print(f"  Vol filter: {'on (ATR > 50-bar mean)' if args.vol_filter else 'off'}")
    print(f"  Date range: {args.start or 'all'} -> {args.end or 'all'}")
    print("=" * 62)


def _print_results(stats: dict, meta: dict, trades: pd.DataFrame) -> None:
    print("\n-- Performance -----------------------------------------------")
    print(f"  Trades          : {stats['n']}")
    print(f"  Win rate        : {stats['win_rate']}%")
    print(f"  Total R         : {stats['total_r']:+.2f}R")
    print(f"  Avg R / trade   : {stats['avg_r']:+.3f}R")
    print(f"  Profit factor   : {stats['pf']}")
    print(f"  Max drawdown    : {stats['max_dd']:.2f}R")
    print(f"  Max loss streak : {stats['max_loss_streak']}")
    print(f"  Expectancy      : {stats['expectancy']:.1f}R total")

    print("\n-- Exit breakdown --------------------------------------------")
    for reason, count in stats.get("exits", {}).items():
        print(f"  {reason:<18} : {count}")

    print("\n-- Signal pipeline ------------------------------------------")
    total_refs = (meta.get('refs_qualified', 0) + meta.get('refs_rejected', 0)
                  + meta.get('refs_low_vol', 0))
    print(f"  HTF bars processed    : {total_refs + meta.get('refs_no_trend', 0)}")
    print(f"    SMA not yet warm    : {meta.get('refs_no_trend', 0)}")
    print(f"    Vol filter blocked  : {meta.get('refs_low_vol', 0)}")
    print(f"    Range too small     : {meta.get('refs_rejected', 0)}")
    print(f"    Refs qualified      : {meta.get('refs_qualified', 0)}")
    print(f"  Sweeps (bull / bear)  : {meta.get('sweeps_bull', 0)} / {meta.get('sweeps_bear', 0)}")
    print(f"  Skipped (min RR)      : {meta.get('skipped_min_rr', 0)}")
    print(f"  Entries (bull / bear) : {meta.get('entries_bull', 0)} / {meta.get('entries_bear', 0)}")

    if stats["n"] > 0:
        print("\n-- Direction split -------------------------------------------")
        for d in ["bull", "bear"]:
            sub = trades[trades["direction"] == d]
            if sub.empty:
                continue
            wr  = round(100 * (sub["realized_r"] > 0).mean(), 1)
            tr  = round(sub["realized_r"].sum(), 2)
            avg_win = sub.loc[sub["realized_r"] > 0, "realized_r"].mean()
            avg_win = round(avg_win, 2) if not pd.isna(avg_win) else 0.0
            print(f"  {d.capitalize():<6} : {len(sub):>3} trades | WR {wr}% | "
                  f"Total R {tr:+.2f} | Avg win {avg_win:.2f}R")

        print("\n-- Natural RR distribution (winning trades) -----------------")
        wins = trades.loc[trades["realized_r"] > 0, "natural_rr"]
        if not wins.empty:
            print(f"  Min  : {wins.min():.2f}R")
            print(f"  Mean : {wins.mean():.2f}R")
            print(f"  Max  : {wins.max():.2f}R")
            buckets = [
                ("< 1R",   wins < 1),
                ("1-2R",   (wins >= 1) & (wins < 2)),
                ("2-3R",   (wins >= 2) & (wins < 3)),
                ("3R+",    wins >= 3),
            ]
            print("  Distribution:")
            for label, mask in buckets:
                print(f"    {label:<6}: {mask.sum()} wins")

        print("\n-- Yearly breakdown -----------------------------------------")
        trades["year"] = pd.to_datetime(trades["entry_time"]).dt.year
        for yr, grp in trades.groupby("year"):
            wr = round(100 * (grp["realized_r"] > 0).mean(), 1)
            tr = round(grp["realized_r"].sum(), 2)
            print(f"  {yr} : {len(grp):>3} trades | WR {wr}% | Total R {tr:+.2f}")

        print("\n-- Last 10 trades -------------------------------------------")
        cols = ["entry_time", "direction", "entry_price", "stop", "target",
                "exit_price", "realized_r", "natural_rr", "exit_reason"]
        print(trades[cols].tail(10).to_string(index=False))

    print()


def main() -> int:
    parser = argparse.ArgumentParser(description="GOLD CRT Backtest")
    parser.add_argument("--symbol",      default="XAUUSD",
                        help="Instrument symbol matching data files (default XAUUSD)")
    parser.add_argument("--htf",        default="4h", choices=["4h", "1h"],
                        help="Reference candle TF: 4h or 1h (default 4h)")
    parser.add_argument("--tf",         default="5m", choices=["5m", "15m", "1h"],
                        help="Entry TF: 5m, 15m, or 1h (default 5m)")
    parser.add_argument("--sl-buf",     type=float, default=0.10,
                        help="ATR buffer beyond sweep extreme (default 0.10)")
    parser.add_argument("--min-range",  type=float, default=0.5,
                        help="Min HTF candle range in ATR multiples (default 0.5)")
    parser.add_argument("--trend-sma",    type=int,   default=200,
                        help="HTF SMA period for trend bias (default 200, do not tune)")
    parser.add_argument("--session-mode", default="broad",
                        choices=["broad", "tight", "kz"],
                        help="Session window: broad=02-13, tight=04-11, kz=05-10 (NY time)")
    parser.add_argument("--min-rr",       type=float, default=0.0,
                        help="Skip setup if natural RR < this (0 = off, recommended 1.5)")
    parser.add_argument("--vol-filter",   action="store_true",
                        help="Only trade when HTF ATR > its 50-bar rolling mean")
    parser.add_argument("--start",        default=None, help="Start date YYYY-MM-DD")
    parser.add_argument("--end",          default=None, help="End date YYYY-MM-DD")
    args = parser.parse_args()

    try:
        htf = _load_htf(args.htf, args.symbol)
    except FileNotFoundError:
        print(f"ERROR: {args.htf.upper()} data not found for {args.symbol}.", file=sys.stderr)
        return 1

    try:
        ltf, ltf_label = _load_entry_tf(args.tf, args.symbol)
    except FileNotFoundError:
        print(f"ERROR: {args.tf.upper()} data not found for {args.symbol}.", file=sys.stderr)
        return 1

    _print_banner(htf, ltf, ltf_label, args)

    max_hold = 48 * BARS_PER_H.get(ltf_label, 12)

    print("\nRunning CRT backtest...", flush=True)
    trades, meta = run_crt_backtest(
        htf, ltf,
        sl_buffer_atr = args.sl_buf,
        min_range_atr = args.min_range,
        min_rr        = args.min_rr,
        trend_sma     = args.trend_sma,
        vol_filter    = args.vol_filter,
        session_mode  = args.session_mode,
        max_hold_bars = max_hold,
        htf_bar_size  = args.htf,
        start_date    = args.start,
        end_date      = args.end,
    )

    stats = summarize(trades)
    _print_results(stats, meta, trades)

    if not trades.empty:
        out = _ROOT / "crt_trades_result.csv"
        trades.to_csv(out, index=False)
        print(f"Trades saved -> {out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
