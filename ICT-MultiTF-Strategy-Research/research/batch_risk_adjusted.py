"""
batch_risk_adjusted.py
======================
Re-runs all 240 parameter combos and ranks by risk-adjusted metrics:
  - Calmar     = Total R / Max DD
  - Sharpe     = Avg R / Std(R)   [per-trade]
  - Composite  = 0.4*Calmar + 0.4*Sharpe + 0.2*Expectancy

Resume: skips combos already in risk_adjusted_results.csv.
Saves each result immediately (crash-safe).
"""
import sys
import time
import numpy as np
import pandas as pd
from pathlib import Path
from itertools import product

ROOT      = Path(r"C:\Users\Hashim\Desktop\CRT + ICT PD Array Research\Python_Project")
DATA_PATH = Path(r"C:\Users\Hashim\Desktop\CRT + ICT PD Array Research\data")
OUT_CSV   = Path(r"C:\Users\Hashim\Desktop\risk_adjusted_results.csv")
sys.path.insert(0, str(ROOT))
from engine.phase2_engine import run_backtest, ALL_SESSIONS, GO_SESSIONS, SPREADS

INSTRUMENTS = list(SPREADS.keys())
START = "2022-05-12"
END   = "2026-01-31"

# ── Parameter grid (same as batch_setup_fast.py) ─────────────────────────────
TIMEFRAMES     = [("4h","15min","H4-M15"), ("4h","5min","H4-M5"),
                  ("1h","15min","H1-M15"), ("1h","5min","H1-M5"),
                  ("15min","5min","M15-M5")]
ENTRY_PREFS    = [("OB","OB_only"), ("FVG","FVG_only"), ("BOTH","OB+FVG")]
ENTRY_STYLES   = [(False,"Risk(no_MSS)"), (True,"Confirm(MSS)")]
SESSION_MODES  = [(list(GO_SESSIONS),"GO_Sessions"), (list(ALL_SESSIONS),"All_Sessions")]
STRONG_FILTERS = [(True,"Strong_ON"), (False,"Strong_OFF")]
PD_FILTERS     = [(True,"PD_ON"),    (False,"PD_OFF")]

combos = []
for (htf,ltf,tf_name),(ep,ep_name),(mss,mss_name),\
    (sess,sess_name),(sf,sf_name),(pf,pf_name) in product(
        TIMEFRAMES, ENTRY_PREFS, ENTRY_STYLES,
        SESSION_MODES, STRONG_FILTERS, PD_FILTERS):
    combos.append(dict(
        htf=htf, ltf=ltf, tf_name=tf_name,
        entry_pref=ep, ep_name=ep_name,
        require_mss=mss, mss_name=mss_name,
        sessions=sess, sess_name=sess_name,
        strong_filter=sf, sf_name=sf_name,
        require_pd=pf, pf_name=pf_name,
        label=f"{tf_name}|{ep_name}|{mss_name}|{sess_name}|{sf_name}|{pf_name}",
    ))

# ── Resume ────────────────────────────────────────────────────────────────────
done_labels = set()
if OUT_CSV.exists():
    try:
        existing = pd.read_csv(OUT_CSV)
        done_labels = set(existing["setup"].tolist())
        print(f"Resuming -- {len(done_labels)} done, {len(combos)-len(done_labels)} remaining.")
    except Exception:
        pass

combos = combos[:80]   # run first 80 only
remaining = [c for c in combos if c["label"] not in done_labels]
print(f"Total: {len(combos)}  |  To run: {len(remaining)}")
print()

if not OUT_CSV.exists():
    pd.DataFrame(columns=[
        "setup","tf","entry","style","sessions","strong","pd",
        "n","win_rate","avg_r","std_r","total_r","pf","max_dd",
        "calmar","sharpe","adj_sharpe",
    ]).to_csv(OUT_CSV, index=False)

# ── Single combo runner ───────────────────────────────────────────────────────
def run_combo(c):
    agg = dict(n=0, wins=0, total_r=0.0, gw=0.0, gl=0.0, all_r=[], sq_r=0.0)
    for inst in INSTRUMENTS:
        try:
            trades, _ = run_backtest(
                instrument=inst, htf_freq=c["htf"], ltf_freq=c["ltf"],
                scheme="A", sessions=c["sessions"],
                strong_filter=c["strong_filter"], min_atr_ratio=0.5,
                entry_pref=c["entry_pref"], require_mss=c["require_mss"],
                require_pd_filter=c["require_pd"], stop_buffer_atr=0.1,
                start_date=START, end_date=END, data_path=DATA_PATH,
            )
            if len(trades) > 0:
                r = trades["realized_r"]
                agg["n"]      += len(r)
                agg["wins"]   += (r > 0).sum()
                agg["total_r"]+= r.sum()
                agg["gw"]     += r[r > 0].sum()
                agg["gl"]     += abs(r[r < 0].sum())
                agg["all_r"]  .extend(r.tolist())
                agg["sq_r"]   += (r**2).sum()
        except Exception:
            pass

    n  = agg["n"]
    tr = round(agg["total_r"], 2)
    wr = round(100 * agg["wins"] / n, 1) if n > 0 else 0
    ar = round(agg["total_r"] / n, 4)    if n > 0 else 0
    gl = agg["gl"]; gw = agg["gw"]
    pf = round(gw/gl, 3) if gl > 0 else (999 if gw > 0 else 0)

    # Std(R) and Sharpe
    if n > 1:
        variance = max(agg["sq_r"]/n - ar**2, 0)
        std_r = round(np.sqrt(variance), 4)
    else:
        std_r = 0
    # Sharpe variants
    sharpe     = round(ar / std_r, 3) if std_r > 0 else 0
    # Adjusted Sharpe = (Avg R x sqrt(N)) / Std(R)  -- rewards edge strength AND sample size
    adj_sharpe = round(ar * np.sqrt(n) / std_r, 3) if std_r > 0 else 0

    # Max DD and Calmar
    if agg["all_r"]:
        cum   = pd.Series(agg["all_r"]).cumsum()
        maxdd = round((cum.cummax() - cum).max(), 2)
    else:
        maxdd = 0
    calmar = round(tr / maxdd, 3) if maxdd > 0 else (999 if tr > 0 else 0)

    return dict(
        setup=c["label"], tf=c["tf_name"], entry=c["ep_name"],
        style=c["mss_name"], sessions=c["sess_name"], strong=c["sf_name"],
        pd=c["pf_name"], n=n, win_rate=wr, avg_r=ar, std_r=std_r,
        total_r=tr, pf=pf, max_dd=maxdd,
        calmar=calmar, sharpe=sharpe, adj_sharpe=adj_sharpe,
    )

# ── Main loop ─────────────────────────────────────────────────────────────────
t0   = time.time()
done = 0
all_rows = []

for c in remaining:
    try:
        row = run_combo(c)
    except Exception as ex:
        print(f"  FAILED: {c['label']} -- {ex}")
        continue

    pd.DataFrame([row]).to_csv(OUT_CSV, mode="a", header=False, index=False)
    all_rows.append(row)
    done += 1
    elapsed = time.time() - t0
    rate    = done / elapsed
    eta     = (len(remaining) - done) / rate if rate > 0 else 0

    if done % 10 == 0 or done == len(remaining):
        best_c = max(all_rows, key=lambda x: x["calmar"])
        best_s = max(all_rows, key=lambda x: x["adj_sharpe"])
        print(f"  [{done:3d}/{len(remaining)}] elapsed={elapsed:.0f}s eta={eta:.0f}s  "
              f"best_calmar={best_c['setup']}  Calmar={best_c['calmar']}  "
              f"best_adjsharpe={best_s['setup']}  AdjSharpe={best_s['adj_sharpe']}")

print(f"\nSession done in {time.time()-t0:.1f}s")

# ── Final: compute composite rank and show tables ──────────────────────────────
df = pd.read_csv(OUT_CSV)
df = df[df["n"] >= 100].copy()  # filter noise

# Rank columns (lower rank number = better)
for col in ["calmar", "adj_sharpe", "avg_r", "total_r"]:
    df[f"_rank_{col}"] = df[col].rank(ascending=False)

# Composite: 40% Calmar (risk-adjusted return) + 40% AdjSharpe (edge x confidence) + 20% Expectancy
df["composite_score"] = (
    0.40 * df["_rank_calmar"] +
    0.40 * df["_rank_adj_sharpe"] +
    0.20 * df["_rank_avg_r"]
)
df = df.sort_values("composite_score").reset_index(drop=True)
df.index += 1

# Drop internal rank columns before saving
df_out = df.drop(columns=[c for c in df.columns if c.startswith("_rank_")])
df_out.to_csv(OUT_CSV, index_label="composite_rank")

# ── Print tables ─────────────────────────────────────────────────────────────
W = 150
print("\n" + "="*W)
print("TOP 20 BY COMPOSITE RISK-ADJUSTED SCORE  (0.4*Calmar + 0.4*Sharpe + 0.2*ExpxSharpe)")
print("="*W)
print(f"{'Rank':>4}  {'TF':>7}  {'Entry':>7}  {'Style':>14}  {'Sessions':>12}  "
      f"{'Strong':>10}  {'P/D':>7}  {'N':>5}  {'WR%':>6}  {'AvgR':>7}  "
      f"{'TotalR':>8}  {'PF':>6}  {'MaxDD':>7}  {'R/DD':>8}  {'AdjSharpe':>10}  {'Score':>8}")
print("-"*W)
for rank, row in df.head(20).iterrows():
    print(f"{rank:4d}  {row['tf']:>7}  {row['entry']:>7}  {row['style']:>14}  "
          f"{row['sessions']:>12}  {row['strong']:>10}  {row['pd']:>7}  "
          f"{row['n']:5.0f}  {row['win_rate']:6.1f}  {row['avg_r']:7.3f}  "
          f"{row['total_r']:8.2f}  {row['pf']:6.2f}  {row['max_dd']:7.2f}  "
          f"{row['calmar']:8.3f}  {row['adj_sharpe']:10.3f}  {row['composite_score']:8.1f}")

ROW_FMT = ("{rank:4d}  {tf:>7}  {entry:>7}  {style:>14}  {sessions:>12}  "
           "{strong:>10}  {pd:>7}  {n:5.0f}  {wr:6.1f}  {ar:7.3f}  "
           "{tr:8.2f}  {pf:6.2f}  {dd:7.2f}  {calmar:8.3f}  {adj_sharpe:10.3f}")

def print_table(df_, title, sort_col):
    df_ = df_.sort_values(sort_col, ascending=False).reset_index(drop=True)
    df_.index += 1
    print("\n" + "="*W)
    print(title)
    print("="*W)
    print(f"{'Rank':>4}  {'TF':>7}  {'Entry':>7}  {'Style':>14}  {'Sessions':>12}  "
          f"{'Strong':>10}  {'P/D':>7}  {'N':>5}  {'WR%':>6}  {'AvgR':>7}  "
          f"{'TotalR':>8}  {'PF':>6}  {'MaxDD':>7}  {'R/DD':>8}  {'AdjSharpe':>10}")
    print("-"*W)
    for rank, row in df_.head(20).iterrows():
        print(ROW_FMT.format(
            rank=rank, tf=row['tf'], entry=row['entry'], style=row['style'],
            sessions=row['sessions'], strong=row['strong'], pd=row['pd'],
            n=row['n'], wr=row['win_rate'], ar=row['avg_r'],
            tr=row['total_r'], pf=row['pf'], dd=row['max_dd'],
            calmar=row['calmar'], adj_sharpe=row['adj_sharpe']))

print_table(df, "TOP 20 BY CALMAR  (R / Max DD)", "calmar")
print_table(df, "TOP 20 BY ADJ SHARPE  (Avg R x sqrt(N) / Std R)", "adj_sharpe")

print("\n" + "="*W)
print("DIMENSION SUMMARY  (composite-ranked results)")
print("="*W)
for dim, col in [("Timeframe","tf"),("Entry","entry"),("Style","style"),
                 ("Sessions","sessions"),("Strong","strong"),("P/D","pd")]:
    g = df.groupby(col).agg(
        avg_calmar=("calmar","mean"),
        avg_adj_sharpe=("adj_sharpe","mean"),
        avg_total_r=("total_r","mean"),
        count=("n","count"),
    ).sort_values("avg_calmar", ascending=False)
    print(f"\n  {dim}:")
    for val, row in g.iterrows():
        print(f"    {val:20s}  R/DD={row['avg_calmar']:6.3f}  "
              f"AdjSharpe={row['avg_adj_sharpe']:7.2f}  AvgTotalR={row['avg_total_r']:+7.1f}")

print("\nDONE.")
