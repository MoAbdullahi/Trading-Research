"""Walk-forward + regime + cross-instrument validation of D1 trend-following.
Self-contained. Strategies return (entry_ts, exit_ts, R) so trades can be
bucketed by period/year and merged across instruments into a basket."""
from __future__ import annotations
import json
import numpy as np
import pandas as pd

SLIP = 2.0 / 10_000.0

def load(path, start=None, end=None):
    df = pd.read_parquet(path)
    if not isinstance(df.index, pd.DatetimeIndex):
        df = df.set_index("timestamp")
    df.index = df.index.tz_localize("UTC") if df.index.tz is None else df.index.tz_convert("UTC")
    df = df.sort_index()
    if start: df = df[df.index >= pd.Timestamp(start, tz="UTC")]
    if end:   df = df[df.index <= pd.Timestamp(end, tz="UTC")]
    return df[["open","high","low","close"]]

def to_d1(df):
    o = df.resample("1D").agg({"open":"first","high":"max","low":"min","close":"last"}).dropna()
    return o

def atr_arr(df, p=14):
    pc = df["close"].shift(1)
    tr = pd.concat([df["high"]-df["low"],(df["high"]-pc).abs(),(df["low"]-pc).abs()],axis=1).max(axis=1)
    return tr.ewm(alpha=1.0/p, adjust=False).mean().to_numpy()

def donchian(df, lookback=55, atr_mult=3.0, atr_p=14):
    h=df["high"].to_numpy(); l=df["low"].to_numpy(); c=df["close"].to_numpy(); o=df["open"].to_numpy()
    ix=df.index; up=pd.Series(h).rolling(lookback).max().shift(1).to_numpy()
    lo=pd.Series(l).rolling(lookback).min().shift(1).to_numpy(); a=atr_arr(df,atr_p)
    n=len(df); tr=[]; i=lookback+1; pos=0; entry=stop=risk=0.0; ent_ts=None
    while i<n-1:
        if pos==0:
            ls=c[i]>up[i]; ss=c[i]<lo[i]
            if ls or ss:
                side=1 if ls else -1
                entry=o[i+1]*(1+SLIP) if side==1 else o[i+1]*(1-SLIP)
                stop=entry-atr_mult*a[i] if side==1 else entry+atr_mult*a[i]
                risk=abs(entry-stop); pos=side; ent_ts=ix[i+1]; i+=1; continue
        else:
            if pos==1:
                stop=max(stop,h[i]-atr_mult*a[i])
                if l[i]<=stop: tr.append((ent_ts,ix[i],(stop*(1-SLIP)-entry)/risk)); pos=0
            else:
                stop=min(stop,l[i]+atr_mult*a[i])
                if h[i]>=stop: tr.append((ent_ts,ix[i],(entry-stop*(1+SLIP))/risk)); pos=0
        i+=1
    if pos!=0: tr.append((ent_ts,ix[-1],((c[-1]-entry) if pos==1 else (entry-c[-1]))/risk))
    return tr

def ema_cross(df, fast=50, slow=200, atr_mult=3.0, atr_p=14):
    c=df["close"]; ef=c.ewm(span=fast,adjust=False).mean().to_numpy(); es=c.ewm(span=slow,adjust=False).mean().to_numpy()
    cc=c.to_numpy(); o=df["open"].to_numpy(); h=df["high"].to_numpy(); l=df["low"].to_numpy(); ix=df.index; a=atr_arr(df,atr_p)
    n=len(df); tr=[]; i=slow+1; pos=0; entry=stop=risk=0.0; ent_ts=None
    while i<n-1:
        up=ef[i]>es[i]; dn=ef[i]<es[i]
        if pos==0:
            if up or dn:
                side=1 if up else -1
                entry=o[i+1]*(1+SLIP) if side==1 else o[i+1]*(1-SLIP)
                stop=entry-atr_mult*a[i] if side==1 else entry+atr_mult*a[i]
                risk=abs(entry-stop); pos=side; ent_ts=ix[i+1]; i+=1; continue
        elif pos==1:
            stop=max(stop,h[i]-atr_mult*a[i])
            if l[i]<=stop: tr.append((ent_ts,ix[i],(stop*(1-SLIP)-entry)/risk)); pos=0
            elif dn: tr.append((ent_ts,ix[i],(o[i]*(1-SLIP)-entry)/risk)); pos=0
        else:
            stop=min(stop,l[i]+atr_mult*a[i])
            if h[i]>=stop: tr.append((ent_ts,ix[i],(entry-stop*(1+SLIP))/risk)); pos=0
            elif up: tr.append((ent_ts,ix[i],(entry-o[i]*(1+SLIP))/risk)); pos=0
        i+=1
    if pos!=0: tr.append((ent_ts,ix[-1],((cc[-1]-entry) if pos==1 else (entry-cc[-1]))/risk))
    return tr

def stats(trs):
    rs=np.array([t[2] for t in trs],float) if trs else np.array([])
    n=len(rs)
    if n==0: return {"trades":0,"avg_R":None,"total_R":0.0,"PF":None,"maxDD_R":0.0,"win%":None}
    wins=rs[rs>0]; gl=-rs[rs<=0].sum(); cum=np.cumsum(rs)
    return {"trades":n,"win%":round(100*float((rs>0).mean()),1),"avg_R":round(float(rs.mean()),3),
            "total_R":round(float(rs.sum()),1),"PF":round(float(wins.sum()/gl),2) if gl>0 else None,
            "maxDD_R":round(float((cum-np.maximum.accumulate(cum)).min()),1)}

def bucket(trs, lo, hi):
    return [t for t in trs if lo<=t[0]<hi]

def main():
    XAU="/sessions/awesome-loving-euler/mnt/data/daily/XAUUSD_D1.parquet"
    GBP="/sessions/awesome-loving-euler/mnt/data/m15/GBPUSD_M15.parquet"
    xau=load(XAU)
    gbp=to_d1(load(GBP))
    print(f"XAUUSD D1: {len(xau)} bars {xau.index[0].date()}->{xau.index[-1].date()}")
    print(f"GBPUSD D1 (resampled): {len(gbp)} bars {gbp.index[0].date()}->{gbp.index[-1].date()}\n")

    systems={"Donchian-20":lambda d:donchian(d,20),"Donchian-55":lambda d:donchian(d,55),
             "EMA50/200":lambda d:ema_cross(d,50,200)}
    T=pd.Timestamp("2024-06-01",tz="UTC")
    report={}

    for inst,df in [("XAUUSD",xau),("GBPUSD",gbp)]:
        report[inst]={}
        for name,fn in systems.items():
            trs=fn(df)
            report[inst][name]={
                "ALL":stats(trs),
                "TRAIN 21-24":stats([t for t in trs if t[0]<T]),
                "TEST 24-26":stats([t for t in trs if t[0]>=T]),
                "by_year":{str(y):stats(bucket(trs,pd.Timestamp(f"{y}-01-01",tz="UTC"),pd.Timestamp(f"{y+1}-01-01",tz="UTC")))
                           for y in range(2021,2027)},
            }

    # 2-instrument basket on Donchian-55: merge trades, equity by exit order
    basket={}
    for name in systems:
        merged=[]
        for inst,df in [("XAUUSD",xau),("GBPUSD",gbp)]:
            merged+= [(t[1],t[2]) for t in systems[name](df)]  # (exit_ts, R)
        merged.sort(key=lambda x:x[0])
        rs=np.array([m[1] for m in merged],float)
        cum=np.cumsum(rs); 
        basket[name]={"trades":len(rs),"avg_R":round(float(rs.mean()),3),"total_R":round(float(rs.sum()),1),
                      "maxDD_R":round(float((cum-np.maximum.accumulate(cum)).min()),1)}
    report["BASKET (XAU+GBP)"]=basket
    print(json.dumps(report,indent=2,default=str))
    open("/sessions/awesome-loving-euler/mnt/outputs/wf_results.json","w").write(json.dumps(report,indent=2,default=str))

if __name__=="__main__": main()
