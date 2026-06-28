import warnings; warnings.filterwarnings("ignore")
import argparse, glob, os, numpy as np, pandas as pd
_ap=argparse.ArgumentParser(description="TSMOM validation: cost sweep, regimes, breadth, beta, variants")
_ap.add_argument("--data", default=os.path.join(os.path.dirname(__file__), "..", "data", "d1"),
                 help="directory of *_D1.parquet daily files (default: ../data/d1)")
_args=_ap.parse_args()
ANN=252; TARGET=0.10
files=sorted(glob.glob(os.path.join(_args.data, "**", "*_D1.parquet"), recursive=True) or glob.glob(os.path.join(_args.data, "*_D1.parquet")))
ser={}
for f in files:
    d=pd.read_parquet(f)
    d.index=d.index.tz_localize("UTC") if d.index.tz is None else d.index.tz_convert("UTC")
    ser[os.path.basename(f).split("_")[0]]=d.sort_index()["close"]
px=pd.concat(ser,axis=1).sort_index().dropna(how="all")
print(f"{px.shape[1]} instruments | {px.index[0].date()} -> {px.index[-1].date()} | {len(px)} rows")
rets=px.pct_change()
look=252
mom=px/px.shift(look)-1
sig=np.sign(mom)
vol=rets.rolling(60).std()*np.sqrt(ANN)
wt=(TARGET/vol).clip(upper=3.0)
keep=pd.Series(range(len(px)),index=px.index)%21==0
pos=(sig*wt).where(keep).ffill()
def stats(r,lbl):
    r=r.dropna()
    if len(r)<50: print(f"  {lbl}: too short"); return
    eq=(1+r).cumprod(); dd=(eq/eq.cummax()-1).min()
    print(f"  {lbl}: n={len(r)}d ann={100*((1+r.mean())**ANN-1):.1f}% vol={100*r.std()*np.sqrt(ANN):.1f}% "
          f"Sharpe={r.mean()/r.std()*np.sqrt(ANN):.2f} maxDD={100*dd:.1f}%")
port=(pos.shift(1)*rets).mean(axis=1,skipna=True)
turn=pos.diff().abs().mean(axis=1).fillna(0)
print("=== 12m TSMOM basket, vol-targeted, monthly refresh ===")
stats(port,"GROSS")
for bps in (2,5,10):
    stats(port-turn*(bps/10000.0), f"NET {bps}bps")
# regime thirds
net=(port-turn*2/10000).dropna()
idx=net.index; t=len(idx)//3
for lbl,seg in [("2015-2018",net[:t]),("2018-2022",net[t:2*t]),("2022-2026",net[2*t:])]:
    stats(seg,lbl)
print("avg pairwise |corr|:", round(rets.corr().abs().where(~np.eye(px.shape[1],dtype=bool)).stack().mean(),2))
