"""
GOLD ICT Strategy — Multi-Setup Parameter Sweep
================================================
Tests named configurations derived from ICT_MultiTF_Strategy.pine.txt:

  Setup families:
    BASELINE   — original defaults (both directions, 3R, tight SL)
    DIRECTION  — bull-only vs bear-only filter
    ENTRY RISK — SL buffer variations (risk vs confirmation style)
    RR TARGET  — different reward ratios (2R / 2.5R / 3R / 4R)
    MSS        — lookback length (5 / 10 / 20 bars)
    PERIOD     — sub-period slices (2022, 2023, 2024, 2025, 2024-2026)
    COMBO      — best guesses combining direction + SL + RR

Usage:
    python test_setups.py
    python test_setups.py --quick   # only BASELINE + DIRECTION + COMBO families
    python test_setups.py --csv all_setups.csv
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

from engine.gold_ict_engine import run_backtest, summarize, load_h4, load_m5

DATA_DIR = _ROOT / "data"

# ── Setup registry ─────────────────────────────────────────────────────────────
# Each entry: (family, name, kwargs_for_run_backtest)
SETUPS: list[tuple[str, str, dict]] = [
    # ── BASELINE ──────────────────────────────────────────────────────────────
    ("BASELINE", "default-3R",       dict(rr_target=3.0, sl_buffer_atr=0.10, direction_filter="both")),

    # ── DIRECTION FILTER ──────────────────────────────────────────────────────
    ("DIRECTION", "bull-only-3R",    dict(rr_target=3.0, sl_buffer_atr=0.10, direction_filter="bull")),
    ("DIRECTION", "bear-only-3R",    dict(rr_target=3.0, sl_buffer_atr=0.10, direction_filter="bear")),

    # ── ENTRY RISK (SL buffer = how much wick room) ────────────────────────────
    # Tight SL  = risk-entry style (entry at zone edge, better RR, lower WR)
    # Wide SL   = confirmation-entry style (more room, higher WR, smaller RR)
    ("ENTRY-RISK", "sl-tight-0.05",  dict(rr_target=3.0, sl_buffer_atr=0.05, direction_filter="both")),
    ("ENTRY-RISK", "sl-normal-0.10", dict(rr_target=3.0, sl_buffer_atr=0.10, direction_filter="both")),
    ("ENTRY-RISK", "sl-wide-0.30",   dict(rr_target=3.0, sl_buffer_atr=0.30, direction_filter="both")),
    ("ENTRY-RISK", "sl-wider-0.50",  dict(rr_target=3.0, sl_buffer_atr=0.50, direction_filter="both")),

    # ── RR TARGET ─────────────────────────────────────────────────────────────
    ("RR-TARGET", "rr-2.0",          dict(rr_target=2.0, sl_buffer_atr=0.10, direction_filter="both")),
    ("RR-TARGET", "rr-2.5",          dict(rr_target=2.5, sl_buffer_atr=0.10, direction_filter="both")),
    ("RR-TARGET", "rr-3.0",          dict(rr_target=3.0, sl_buffer_atr=0.10, direction_filter="both")),
    ("RR-TARGET", "rr-4.0",          dict(rr_target=4.0, sl_buffer_atr=0.10, direction_filter="both")),

    # ── MSS LOOKBACK ──────────────────────────────────────────────────────────
    ("MSS-LB", "mss-5",              dict(rr_target=3.0, sl_buffer_atr=0.10, mss_lookback=5,  direction_filter="both")),
    ("MSS-LB", "mss-10",             dict(rr_target=3.0, sl_buffer_atr=0.10, mss_lookback=10, direction_filter="both")),
    ("MSS-LB", "mss-20",             dict(rr_target=3.0, sl_buffer_atr=0.10, mss_lookback=20, direction_filter="both")),

    # ── SUB-PERIODS ───────────────────────────────────────────────────────────
    ("PERIOD", "2022",               dict(rr_target=3.0, sl_buffer_atr=0.10, direction_filter="both", start_date="2022-01-01", end_date="2022-12-31")),
    ("PERIOD", "2023",               dict(rr_target=3.0, sl_buffer_atr=0.10, direction_filter="both", start_date="2023-01-01", end_date="2023-12-31")),
    ("PERIOD", "2024",               dict(rr_target=3.0, sl_buffer_atr=0.10, direction_filter="both", start_date="2024-01-01", end_date="2024-12-31")),
    ("PERIOD", "2025",               dict(rr_target=3.0, sl_buffer_atr=0.10, direction_filter="both", start_date="2025-01-01", end_date="2025-12-31")),
    ("PERIOD", "2024-now",           dict(rr_target=3.0, sl_buffer_atr=0.10, direction_filter="both", start_date="2024-01-01")),
    ("PERIOD", "bull-only-2024",     dict(rr_target=3.0, sl_buffer_atr=0.10, direction_filter="bull", start_date="2024-01-01")),

    # ── COMBO (ICT risk-entry style: no confirmation, tight SL, bull trend) ───
    ("COMBO", "bull-sl0.3-rr2",      dict(rr_target=2.0, sl_buffer_atr=0.30, direction_filter="bull")),
    ("COMBO", "bull-sl0.3-rr3",      dict(rr_target=3.0, sl_buffer_atr=0.30, direction_filter="bull")),
    ("COMBO", "bull-sl0.5-rr2",      dict(rr_target=2.0, sl_buffer_atr=0.50, direction_filter="bull")),
    ("COMBO", "bull-sl0.5-rr3",      dict(rr_target=3.0, sl_buffer_atr=0.50, direction_filter="bull")),
    ("COMBO", "bull-2024-sl0.3-rr2", dict(rr_target=2.0, sl_buffer_atr=0.30, direction_filter="bull", start_date="2024-01-01")),
    ("COMBO", "bull-2024-sl0.3-rr3", dict(rr_target=3.0, sl_buffer_atr=0.30, direction_filter="bull", start_date="2024-01-01")),
]

QUICK_FAMILIES = {"BASELINE", "DIRECTION", "COMBO"}


# ── Engine wrapper — adds direction_filter support ─────────────────────────────

def _run_setup(h4: pd.DataFrame, m5: pd.DataFrame, cfg: dict) -> tuple[dict, dict]:
    """Extract direction_filter from cfg, pass the rest to run_backtest."""
    direction = cfg.pop("direction_filter", "both")
    start     = cfg.pop("start_date", None)
    end       = cfg.pop("end_date", None)

    trades, meta = run_backtest(
        h4, m5,
        start_date=start,
        end_date=end,
        **cfg,
    )

    # Apply direction filter post-run (no re-simulation needed)
    if direction in ("bull", "bear") and not trades.empty:
        trades = trades[trades["direction"] == direction].copy()

    stats = summarize(trades)
    return stats, meta


# ── Printing ──────────────────────────────────────────────────────────────────

def _header() -> None:
    print("=" * 100)
    print(f"  {'Family':<12}  {'Name':<26}  {'N':>4}  {'WR%':>5}  {'TotalR':>8}  "
          f"{'AvgR':>7}  {'PF':>5}  {'MaxDD':>7}  {'MaxStr':>6}")
    print("=" * 100)


def _row(family: str, name: str, s: dict) -> None:
    print(
        f"  {family:<12}  {name:<26}  {s['n']:>4}  {s['win_rate']:>5}  "
        f"{s['total_r']:>+8.2f}  {s['avg_r']:>+7.3f}  {s['pf']:>5}  "
        f"{s['max_dd']:>7.2f}  {s['max_loss_streak']:>6}"
    )


def _separator(family: str, prev_family: list[str]) -> None:
    if prev_family and prev_family[0] != family:
        print("-" * 100)
    prev_family[0] = family


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="ICT strategy multi-setup sweep")
    parser.add_argument("--quick", action="store_true",
                        help="Run only BASELINE, DIRECTION and COMBO families")
    parser.add_argument("--csv", default=None, metavar="PATH",
                        help="Save all results to this CSV path")
    args = parser.parse_args()

    # ── Load data once ────────────────────────────────────────────────────────
    print("Loading data...", flush=True)
    try:
        h4 = load_h4(DATA_DIR)
        m5 = load_m5(DATA_DIR)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    print(f"  4H: {len(h4):,} bars  {h4.index.min().date()} -> {h4.index.max().date()}")
    print(f"  5M: {len(m5):,} bars  {m5.index.min().date()} -> {m5.index.max().date()}")

    setups = [(f, n, dict(cfg)) for f, n, cfg in SETUPS
              if not args.quick or f in QUICK_FAMILIES]

    print(f"\nRunning {len(setups)} setups...\n", flush=True)

    rows: list[dict] = []
    prev_fam: list[str] = [""]
    _header()
    t0 = time.perf_counter()

    for family, name, cfg in setups:
        stats, _meta = _run_setup(h4, m5, cfg)
        _separator(family, prev_fam)
        _row(family, name, stats)
        rows.append({
            "family": family,
            "name": name,
            **{k: v for k, v in stats.items() if k != "exits"},
        })

    elapsed = time.perf_counter() - t0
    print("=" * 100)
    print(f"\n  Done in {elapsed:.1f}s.\n")

    # ── Best performers ───────────────────────────────────────────────────────
    df = pd.DataFrame(rows)
    enough = df[df["n"] >= 10].copy()

    if not enough.empty:
        print("-- Top 5 by Profit Factor (>=10 trades) --------------------")
        top = enough.nlargest(5, "pf")[["family", "name", "n", "win_rate", "total_r", "pf", "max_dd"]]
        print(top.to_string(index=False))
        print()
        print("-- Top 5 by Total R (>=10 trades) --------------------------")
        top2 = enough.nlargest(5, "total_r")[["family", "name", "n", "win_rate", "total_r", "pf", "max_dd"]]
        print(top2.to_string(index=False))
        print()

    # ── Save ─────────────────────────────────────────────────────────────────
    if args.csv:
        out = Path(args.csv) if Path(args.csv).is_absolute() else _ROOT / args.csv
        df.to_csv(out, index=False)
        print(f"Results saved -> {out}")
    else:
        out = _ROOT / "setup_results.csv"
        df.to_csv(out, index=False)
        print(f"Results saved -> {out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
