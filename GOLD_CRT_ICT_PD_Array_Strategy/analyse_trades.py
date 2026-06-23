"""Quick analysis of CRT trade distribution to identify improvement areas."""
import pandas as pd
import numpy as np
import sys
import warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, ".")

from engine.gold_ict_engine import load_h4, _atr

DATA_DIR = None  # uses default

trades = pd.read_csv("results/crt_trades.csv", parse_dates=["entry_time", "exit_time"])
trades["year"] = trades["entry_time"].dt.year
trades["hour_ny"] = (
    pd.to_datetime(trades["entry_time"], utc=True)
    .dt.tz_convert("America/New_York")
    .dt.hour
)

print("=== Entry hour (NY time) — R per hour ===")
by_hour = trades.groupby("hour_ny")["realized_r"].agg(["count", "sum", "mean"]).round(3)
by_hour.columns = ["trades", "total_r", "avg_r"]
print(by_hour.to_string())

print()
print("=== Win rate and R by natural RR bucket ===")
bins   = [0, 1, 1.5, 2, 3, 5, 999]
labels = ["<1R", "1-1.5R", "1.5-2R", "2-3R", "3-5R", "5R+"]
trades["rr_bucket"] = pd.cut(trades["natural_rr"], bins=bins, labels=labels)
for lbl, grp in trades.groupby("rr_bucket", observed=True):
    wr  = round(100 * (grp["realized_r"] > 0).mean(), 1)
    tot = round(grp["realized_r"].sum(), 2)
    print(f"  {str(lbl):<8}: {len(grp):>4} trades | WR {wr}% | Total R {tot:+.2f}")

print()
print("=== Bull vs Bear R by year ===")
for yr, grp in trades.groupby("year"):
    b  = grp[grp["direction"] == "bull"]
    be = grp[grp["direction"] == "bear"]
    print(f"  {yr}  Bull: {len(b):>3} trades | {round(b['realized_r'].sum(),1):+.1f}R   "
          f"Bear: {len(be):>3} trades | {round(be['realized_r'].sum(),1):+.1f}R")

print()
h4 = load_h4()
h4["atr"] = _atr(h4, 14)
avg_atr = float(h4["atr"].mean())

bull_trades = trades[trades["direction"] == "bull"].copy()
bear_trades = trades[trades["direction"] == "bear"].copy()
bull_trades["sweep_size"] = bull_trades["entry_price"] - bull_trades["ref_low"]
bear_trades["sweep_size"] = bear_trades["ref_high"] - bear_trades["entry_price"]
all_trades = pd.concat([bull_trades, bear_trades])

print(f"=== Sweep size (entry vs ref level) as ATR multiples ===")
print(f"  Avg H4 ATR : {avg_atr:.2f}")
all_trades["sweep_atr"] = all_trades["sweep_size"] / avg_atr
buckets = [0, 0.05, 0.1, 0.2, 0.5, 99]
blabels = ["<0.05", "0.05-0.1", "0.1-0.2", "0.2-0.5", ">0.5"]
all_trades["sb"] = pd.cut(all_trades["sweep_atr"], bins=buckets, labels=blabels)
for lbl, grp in all_trades.groupby("sb", observed=True):
    wr  = round(100 * (grp["realized_r"] > 0).mean(), 1)
    tot = round(grp["realized_r"].sum(), 2)
    print(f"  {str(lbl):<12}: {len(grp):>4} trades | WR {wr}% | Total R {tot:+.2f}")
