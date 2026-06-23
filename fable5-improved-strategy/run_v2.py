"""
Walk-forward runner for the v2 engines.
Train: data start -> 2024-12-31   |   Test (untouched): 2025-01-01 -> data end
All results are NET of costs (round-trip spread + stop slippage).

Usage:
    python run_v2.py --strategy po3
    python run_v2.py --strategy crt
    python run_v2.py --strategy ict
"""
from __future__ import annotations
import argparse
from pathlib import Path
import pandas as pd

from v2_common import resample_h4_ny, summarize, COSTS
from po3_engine_v2 import run_po3_v2
from crt_engine_v2 import run_crt_v2
from ict_ob_engine_v2 import run_ict_v2

HERE = Path(__file__).resolve().parent
_CANDIDATES = [HERE / "data",
               HERE.parent / "data",
               HERE.parent / "GOLD_CRT_ICT_PD_Array_Strategy" / "data"]
DATA = next((p for p in _CANDIDATES if p.exists()), _CANDIDATES[0])
OUT = HERE / "results_v2"
OUT.mkdir(exist_ok=True)

TRAIN = dict(start_date=None, end_date="2024-12-31")
TEST = dict(start_date="2025-01-01", end_date=None)
PERIODS = [("train", TRAIN), ("test", TEST)]


def _tz(df):
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    df.index = df.index.as_unit("ns")   # parquet may store ms — .asi8 must be ns
    return df.sort_index()


def load(tf, symbol):
    return _tz(pd.read_parquet(DATA / tf / f"{symbol}_{tf.upper()}.parquet"))


def add_rows(rows, strategy, cfg_name, period, trades):
    s = summarize(trades, "net_r")
    g = summarize(trades, "realized_r") if len(trades) else s
    rows.append({"strategy": strategy, "config": cfg_name, "period": period,
                 "n": s["n"], "win_rate": s["win_rate"],
                 "gross_r": g["total_r"], "net_r": s["total_r"],
                 "pf_net": s["pf"], "max_dd_net": s["max_dd"],
                 "avg_cost_r": round(trades["cost_r"].mean(), 3) if len(trades) else 0.0})
    print(f"{strategy:4s} {cfg_name:24s} {period:5s} n={s['n']:5d} wr={s['win_rate']:5.1f}% "
          f"gross={g['total_r']:+8.1f} net={s['total_r']:+8.1f} pf={s['pf']:5.2f} dd={s['max_dd']:6.1f}")


def run_po3(rows):
    m15, m5 = load("m15", "XAUUSD"), load("m5", "XAUUSD")
    c = COSTS["XAUUSD"]
    cfgs = {
        "v1-parity+costs": dict(regime_filter=False),
        "regime": dict(regime_filter=True),
        "regime+fvg": dict(regime_filter=True, require_fvg=True),
        "regime+pd": dict(regime_filter=True, pd_filter=True),
        "regime+fvg+pd": dict(regime_filter=True, require_fvg=True, pd_filter=True),
        "regime+structTP": dict(regime_filter=True, tp_mode="structure"),
    }
    for name, kw in cfgs.items():
        for pname, pkw in PERIODS:
            tr, _ = run_po3_v2(m15, m5, spread=c["spread"], slip_atr=c["slip_atr"], **kw, **pkw)
            add_rows(rows, "po3", name, pname, tr)
            if name in ("regime", "regime+structTP"):
                tr.to_csv(OUT / f"po3_{name.replace('+', '_')}_{pname}_trades.csv", index=False)


def run_po3_m15(rows):
    """H1 sweeps + M15 entries + D1 SMA200 regime — lower cost-per-R variant."""
    m15 = load("m15", "XAUUSD")
    h1 = _tz(pd.read_parquet(DATA / "h4" / "XAUUSD_H1_raw.parquet"))
    d1 = _tz(pd.read_parquet(DATA / "daily" / "XAUUSD_D1.parquet"))
    c = COSTS["XAUUSD"]
    base = dict(sweep_bar_minutes=60, swing_lookback=20, max_sweep_bars=8,
                max_hold_bars=64, pd_lookback=24,
                spread=c["spread"], slip_atr=c["slip_atr"])
    cfgs = {
        "m15-noregime": dict(regime_filter=False),
        "m15-regime": dict(regime_filter=True),
        "m15-regime+fvg": dict(regime_filter=True, require_fvg=True),
        "m15-regimeD1": dict(regime_filter=True, regime_daily=d1),
        "m15-regimeD1+fvg": dict(regime_filter=True, regime_daily=d1, require_fvg=True),
    }
    for name, kw in cfgs.items():
        for pname, pkw in PERIODS:
            tr, _ = run_po3_v2(h1, m15, **base, **kw, **pkw)
            add_rows(rows, "po3-m15", name, pname, tr)
            if name in ("m15-regimeD1+fvg", "m15-regime+fvg"):
                tr.to_csv(OUT / f"po3m15_{name.replace('+', '_')}_{pname}_trades.csv", index=False)


def run_crt(rows):
    m15, m5 = load("m15", "GBPUSD"), load("m5", "GBPUSD")
    h4 = resample_h4_ny(m15)
    c = COSTS["GBPUSD"]
    for name, kw in {"minrr0": dict(min_rr=0.0), "minrr2": dict(min_rr=2.0)}.items():
        for pname, pkw in PERIODS:
            tr, _ = run_crt_v2(h4, m5, spread=c["spread"], slip_atr=c["slip_atr"], **kw, **pkw)
            add_rows(rows, "crt", name, pname, tr)
            if name == "minrr2":
                tr.to_csv(OUT / f"crt_minrr2_{pname}_trades.csv", index=False)


def run_ict(rows):
    m15, m5 = load("m15", "XAUUSD"), load("m5", "XAUUSD")
    h4 = resample_h4_ny(m15)
    c = COSTS["XAUUSD"]
    for name, kw in {"base": dict(regime_filter=False), "regime": dict(regime_filter=True)}.items():
        for pname, pkw in PERIODS:
            tr, _ = run_ict_v2(h4, m5, spread=c["spread"], slip_atr=c["slip_atr"], **kw, **pkw)
            add_rows(rows, "ict", name, pname, tr)
            if name == "regime":
                tr.to_csv(OUT / f"ict_regime_{pname}_trades.csv", index=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", choices=["po3", "po3m15", "crt", "ict"], required=True)
    args = ap.parse_args()
    rows = []
    {"po3": run_po3, "po3m15": run_po3_m15, "crt": run_crt, "ict": run_ict}[args.strategy](rows)
    df = pd.DataFrame(rows)
    f = OUT / "summary.csv"
    if f.exists():
        old = pd.read_csv(f)
        old = old[old["strategy"] != args.strategy]
        df = pd.concat([old, df], ignore_index=True)
    df.to_csv(f, index=False)
    print("\nsaved -> " + str(f))


if __name__ == "__main__":
    main()
