"""
ICT P.O.3 Strategy Runner
===========================
Runs the Power of 3 (Liquidity Sweep + MSS) strategy.

Symbols available: XAUUSD, GBPUSD (Dukascopy 4-year data)

Usage:
    python run_po3.py                            # XAUUSD default
    python run_po3.py --symbol GBPUSD
    python run_po3.py --symbol XAUUSD --rr 2.0 --sl-buf 0.25 --swing 30
    python run_po3.py --start 2024-01-01
    python run_po3.py --fvg                      # require FVG confluence
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

_ROOT = Path(__file__).parent
sys.path.insert(0, str(_ROOT))

from engine.po3_engine import run_backtest, summarize, load_m15, load_m5, SPREADS

DATA_DIR = _ROOT / "data"


def main() -> int:
    parser = argparse.ArgumentParser(description="ICT P.O.3 Backtest")
    parser.add_argument("--symbol",    default="XAUUSD", choices=["XAUUSD","GBPUSD"])
    parser.add_argument("--start",     default=None)
    parser.add_argument("--end",       default=None)
    parser.add_argument("--rr",        type=float, default=3.0)
    parser.add_argument("--sl-buf",    type=float, default=0.15)
    parser.add_argument("--swing",     type=int,   default=20)
    parser.add_argument("--mss-lb",    type=int,   default=10)
    parser.add_argument("--sweep-exp", type=int,   default=8)
    parser.add_argument("--fvg",       action="store_true")
    parser.add_argument("--spread",    action="store_true")
    parser.add_argument("--save",      action="store_true")
    args = parser.parse_args()

    m15 = load_m15(args.symbol, DATA_DIR)
    m5  = load_m5(args.symbol,  DATA_DIR)

    print("=" * 60)
    print(f"  ICT P.O.3  --  {args.symbol}  Backtest")
    print("=" * 60)
    print(f"  M15: {m15.index.min().date()} -> {m15.index.max().date()}  ({len(m15):,} bars)")
    print(f"  M5 : {m5.index.min().date()}  -> {m5.index.max().date()}  ({len(m5):,} bars)")
    print(f"  RR={args.rr}  SL={args.sl_buf}xATR  Swing={args.swing}  "
          f"MSS={args.mss_lb}  Expiry={args.sweep_exp}  FVG={'on' if args.fvg else 'off'}")
    print("=" * 60)

    spd = SPREADS.get(args.symbol, 0.0) if args.spread else 0.0

    trades, meta = run_backtest(
        m15, m5,
        swing_lookback = args.swing,
        mss_lookback   = args.mss_lb,
        rr_target      = args.rr,
        sl_buffer_atr  = args.sl_buf,
        max_sweep_m15  = args.sweep_exp,
        require_fvg    = args.fvg,
        spread         = spd,
        start_date     = args.start,
        end_date       = args.end,
    )

    stats = summarize(trades)

    print(f"\n-- Performance ----------------------------------------")
    print(f"  Trades       : {stats['n']}")
    print(f"  Win rate     : {stats['win_rate']}%")
    print(f"  Total R      : {stats['total_r']:+.2f}R")
    print(f"  Avg R/trade  : {stats['avg_r']:+.3f}R")
    print(f"  Profit factor: {stats['pf']}")
    print(f"  Max drawdown : {stats['max_dd']:.2f}R")
    print(f"  Max loss str.: {stats['max_loss_streak']}")

    print(f"\n-- Signal meta ----------------------------------------")
    print(f"  Bull sweeps  : {meta['bull_sweeps']}")
    print(f"  Bear sweeps  : {meta['bear_sweeps']}")
    print(f"  MSS signals  : {meta['mss_signals']}")
    print(f"  Entries taken: {meta['entries']}")
    print(f"  Sweep expired: {meta['sweep_expired']}")

    print(f"\n-- Exit breakdown -------------------------------------")
    for k, v in stats.get("exits", {}).items():
        print(f"  {k:<18}: {v}")

    if stats["n"] > 0:
        print(f"\n-- Direction split ------------------------------------")
        for d in ["bull", "bear"]:
            sub = trades[trades["direction"] == d]
            if len(sub):
                wr  = round(100 * (sub["realized_r"] > 0).mean(), 1)
                tot = round(sub["realized_r"].sum(), 2)
                print(f"  {d.capitalize():<5}: {len(sub):>4} trades | WR {wr}% | {tot:+.2f}R")

        print(f"\n-- Last 10 trades -------------------------------------")
        cols = ["entry_time","sweep_dir","direction","entry_price","exit_price","realized_r","exit_reason"]
        print(trades[cols].tail(10).to_string(index=False))

    if args.save and not trades.empty:
        out = _ROOT / "results" / f"po3_{args.symbol.lower()}_trades.csv"
        out.parent.mkdir(exist_ok=True)
        trades.to_csv(out, index=False)
        print(f"\nTrades saved -> {out}")

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
