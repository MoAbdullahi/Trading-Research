"""Trend-following on the horizons the literature actually supports: H1, H4, D1.
Donchian breakout + chandelier ATR trailing stop, plus a daily EMA50/200 cross.
Same fill conventions (next-bar open, 2bps slip). R = move / initial ATR risk.
Also reports total % return and buy&hold for context (gold trended hard 2024-26)."""
from __future__ import annotations
import json
import numpy as np
import pandas as pd

SLIP = 2.0 / 10_000.0
FILES = {
    "H1": "/sessions/awesome-loving-euler/mnt/data/h4/XAUUSD_H1_raw.parquet",
    "H4": "/sessions/awesome-loving-euler/mnt/data/h4/XAUUSD_H4.parquet",
    "D1": "/sessions/awesome-loving-euler/mnt/data/daily/XAUUSD_D1.parquet",
}


def load(path):
    df = pd.read_parquet(path)
    if not isinstance(df.index, pd.DatetimeIndex):
        df = df.set_index("timestamp")
    df.index = df.index.tz_localize("UTC") if df.index.tz is None else df.index.tz_convert("UTC")
    return df.sort_index()[["open", "high", "low", "close"]]


def atr_arr(df, p=14):
    pc = df["close"].shift(1)
    tr = pd.concat([df["high"]-df["low"], (df["high"]-pc).abs(), (df["low"]-pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0/p, adjust=False).mean().to_numpy()


def summ(rs, label, bh):
    n=len(rs)
    if n==0: return {"strategy":label,"trades":0}
    rs=np.array(rs,float); wins=rs[rs>0]; losses=rs[rs<=0]
    gw=wins.sum(); gl=-losses.sum(); cum=np.cumsum(rs)
    mdd=float((cum-np.maximum.accumulate(cum)).min())
    pf=float(gw/gl) if gl>0 else float("inf")
    return {"strategy":label,"trades":n,"win_rate":round(float((rs>0).mean()),3),
            "avg_R":round(float(rs.mean()),3),"total_R":round(float(rs.sum()),1),
            "profit_factor":round(pf,2),"max_dd_R":round(mdd,1),
            "buy_hold_%":bh}


def donchian(df, lookback, atr_mult=3.0, atr_p=14):
    h=df["high"].to_numpy(); l=df["low"].to_numpy(); c=df["close"].to_numpy(); o=df["open"].to_numpy()
    n=len(df); up=pd.Series(h).rolling(lookback).max().shift(1).to_numpy()
    lo=pd.Series(l).rolling(lookback).min().shift(1).to_numpy(); a=atr_arr(df,atr_p)
    rs=[]; i=lookback+1; pos=0; entry=stop=risk=0.0
    while i<n-1:
        if pos==0:
            ls=c[i]>up[i]; ss=c[i]<lo[i]
            if ls or ss:
                side=1 if ls else -1
                entry=o[i+1]*(1+SLIP) if side==1 else o[i+1]*(1-SLIP)
                stop=entry-atr_mult*a[i] if side==1 else entry+atr_mult*a[i]
                risk=abs(entry-stop); pos=side; i+=1; continue
        else:
            if pos==1:
                stop=max(stop,h[i]-atr_mult*a[i])
                if l[i]<=stop: rs.append((stop*(1-SLIP)-entry)/risk); pos=0
            else:
                stop=min(stop,l[i]+atr_mult*a[i])
                if h[i]>=stop: rs.append((entry-stop*(1+SLIP))/risk); pos=0
        i+=1
    if pos!=0: rs.append(((c[-1]-entry) if pos==1 else (entry-c[-1]))/risk)
    return rs


def ema_cross(df, fast=50, slow=200, atr_mult=3.0, atr_p=14):
    c=df["close"]; o=df["open"].to_numpy(); h=df["high"].to_numpy(); l=df["low"].to_numpy()
    ef=c.ewm(span=fast,adjust=False).mean().to_numpy(); es=c.ewm(span=slow,adjust=False).mean().to_numpy()
    cc=c.to_numpy(); a=atr_arr(df,atr_p); n=len(df); rs=[]; i=slow+1; pos=0; entry=stop=risk=0.0
    while i<n-1:
        up=ef[i]>es[i]; dn=ef[i]<es[i]
        if pos==0:
            if up or dn:
                side=1 if up else -1
                entry=o[i+1]*(1+SLIP) if side==1 else o[i+1]*(1-SLIP)
                stop=entry-atr_mult*a[i] if side==1 else entry+atr_mult*a[i]
                risk=abs(entry-stop); pos=side; i+=1; continue
        else:
            # exit on opposite cross or stop
            if pos==1:
                stop=max(stop,h[i]-atr_mult*a[i])
                if l[i]<=stop or dn: 
                    px=min(l[i],stop)*(1-SLIP) if l[i]<=stop else o[i]*(1-SLIP); rs.append((px-entry)/risk); pos=0; 
                    if dn and l[i]>stop: i+=1; continue
            else:
                stop=min(stop,l[i]+atr_mult*a[i])
                if h[i]>=stop or up:
                    px=max(h[i],stop)*(1+SLIP) if h[i]>=stop else o[i]*(1+SLIP); rs.append((entry-px)/risk); pos=0
                    if up and h[i]<stop: i+=1; continue
        i+=1
    if pos!=0: rs.append(((cc[-1]-entry) if pos==1 else (entry-cc[-1]))/risk)
    return rs


def main():
    out=[]
    for tf,path in FILES.items():
        df=load(path)
        bh=round(100*(df["close"].iloc[-1]/df["close"].iloc[0]-1),1)
        if tf=="D1":
            out.append(summ(donchian(df,20,3.0),"D1 Donchian-20 trend",bh))
            out.append(summ(donchian(df,55,3.0),"D1 Donchian-55 trend",bh))
            out.append(summ(ema_cross(df,50,200),"D1 EMA 50/200 cross",bh))
        else:
            out.append(summ(donchian(df,20,3.0),f"{tf} Donchian-20 trend",bh))
            out.append(summ(donchian(df,60,3.0),f"{tf} Donchian-60 trend",bh))
    print(json.dumps(out,indent=2))
    open("/sessions/awesome-loving-euler/mnt/outputs/gold_trend_results.json","w").write(json.dumps(out,indent=2))

if __name__=="__main__":
    main()
