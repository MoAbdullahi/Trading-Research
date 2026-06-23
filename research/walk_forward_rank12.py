"""
walk_forward_rank12.py
======================
Walk-forward validation of Rank #12 setup:
  H4-M5 | OB_only | Confirm(MSS) | GO_Sessions | Strong_OFF | PD_OFF

Calendar split across all 6 instruments:
  Training (IS):  2022-05-12 -> 2024-12-31  (in-sample)
  Testing  (OOS): 2025-01-01 -> 2026-01-31  (out-of-sample)
"""
import sys
import numpy as np
import pandas as pd
from pathlib import Path

ROOT      = Path(r"C:\Users\Hashim\Desktop\CRT + ICT PD Array Research\Python_Project")
DATA_PATH = Path(r"C:\Users\Hashim\Desktop\CRT + ICT PD Array Research\data")
sys.path.insert(0, str(ROOT))
from engine.phase2_engine import run_backtest, GO_SESSIONS, SPREADS

INSTRUMENTS = list(SPREADS.keys())

SETUP = dict(
    htf_freq         = "4h",
    ltf_freq         = "5min",
    scheme           = "A",
    sessions         = list(GO_SESSIONS),
    strong_filter    = False,
    min_atr_ratio    = 0.5,
    entry_pref       = "OB",
    require_mss      = True,
    require_pd_filter= False,
    stop_buffer_atr  = 0.1,
    data_path        = DATA_PATH,
)

PERIODS = {
    "TRAINING (IS)":  ("2022-05-12", "2024-12-31"),
    "TEST (OOS)":     ("2025-01-01", "2026-01-31"),
}

# ── Per-instrument detail header ─────────────────────────────────────────────
HDR = f"  {'Instrument':10s} {'N':>5} {'WR%':>6} {'AvgR':>7} {'TotalR':>9} {'PF':>6} {'MaxDD':>7}"

def run_period(start, end):
    agg = dict(n=0, wins=0, total_r=0.0, gw=0.0, gl=0.0, all_r=[], sq_r=0.0)
    print(HDR)
    print("  " + "-"*65)
    for inst in INSTRUMENTS:
        try:
            trades, _ = run_backtest(
                instrument=inst,
                start_date=start,
                end_date=end,
                **SETUP,
            )
        except Exception as e:
            print(f"  {inst:10s} ERROR: {e}")
            continue
        if len(trades) == 0:
            print(f"  {inst:10s} {'0':>5}  --  no trades")
            continue
        r = trades["realized_r"]
        n   = len(r)
        wr  = 100 * (r > 0).sum() / n
        tr  = r.sum()
        ar  = tr / n
        gw_ = r[r > 0].sum()
        gl_ = abs(r[r < 0].sum())
        pf_ = round(gw_/gl_, 2) if gl_ > 0 else 999
        cum = r.cumsum()
        dd  = round((cum.cummax() - cum).max(), 2)
        print(f"  {inst:10s} {n:5d} {wr:6.1f} {ar:7.3f} {tr:9.2f} {pf_:6.2f} {dd:7.2f}")
        agg["n"]      += n
        agg["wins"]   += (r > 0).sum()
        agg["total_r"]+= tr
        agg["gw"]     += gw_
        agg["gl"]     += gl_
        agg["all_r"]  .extend(r.tolist())
        agg["sq_r"]   += (r**2).sum()

    n  = agg["n"]
    if n == 0:
        print("  No trades in this period.")
        return None

    tr  = agg["total_r"]
    ar  = tr / n
    wr  = 100 * agg["wins"] / n
    pf_ = round(agg["gw"] / agg["gl"], 2) if agg["gl"] > 0 else 999
    cum = pd.Series(agg["all_r"]).cumsum()
    dd  = round((cum.cummax() - cum).max(), 2)
    std_r  = np.sqrt(max(agg["sq_r"]/n - ar**2, 0))
    sharpe = round(ar / std_r, 3) if std_r > 0 else 0
    calmar = round(tr / dd, 2)    if dd  > 0 else 999

    print("  " + "-"*65)
    print(f"  {'TOTAL':10s} {n:5d} {wr:6.1f} {ar:7.3f} {tr:9.2f} {pf_:6.2f} {dd:7.2f}")
    print(f"  Sharpe: {sharpe}   Calmar: {calmar}   Std(R): {std_r:.4f}")
    return dict(n=n, wr=round(wr,1), avg_r=round(ar,3), total_r=round(tr,2),
                pf=pf_, max_dd=dd, sharpe=sharpe, calmar=calmar)


results = {}
for label, (s, e) in PERIODS.items():
    print()
    print("=" * 70)
    print(f"  {label}  ({s}  to  {e})")
    print("=" * 70)
    results[label] = run_period(s, e)

# ── Walk-forward comparison table ────────────────────────────────────────────
IS  = results.get("TRAINING (IS)")
OOS = results.get("TEST (OOS)")

if IS and OOS:
    print()
    print("=" * 70)
    print("  WALK-FORWARD COMPARISON")
    print("=" * 70)
    keys = ["n", "wr", "avg_r", "total_r", "pf", "max_dd", "calmar", "sharpe"]
    labels = ["Trades", "WR %", "Avg R", "Total R", "Prof Factor", "Max DD", "Calmar", "Sharpe"]
    print(f"  {'Metric':<14} {'IS (Train)':>12} {'OOS (Test)':>12} {'OOS/IS':>9}")
    print("  " + "-"*52)
    for k, lbl in zip(keys, labels):
        iv = IS[k]; ov = OOS[k]
        if iv and iv != 0 and k not in ("max_dd",):
            ratio = f"{ov/iv:.1%}"
        elif k == "max_dd":
            ratio = "(lower=better)"
        else:
            ratio = "N/A"
        print(f"  {lbl:<14} {str(iv):>12} {str(ov):>12} {ratio:>9}")

    print()
    wr_ret = OOS["wr"] / IS["wr"]
    ar_ret = OOS["avg_r"] / IS["avg_r"] if IS["avg_r"] else 0
    pf_ret = OOS["pf"]   / IS["pf"]

    if   wr_ret >= 0.92 and ar_ret >= 0.80 and OOS["pf"] >= 1.5:
        verdict = "STRONG PASS  -- edge is robust out-of-sample"
    elif wr_ret >= 0.85 and ar_ret >= 0.65 and OOS["pf"] > 1.2:
        verdict = "PASS         -- edge holds OOS with minor degradation"
    elif wr_ret >= 0.75 and OOS["total_r"] > 0:
        verdict = "MARGINAL     -- edge weakens but remains positive"
    else:
        verdict = "FAIL         -- edge does NOT hold out-of-sample"

    print(f"  WR retention:   {wr_ret:.1%}")
    print(f"  AvgR retention: {ar_ret:.1%}")
    print(f"  PF retention:   {pf_ret:.1%}")
    print()
    print(f"  >> VERDICT: {verdict}")

print()
print("DONE.")
