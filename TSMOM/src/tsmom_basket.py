"""Time-series (absolute) momentum basket — Hurst/Ooi/Pedersen style.
Each instrument: long if its own 252d return>0 else short; sized inverse-vol
(vol target 10%/yr). Equal risk across instruments. Monthly signal refresh."""
import warnings; warnings.filterwarnings("ignore")
import argparse, glob, os, numpy as np, pandas as pd
_ap=argparse.ArgumentParser(description="TSMOM basket backtest")
_ap.add_argument("--data", default=os.path.join(os.path.dirname(__file__), "..", "data", "d1"),
                 help="directory of *_D1.parquet daily files (default: ../data/d1)")
_args=_ap.parse_args()
ANN=252; TARGET=0.10
files=sorted(glob.glob(os.path.join(_args.data, "*_D1.parquet")))
assert files, f"no *_D1.parquet found in {_args.data} — run scripts/fetch_basket_d1.py first"
ser={}
for f in files:
    d=pd.read_parquet(f); 
    d.index=d.index.tz_localize("UTC") if d.index.tz is None else d.index.tz_convert("UTC")
    ser[os.path.basename(f).split("_")[0]]=d.sort_index()["close"]
px=pd.concat(ser,axis=1).sort_index().dropna(how="all")
rets=px.pct_change()
look=252
mom=px/px.shift(look)-1
sig=np.sign(mom)                      # +1 long / -1 short
vol=rets.rolling(60).std()*np.sqrt(ANN)
wt=(TARGET/vol).clip(upper=3.0)       # inverse-vol sizing, capped
# refresh monthly (every 21d) to cut turnover
keep=pd.Series(range(len(px)),index=px.index)%21==0
pos=(sig*wt).where(keep).ffill()
port=(pos.shift(1)*rets).mean(axis=1, skipna=True)   # equal-weight across active
turn=pos.diff().abs().mean(axis=1).fillna(0)
port=port-turn*(2.0/10000)
r=port.dropna()
eq=(1+r).cumprod(); dd=(eq/eq.cummax()-1).min()
print(f"TSMOM basket (12m, vol-targeted, {px.shape[1]} instruments, {px.index[0].date()}->{px.index[-1].date()})")
print(f"  ann_return={100*((1+r.mean())**ANN-1):.1f}%  ann_vol={100*r.std()*np.sqrt(ANN):.1f}%  "
      f"Sharpe={r.mean()/r.std()*np.sqrt(ANN):.2f}  maxDD={100*dd:.1f}%")
# split by regime halves
mid=r.index[len(r)//2]
for lbl,seg in [("2014->2020",r[r.index<mid]),("2020->2026",r[r.index>=mid])]:
    if len(seg)>50:
        print(f"  {lbl}: Sharpe={seg.mean()/seg.std()*np.sqrt(ANN):.2f}  ann={100*((1+seg.mean())**ANN-1):.1f}%")
