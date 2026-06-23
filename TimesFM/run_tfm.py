"""
Walk-forward runner for the TimesFM-direction test.

Train: data start -> 2024-12-31   |   Test (untouched): 2025-01-01 -> data end
All results are NET of costs (round-trip spread + stop slippage).

Examples
--------
    python run_tfm.py --forecaster baseline
    python run_tfm.py --forecaster timesfm
    python run_tfm.py --forecaster timesfm --stride 8 --min-move-frac 0.0005
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

from v2_common import resample_h4_ny, summarize, COSTS  # noqa: E402
from tfm_engine import run_tfm  # noqa: E402

_CANDIDATES = [HERE / "data"]
DATA = next((p for p in _CANDIDATES if p.exists()), _CANDIDATES[0])
OUT = HERE / "results"
OUT.mkdir(exist_ok=True)

TRAIN = dict(start_date=None, end_date="2024-12-31")
TEST = dict(start_date="2025-01-01", end_date=None)
PERIODS = [("train", TRAIN), ("test", TEST)]


def _tz(df):
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    df.index = df.index.as_unit("ns")
    return df.sort_index()


def load(tf, symbol):
    return _tz(pd.read_parquet(DATA / tf / f"{symbol}_{tf.upper()}.parquet"))


def add_row(rows, fc, mode, period, trades):
    s = summarize(trades, "net_r")
    g = summarize(trades, "realized_r") if len(trades) else s
    rows.append({"forecaster": fc, "level_mode": mode, "period": period,
                 "n": s["n"], "win_rate": s["win_rate"],
                 "gross_r": g["total_r"], "net_r": s["total_r"],
                 "pf_net": s["pf"], "max_dd_net": s["max_dd"],
                 "avg_cost_r": round(trades["cost_r"].mean(), 3) if len(trades) else 0.0})
    print(f"{fc:14s} {mode:9s} {period:5s} n={s['n']:5d} wr={s['win_rate']:5.1f}% "
          f"gross={g['total_r']:+8.1f} net={s['total_r']:+8.1f} "
          f"pf={s['pf']:5.2f} dd={s['max_dd']:6.1f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="XAUUSD")
    ap.add_argument("--ltf", default="m15", help="entry timeframe (m15/m5)")
    ap.add_argument("--forecaster", default="baseline",
                    choices=["baseline", "timesfm"])
    ap.add_argument("--level-mode", default="both",
                    choices=["both", "swing", "h4candle"])
    ap.add_argument("--rr", type=float, default=3.0)
    ap.add_argument("--horizon", type=int, default=6, help="H4 bars ahead")
    ap.add_argument("--min-move-frac", type=float, default=0.0015)
    ap.add_argument("--max-hold", type=int, default=64)
    ap.add_argument("--stride", type=int, default=4,
                    help="TimesFM only: forecast every Nth H4 bar and forward-fill "
                         "between recomputes. Higher = much faster. 1 = every bar.")
    ap.add_argument("--context", type=int, default=512,
                    help="TimesFM only: H4 context length fed to the model.")
    args = ap.parse_args()

    m_ltf = load(args.ltf, args.symbol)
    h4 = resample_h4_ny(load("m15", args.symbol))
    c = COSTS.get(args.symbol, {"spread": 0.25, "slip_atr": 0.05})

    fc_kw = dict(horizon=args.horizon, min_move_frac=args.min_move_frac)
    if args.forecaster == "timesfm":
        fc_kw.update(stride=args.stride, context=args.context)
    modes = ["swing", "h4candle"] if args.level_mode == "both" else [args.level_mode]

    from direction_model import make_forecaster
    forecaster = make_forecaster(args.forecaster, **fc_kw)

    rows = []
    for mode in modes:
        for pname, pkw in PERIODS:
            trades, _ = run_tfm(
                h4, m_ltf, forecaster=forecaster, level_mode=mode,
                rr=args.rr, max_hold_bars=args.max_hold,
                spread=c["spread"], slip_atr=c["slip_atr"], **pkw)
            add_row(rows, forecaster.name, mode, pname, trades)
            if len(trades):
                trades.to_csv(
                    OUT / f"tfm_{args.forecaster}_{mode}_{pname}_trades.csv",
                    index=False)

    df = pd.DataFrame(rows)
    f = OUT / "summary.csv"
    df.to_csv(f, index=False)
    print("\nsaved -> " + str(f))


if __name__ == "__main__":
    main()
