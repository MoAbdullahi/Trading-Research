"""
ICT P.O.3 Strategy — Multi-Setup Parameter Sweep
===================================================
Runs all named configurations for XAUUSD and GBPUSD.

Usage:
    python test_po3_setups.py                       # all setups, both symbols
    python test_po3_setups.py --symbol XAUUSD       # one symbol
    python test_po3_setups.py --quick               # BASELINE + COMBO only
    python test_po3_setups.py --csv po3_results.csv
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

import pandas as pd

_ROOT = Path(__file__).parent
sys.path.insert(0, str(_ROOT))

from engine.po3_engine import run_backtest, summarize, load_m15, load_m5

DATA_DIR = _ROOT / "data"
SYMBOLS  = ["XAUUSD", "GBPUSD"]

SETUPS: list[tuple[str, str, dict]] = [
    # BASELINE
    ("BASELINE", "default",
        dict(swing_lookback=20, mss_lookback=10, rr_target=3.0, sl_buffer_atr=0.15, max_sweep_m15=8, require_fvg=False)),

    # SWING LOOKBACK
    ("SWING", "swing-30",
        dict(swing_lookback=30, mss_lookback=10, rr_target=3.0, sl_buffer_atr=0.15, max_sweep_m15=8, require_fvg=False)),
    ("SWING", "swing-40",
        dict(swing_lookback=40, mss_lookback=10, rr_target=3.0, sl_buffer_atr=0.15, max_sweep_m15=8, require_fvg=False)),
    ("SWING", "swing-50",
        dict(swing_lookback=50, mss_lookback=10, rr_target=3.0, sl_buffer_atr=0.15, max_sweep_m15=8, require_fvg=False)),

    # RR TARGET
    ("RR", "rr-2.0",
        dict(swing_lookback=20, mss_lookback=10, rr_target=2.0, sl_buffer_atr=0.15, max_sweep_m15=8, require_fvg=False)),
    ("RR", "rr-2.5",
        dict(swing_lookback=20, mss_lookback=10, rr_target=2.5, sl_buffer_atr=0.15, max_sweep_m15=8, require_fvg=False)),

    # SL BUFFER
    ("SL", "sl-0.10",
        dict(swing_lookback=20, mss_lookback=10, rr_target=3.0, sl_buffer_atr=0.10, max_sweep_m15=8, require_fvg=False)),
    ("SL", "sl-0.25",
        dict(swing_lookback=20, mss_lookback=10, rr_target=3.0, sl_buffer_atr=0.25, max_sweep_m15=8, require_fvg=False)),

    # MSS LOOKBACK
    ("MSS", "mss-5",
        dict(swing_lookback=20, mss_lookback=5,  rr_target=3.0, sl_buffer_atr=0.15, max_sweep_m15=8, require_fvg=False)),
    ("MSS", "mss-20",
        dict(swing_lookback=20, mss_lookback=20, rr_target=3.0, sl_buffer_atr=0.15, max_sweep_m15=8, require_fvg=False)),

    # SWEEP EXPIRY
    ("EXPIRY", "expiry-4",
        dict(swing_lookback=20, mss_lookback=10, rr_target=3.0, sl_buffer_atr=0.15, max_sweep_m15=4,  require_fvg=False)),
    ("EXPIRY", "expiry-12",
        dict(swing_lookback=20, mss_lookback=10, rr_target=3.0, sl_buffer_atr=0.15, max_sweep_m15=12, require_fvg=False)),

    # FVG CONFLUENCE
    ("FVG", "fvg-rr3",
        dict(swing_lookback=20, mss_lookback=10, rr_target=3.0, sl_buffer_atr=0.15, max_sweep_m15=8, require_fvg=True)),
    ("FVG", "fvg-rr2",
        dict(swing_lookback=20, mss_lookback=10, rr_target=2.0, sl_buffer_atr=0.15, max_sweep_m15=8, require_fvg=True)),

    # PERIOD SLICES
    ("PERIOD", "2023+",
        dict(swing_lookback=20, mss_lookback=10, rr_target=3.0, sl_buffer_atr=0.15, max_sweep_m15=8, require_fvg=False, start_date="2023-01-01")),
    ("PERIOD", "2024+",
        dict(swing_lookback=20, mss_lookback=10, rr_target=3.0, sl_buffer_atr=0.15, max_sweep_m15=8, require_fvg=False, start_date="2024-01-01")),

    # COMBOS
    ("COMBO", "swing30-rr2",
        dict(swing_lookback=30, mss_lookback=10, rr_target=2.0, sl_buffer_atr=0.15, max_sweep_m15=8, require_fvg=False)),
    ("COMBO", "swing30-rr2-fvg",
        dict(swing_lookback=30, mss_lookback=10, rr_target=2.0, sl_buffer_atr=0.15, max_sweep_m15=8, require_fvg=True)),
    ("COMBO", "swing40-rr2",
        dict(swing_lookback=40, mss_lookback=10, rr_target=2.0, sl_buffer_atr=0.15, max_sweep_m15=8, require_fvg=False)),
    ("COMBO", "swing40-rr2-fvg",
        dict(swing_lookback=40, mss_lookback=10, rr_target=2.0, sl_buffer_atr=0.15, max_sweep_m15=8, require_fvg=True)),
    ("COMBO", "swing30-rr2-2024",
        dict(swing_lookback=30, mss_lookback=10, rr_target=2.0, sl_buffer_atr=0.15, max_sweep_m15=8, require_fvg=False, start_date="2024-01-01")),
    ("COMBO", "swing40-rr2-2024",
        dict(swing_lookback=40, mss_lookback=10, rr_target=2.0, sl_buffer_atr=0.15, max_sweep_m15=8, require_fvg=False, start_date="2024-01-01")),
    ("COMBO", "swing30-sl0.25-rr2",
        dict(swing_lookback=30, mss_lookback=10, rr_target=2.0, sl_buffer_atr=0.25, max_sweep_m15=8, require_fvg=False)),
]

QUICK_FAMILIES = {"BASELINE", "COMBO"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default=None, choices=SYMBOLS + [None])
    parser.add_argument("--quick",  action="store_true")
    parser.add_argument("--csv",    default=None)
    args = parser.parse_args()

    symbols = [args.symbol] if args.symbol else SYMBOLS
    setups  = [(f, n, dict(c)) for f, n, c in SETUPS
               if not args.quick or f in QUICK_FAMILIES]

    # Load data once per symbol
    print("Loading data...")
    data: dict[str, tuple] = {}
    for sym in symbols:
        try:
            m15 = load_m15(sym, DATA_DIR)
            m5  = load_m5(sym,  DATA_DIR)
            data[sym] = (m15, m5)
            print(f"  {sym}: M15={len(m15):,}  M5={len(m5):,}  "
                  f"{m15.index.min().date()} -> {m15.index.max().date()}")
        except FileNotFoundError as e:
            print(f"  {sym}: SKIP - {e}")

    if not data:
        print("ERROR: no data loaded.", file=sys.stderr)
        return 1

    n_runs = len(setups) * len(data)
    print(f"\nRunning {len(setups)} setups x {len(data)} symbols = {n_runs} runs...\n")

    rows: list[dict] = []
    t0 = time.perf_counter()

    for sym, (m15, m5) in data.items():
        print(f"\n{'='*100}")
        print(f"  {sym}")
        print(f"  {'Family':<10}  {'Name':<22}  {'N':>5}  {'WR%':>5}  {'TotalR':>8}  {'AvgR':>7}  {'PF':>5}  {'MaxDD':>7}  {'MaxStr':>6}")
        print(f"{'='*100}")
        prev = [""]

        for family, name, cfg in setups:
            trades, meta = run_backtest(m15, m5, **cfg)
            s = summarize(trades)

            if prev[0] and prev[0] != family:
                print("-" * 100)
            prev[0] = family

            print(
                f"  {family:<10}  {name:<22}  {s['n']:>5}  {s['win_rate']:>5}  "
                f"{s['total_r']:>+8.2f}  {s['avg_r']:>+7.3f}  {s['pf']:>5}  "
                f"{s['max_dd']:>7.2f}  {s['max_loss_streak']:>6}"
            )
            rows.append({"symbol": sym, "family": family, "name": name,
                         **{k: v for k, v in s.items() if k != "exits"}})

        print("=" * 100)

    elapsed = time.perf_counter() - t0
    print(f"\n  Done in {elapsed:.0f}s  ({elapsed/60:.1f} min)\n")

    df = pd.DataFrame(rows)
    enough = df[df["n"] >= 15].copy()

    if not enough.empty:
        cols = ["symbol","family","name","n","win_rate","total_r","pf","max_dd"]
        print("-- Top 10 by Profit Factor (>=15 trades) -------------------")
        print(enough.nlargest(10, "pf")[cols].to_string(index=False))
        print()
        print("-- Top 10 by Total R (>=15 trades) -------------------------")
        print(enough.nlargest(10, "total_r")[cols].to_string(index=False))
        print()

    out = Path(args.csv) if args.csv else _ROOT / "results" / "po3_setup_results.csv"
    out.parent.mkdir(exist_ok=True)
    df.to_csv(out, index=False)
    print(f"Results saved -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
