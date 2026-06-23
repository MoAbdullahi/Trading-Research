"""Gold CRT sweep-reversal backtest — H4 range + 5M entry variant.

Same CRT logic as run_gold_backtest.py (H4 structure, MSS, OB_ONLY) but
driven by 5-minute bars.  Finer OB boundaries; expect tighter stops, slightly
higher RR on passing trades.

Pre-committed kill criterion (identical to M15 run — do not adjust post-hoc):
  PASS requires ALL of:
    1. >= 150 closed trades over the test window
    2. avg_R (expected value per trade) >= +0.2 R

Usage:
    python run_gold_backtest_5m.py --data "C:/path/to/XAUUSD_M5.parquet"
    python run_gold_backtest_5m.py --data ... --start 2025-01-01 --end 2025-05-30
    python run_gold_backtest_5m.py --data ... --max-hold 96 --displacement-atr 1.0

Notes:
  --max-hold N   : force-close after N M5 bars (default 96 = 8h at 5-min bars)
  --rr-min       : gateway RR floor (default 1.5)
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

KILL_MIN_TRADES = 150
KILL_MIN_EV_R = 0.2

BAR_MINUTES = 5
# 4 H4 candles * 48 M5 bars each = 192 bars minimum warmup
MIN_BARS_WARMUP = 192


def main() -> None:
    ap = argparse.ArgumentParser(description="Gold CRT sweep-reversal backtest (H4 + 5M entry)")
    ap.add_argument("--data", required=True, help="Path to XAUUSD_M5.parquet")
    ap.add_argument("--start", default=None, help="ISO start date UTC (inclusive)")
    ap.add_argument("--end", default=None, help="ISO end date UTC (inclusive)")
    ap.add_argument("--max-hold", type=int, default=96,
                    help="Max M5 bars per trade (default 96 = 8 h at 5-min bars)")
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
    print(f"  {n_bars} M5 bars | {df.index[0]} -> {df.index[-1]} ({span_days} days)")

    hold_hours = args.max_hold * BAR_MINUTES / 60
    print(f"Running CRT replay H4+5M (max_hold={args.max_hold} bars = {hold_hours:.1f} h, "
          f"disp={args.displacement_atr}xATR, rr_min={args.rr_min}) ...")

    params = CRTParams(
        displacement_atr_mult=args.displacement_atr,
        sweep_buffer_atr=args.sweep_buffer_atr,
        min_m15_bars=MIN_BARS_WARMUP,  # scaled for 5M: 4 H4 candles × 48 bars
    )
    provider = CRTSignalProvider(params=params)

    cfg = ReplayConfig(
        asset_class=AssetClass.GOLD,
        max_hold_bars=args.max_hold,
        consensus_threshold=2,
        exit_mode=args.exit_mode,
        target_mode="structural",
        warmup_bars=MIN_BARS_WARMUP,
    )

    limits = RiskLimits(min_reward_to_risk=args.rr_min)
    report = run_replay("XAUUSD", df, provider, cfg, risk_limits=limits)
    summary = report.summary()

    n_trades = summary.get("trades", 0)
    ev = summary.get("avg_R", 0.0)

    print()
    print("=" * 60)
    print("GOLD CRT BACKTEST (H4 + 5M ENTRY)  --  RESULTS")
    print("=" * 60)
    print(json.dumps(summary, indent=2))
    print()

    print("KILL CRITERION CHECK")
    print(f"  trades : need >= {KILL_MIN_TRADES}  ->  got {n_trades}  "
          f"{'PASS' if n_trades >= KILL_MIN_TRADES else 'FAIL'}")
    print(f"  EV/trade: need >= {KILL_MIN_EV_R:.2f} R  ->  got {ev:.3f} R  "
          f"{'PASS' if ev >= KILL_MIN_EV_R else 'FAIL'}")
    print()

    if n_trades < KILL_MIN_TRADES:
        print("NOTE: insufficient trades — extend date range for kill criterion evaluation.")
        sys.exit(0)

    if ev < KILL_MIN_EV_R:
        print("VERDICT: KILL  --  EV below threshold. Gold CRT (5M entry) thesis dead.")
        sys.exit(1)

    print("VERDICT: PASS  --  Proceed to macro conditioning test.")
    sys.exit(0)


if __name__ == "__main__":
    main()
