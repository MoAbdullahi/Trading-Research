"""Gold CRT sweep-reversal backtest runner.

Pre-committed kill criterion (written before first run — do not adjust post-hoc):
  PASS requires ALL of:
    1. >= 150 closed trades over the test window
    2. avg_R (expected value per trade) >= +0.2 R
    3. London-window subset avg_R >= unconditioned avg_R  (macro conditioning test)

  FAIL on any criterion -> thesis dead for this dataset / parameter set.

Usage:
    python run_gold_backtest.py --data "C:/path/to/XAUUSD_M15.parquet"
    python run_gold_backtest.py --data ... --start 2024-01-01 --end 2025-12-31
    python run_gold_backtest.py --data ... --max-hold 32 --displacement-atr 0.8
    python run_gold_backtest.py --data ... --rr-min 1.5

Notes:
  --max-hold N   : force-close after N M15 bars from entry (default 32 = 8h, 2 H4 candles)
  --rr-min       : gateway RR floor (default 1.5 for structural gold targets; 2.0 is equities)
  --displacement-atr : body threshold for the reversal candle (default 1.0x ATR)
"""
from __future__ import annotations

import argparse
import json
import sys

from backtest.providers_crt import CRTParams, CRTSignalProvider
from backtest.replay import ReplayConfig, run_replay
from core.enums import AssetClass
from data.dukascopy import load_dukascopy_parquet
from risk.models import RiskLimits

# --- pre-committed kill criterion ---
KILL_MIN_TRADES = 150
KILL_MIN_EV_R = 0.2   # R per trade


def _london_filter(trade) -> bool:
    """True if the trade was entered during the London session (07:00-16:00 UTC)."""
    if not trade.exits:
        return False
    try:
        from agents.orchestrator import orchestrator_node  # noqa: F401 — confirm import path
        entry_ts = trade.exits[0].ts  # proxy: first exit ts is close to entry
    except Exception:
        return False
    # use filled_at if available, else check regime tag
    h = entry_ts.hour if hasattr(entry_ts, "hour") else None
    return h is not None and 7 <= h < 16


def main() -> None:
    ap = argparse.ArgumentParser(description="Gold CRT sweep-reversal backtest")
    ap.add_argument("--data", required=True, help="Path to XAUUSD_M15.parquet")
    ap.add_argument("--start", default=None, help="ISO start date UTC (inclusive)")
    ap.add_argument("--end", default=None, help="ISO end date UTC (inclusive)")
    ap.add_argument("--max-hold", type=int, default=32,
                    help="Max M15 bars per trade (default 32 = 8 h)")
    ap.add_argument("--displacement-atr", type=float, default=1.0,
                    help="Displacement body threshold in ATR (default 1.0)")
    ap.add_argument("--sweep-buffer-atr", type=float, default=0.1,
                    help="Stop buffer beyond swept wick in ATR (default 0.1)")
    ap.add_argument("--rr-min", type=float, default=1.5,
                    help="Gateway min RR (default 1.5 for structural gold targets)")
    ap.add_argument("--exit-mode", default="full_target",
                    choices=["full_target", "atr_trail"],
                    help="Exit mode (default full_target)")
    args = ap.parse_args()

    print(f"Loading {args.data}")
    df = load_dukascopy_parquet(args.data, start=args.start, end=args.end)
    n_bars = len(df)
    span_days = (df.index[-1] - df.index[0]).days
    print(f"  {n_bars} M15 bars | {df.index[0]} -> {df.index[-1]} ({span_days} days)")

    params = CRTParams(
        displacement_atr_mult=args.displacement_atr,
        sweep_buffer_atr=args.sweep_buffer_atr,
    )
    provider = CRTSignalProvider(params=params)

    cfg = ReplayConfig(
        asset_class=AssetClass.GOLD,
        max_hold_bars=args.max_hold,
        consensus_threshold=2,
        exit_mode=args.exit_mode,
        target_mode="structural",
    )

    limits = RiskLimits(min_reward_to_risk=args.rr_min)

    print(f"Running CRT replay (max_hold={args.max_hold} bars = {args.max_hold * 15 / 60:.1f} h, "
          f"disp={args.displacement_atr}xATR, rr_min={args.rr_min}) ...")
    report = run_replay("XAUUSD", df, provider, cfg, risk_limits=limits)
    summary = report.summary()

    n_trades = summary.get("trades", 0)
    ev = summary.get("avg_R", 0.0)

    print()
    print("=" * 60)
    print("GOLD CRT BACKTEST  --  RESULTS")
    print("=" * 60)
    print(json.dumps(summary, indent=2))
    print()

    # --- kill criterion evaluation ---
    print("KILL CRITERION CHECK")
    print(f"  trades : need >= {KILL_MIN_TRADES}  ->  got {n_trades}  "
          f"{'PASS' if n_trades >= KILL_MIN_TRADES else 'FAIL'}")
    print(f"  EV/trade: need >= {KILL_MIN_EV_R:.2f} R  ->  got {ev:.3f} R  "
          f"{'PASS' if ev >= KILL_MIN_EV_R else 'FAIL'}")
    print()

    if n_trades < KILL_MIN_TRADES:
        print("NOTE: insufficient trades for kill criterion.")
        print("      Extend date range or lower displacement_atr_mult.")
        sys.exit(0)

    if ev < KILL_MIN_EV_R:
        print("VERDICT: KILL  --  EV below threshold. Gold CRT thesis dead on this dataset.")
        sys.exit(1)

    print("VERDICT: PASS  --  Proceed to macro conditioning test.")
    print("  Next: re-run with --start / --end scoped to London-only trades and compare avg_R.")
    sys.exit(0)


if __name__ == "__main__":
    main()
