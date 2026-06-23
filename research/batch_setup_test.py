"""
batch_setup_fast.py — parallel version
========================================
Same grid as batch_setup_test.py but runs up to N_WORKERS combos in
parallel using ProcessPoolExecutor.  Each worker independently caches
parquet data (lru_cache is per-process).

Resume: reads Desktop/setup_results.csv on startup and skips done combos.
Crash-safe: saves each finished combo to CSV immediately.
"""
import sys
import time
from pathlib import Path
from itertools import product
from concurrent.futures import ProcessPoolExecutor, as_completed
import pandas as pd
import numpy as np

ROOT      = Path(r"C:\Users\Hashim\Desktop\CRT + ICT PD Array Research\Python_Project")
OUT_CSV   = Path(r"C:\Users\Hashim\Desktop\setup_results.csv")
DATA_PATH = Path(r"C:\Users\Hashim\Desktop\CRT + ICT PD Array Research\data")
INSTRUMENTS = ['EURUSD', 'GBPUSD', 'USDJPY', 'XAUUSD', 'NAS100', 'US30']
START     = "2022-05-12"
END       = "2026-01-31"
N_WORKERS = 4

# ── Parameter grid ─────────────────────────────────────────────────────────
sys.path.insert(0, str(ROOT))
from engine.phase2_engine import ALL_SESSIONS, GO_SESSIONS

TIMEFRAMES = [
    ("4h",    "15min", "H4-M15"),
    ("4h",    "5min",  "H4-M5"),
    ("1h",    "15min", "H1-M15"),
    ("1h",    "5min",  "H1-M5"),
    ("15min", "5min",  "M15-M5"),
]
ENTRY_PREFS    = [("OB","OB_only"), ("FVG","FVG_only"), ("BOTH","OB+FVG")]
ENTRY_STYLES   = [(False,"Risk(no_MSS)"), (True,"Confirm(MSS)")]
SESSION_MODES  = [(list(GO_SESSIONS),"GO_Sessions"), (list(ALL_SESSIONS),"All_Sessions")]
STRONG_FILTERS = [(True,"Strong_ON"), (False,"Strong_OFF")]
PD_FILTERS     = [(True,"PD_ON"), (False,"PD_OFF")]

combos = []
for (htf, ltf, tf_name), (ep, ep_name), (mss, mss_name), \
    (sess, sess_name), (sf, sf_name), (pf, pf_name) in product(
        TIMEFRAMES, ENTRY_PREFS, ENTRY_STYLES,
        SESSION_MODES, STRONG_FILTERS, PD_FILTERS):
    combos.append({
        "htf": htf, "ltf": ltf, "tf_name": tf_name,
        "entry_pref": ep, "ep_name": ep_name,
        "require_mss": mss, "mss_name": mss_name,
        "sessions": sess, "sess_name": sess_name,
        "strong_filter": sf, "sf_name": sf_name,
        "require_pd": pf, "pf_name": pf_name,
        "label": f"{tf_name}|{ep_name}|{mss_name}|{sess_name}|{sf_name}|{pf_name}",
    })

# ── Resume ──────────────────────────────────────────────────────────────────
done_labels = set()
if OUT_CSV.exists():
    try:
        existing = pd.read_csv(OUT_CSV)
        done_labels = set(existing["setup"].tolist())
        print(f"Resuming — {len(done_labels)} combos already done, "
              f"{len(combos) - len(done_labels)} remaining.")
    except Exception:
        pass

remaining = [c for c in combos if c["label"] not in done_labels]
print(f"Total: {len(combos)}  |  To run: {len(remaining)}  |  Workers: {N_WORKERS}")
print()

if not OUT_CSV.exists():
    pd.DataFrame(columns=[
        "setup","tf","entry","style","sessions","strong","pd",
        "n","win_rate","avg_r","total_r","pf","max_dd"
    ]).to_csv(OUT_CSV, index=False)

# ── Worker function (runs in child process) ─────────────────────────────────
def _run_combo(c, instruments, start, end, data_path_str):
    import sys
    from pathlib import Path
    _root = Path(r"C:\Users\Hashim\Desktop\CRT + ICT PD Array Research\Python_Project")
    sys.path.insert(0, str(_root))
    from engine.phase2_engine import run_backtest
    import pandas as pd

    dp = Path(data_path_str)
    agg = {"n":0,"wins":0,"total_r":0.0,"gross_win":0.0,"gross_loss":0.0,"all_r":[]}
    for inst in instruments:
        try:
            trades, _ = run_backtest(
                instrument=inst, htf_freq=c["htf"], ltf_freq=c["ltf"],
                scheme="A", sessions=c["sessions"],
                strong_filter=c["strong_filter"], min_atr_ratio=0.5,
                entry_pref=c["entry_pref"], require_mss=c["require_mss"],
                require_pd_filter=c["require_pd"], stop_buffer_atr=0.1,
                start_date=start, end_date=end, data_path=dp,
            )
            if len(trades) > 0:
                r = trades["realized_r"]
                agg["n"]          += len(trades)
                agg["wins"]       += (r > 0).sum()
                agg["total_r"]    += r.sum()
                agg["all_r"].extend(r.tolist())
                agg["gross_win"]  += r[r > 0].sum()
                agg["gross_loss"] += abs(r[r < 0].sum())
        except Exception:
            pass

    n  = agg["n"]
    tr = round(agg["total_r"], 2)
    wr = round(100 * agg["wins"] / n, 1) if n > 0 else 0
    ar = round(agg["total_r"] / n, 3)    if n > 0 else 0
    gl = agg["gross_loss"];  gw = agg["gross_win"]
    pf = round(gw/gl, 2) if gl > 0 else (999 if gw > 0 else 0)
    if agg["all_r"]:
        cum   = pd.Series(agg["all_r"]).cumsum()
        maxdd = round((cum.cummax() - cum).max(), 2)
    else:
        maxdd = 0
    return {
        "setup":c["label"],"tf":c["tf_name"],"entry":c["ep_name"],
        "style":c["mss_name"],"sessions":c["sess_name"],"strong":c["sf_name"],
        "pd":c["pf_name"],"n":n,"win_rate":wr,"avg_r":ar,
        "total_r":tr,"pf":pf,"max_dd":maxdd,
    }

# ── Parallel run ─────────────────────────────────────────────────────────────
t0      = time.time()
done    = 0
results = []

with ProcessPoolExecutor(max_workers=N_WORKERS) as pool:
    futures = {
        pool.submit(_run_combo, c, INSTRUMENTS, START, END, str(DATA_PATH)): c
        for c in remaining
    }
    for fut in as_completed(futures):
        try:
            row = fut.result()
        except Exception as ex:
            row = None
            print(f"  COMBO FAILED: {futures[fut]['label']} — {ex}")

        if row:
            pd.DataFrame([row]).to_csv(OUT_CSV, mode="a", header=False, index=False)
            results.append(row)
            done += 1
            elapsed = time.time() - t0
            rate    = done / elapsed
            eta     = (len(remaining) - done) / rate if rate > 0 else 0
            if done % 4 == 0 or done == len(remaining):
                best = max(results, key=lambda x: x["total_r"])
                print(f"  [{done:3d}/{len(remaining)}] elapsed={elapsed:.0f}s  "
                      f"eta={eta:.0f}s  best={best['setup']}  R={best['total_r']}")

print()
print(f"Session done in {time.time()-t0:.1f}s")

# ── Final ranking ─────────────────────────────────────────────────────────────
df = pd.read_csv(OUT_CSV)
df = df.sort_values("total_r", ascending=False).reset_index(drop=True)
df.index += 1
df.to_csv(OUT_CSV, index_label="rank")
print(f"Results saved: {len(df)} setups  ->  {OUT_CSV}")
print()

print("=" * 130)
print("TOP 20 SETUPS  (2022-05-12 to 2026-01-31, all 6 instruments)")
print("=" * 130)
print(f"{'Rank':>4}  {'TF':>7}  {'Entry':>7}  {'Style':>14}  {'Sessions':>12}  "
      f"{'Strong':>10}  {'P/D':>7}  {'N':>5}  {'WR%':>6}  {'AvgR':>7}  "
      f"{'TotalR':>8}  {'PF':>6}  {'MaxDD':>7}")
print("-" * 130)
for rank, row in df.head(20).iterrows():
    print(f"{rank:4d}  {row['tf']:>7}  {row['entry']:>7}  {row['style']:>14}  "
          f"{row['sessions']:>12}  {row['strong']:>10}  {row['pd']:>7}  "
          f"{row['n']:5d}  {row['win_rate']:6.1f}  {row['avg_r']:7.3f}  "
          f"{row['total_r']:8.2f}  {row['pf']:6.2f}  {row['max_dd']:7.2f}")
print()

print("BOTTOM 10 SETUPS")
print("-" * 130)
for rank, row in df.tail(10).iterrows():
    print(f"{rank:4d}  {row['tf']:>7}  {row['entry']:>7}  {row['style']:>14}  "
          f"{row['sessions']:>12}  {row['strong']:>10}  {row['pd']:>7}  "
          f"{row['n']:5d}  {row['win_rate']:6.1f}  {row['avg_r']:7.3f}  "
          f"{row['total_r']:8.2f}  {row['pf']:6.2f}  {row['max_dd']:7.2f}")
print()

print("=" * 80)
print("DIMENSION SUMMARY")
print("=" * 80)
for dim, col in [("Timeframe","tf"),("Entry Type","entry"),("Entry Style","style"),
                 ("Sessions","sessions"),("Strong Filter","strong"),("P/D Filter","pd")]:
    g = df.groupby(col)["total_r"].mean().sort_values(ascending=False)
    print(f"\n  {dim}:")
    for val, avg in g.items():
        print(f"    {val:20s}  avg_total_r = {avg:+.2f}")
print()
print("DONE.")
