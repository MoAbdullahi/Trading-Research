"""Test the Wyckoff 'effort vs result' (volume) idea on our gold CRT — the one
lever the ICT/CRT tests omitted. NOTE: Dukascopy gold 'volume' is TICK volume,
not real volume, so this is an indicative proxy (volume analysis is far stronger
on real-volume markets like equities/futures)."""
import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
SLIP=2/10_000; DISP=1.0; BUF=0.1; RRMIN=1.5; MAXHOLD=32
g=pd.read_parquet("/sessions/awesome-loving-euler/mnt/data/m15/XAUUSD_M15.parquet")
g.index=g.index.tz_convert("UTC"); g=g.sort_index()
o=g["open"].to_numpy();h=g["high"].to_numpy();l=g["low"].to_numpy();c=g["close"].to_numpy();v=g["volume"].to_numpy()
idx=g.index
tr=pd.concat([g["high"]-g["low"],(g["high"]-g["close"].shift()).abs(),(g["low"]-g["close"].shift()).abs()],axis=1).max(axis=1)
atr=tr.ewm(alpha=1/14,adjust=False).mean().to_numpy()
vavg=pd.Series(v).rolling(20).mean().to_numpy()
bkt=idx.floor("4h"); codes=pd.factorize(bkt,sort=True)[0]
gg=pd.DataFrame({"hi":h,"lo":l,"code":codes})
prev_hi=gg.groupby("code")["hi"].max().shift(1).reindex(codes).to_numpy()
prev_lo=gg.groupby("code")["lo"].min().shift(1).reindex(codes).to_numpy()
n=len(g); bstart=np.empty(n,np.int64); s=0
for i in range(n):
    if i>0 and codes[i]!=codes[i-1]: s=i
    bstart[i]=s
d1=pd.read_parquet("/sessions/awesome-loving-euler/mnt/data/daily/XAUUSD_D1.parquet")
d1.index=(d1.index.tz_localize("UTC") if d1.index.tz is None else d1.index.tz_convert("UTC")); d1=d1.sort_index()
bmom=np.sign(d1["close"]/d1["close"].shift(252)-1)
bs=pd.Series(bmom.values,index=bmom.index.normalize()); bs=bs[~bs.index.duplicated()]
B=pd.Series(idx.normalize()).map(bs).ffill().fillna(0).to_numpy()

def detect(i):
    b=bstart[i]
    if i-b+1<3: return None
    rh,rl=prev_hi[i],prev_lo[i]; a=atr[i]
    if not(np.isfinite(rh) and np.isfinite(rl) and a>0): return None
    los=l[b:i+1]; his=h[b:i+1]; sl_=los.min()<rl; sh=his.max()>rh
    if sl_==sh: return None
    if sl_:
        si=b+int(los.argmin()); swe=l[si]; rhi=h[si]
        if c[i]<=rl: return None
        fd=-1
        for j in range(si+1,i+1):
            if (c[j]-o[j])>=DISP*a and c[j]>o[j]: fd=j;break
        if fd<0 or c[fd:i+1].max()<=rhi: return None
        ob=-1
        for j in range(fd-1,si-1,-1):
            if c[j]<o[j]: ob=j;break
        if ob<0: return None
        obh=max(o[ob],c[ob])
        if l[i]>obh: return None
        e=obh; st=round(swe-BUF*a,4); tg=round(rh,4)
        if not(st<e<tg): return None
        return 1,round(e,4),st,tg,si,fd
    else:
        si=b+int(his.argmax()); swe=h[si]; rlo=l[si]
        if c[i]>=rh: return None
        fd=-1
        for j in range(si+1,i+1):
            if (c[j]-o[j])<=-DISP*a and c[j]<o[j]: fd=j;break
        if fd<0 or c[fd:i+1].min()>=rlo: return None
        ob=-1
        for j in range(fd-1,si-1,-1):
            if c[j]>o[j]: ob=j;break
        if ob<0: return None
        obl=min(o[ob],c[ob])
        if h[i]<obl: return None
        e=obl; st=round(swe+BUF*a,4); tg=round(rl,4)
        if not(tg<e<st): return None
        return -1,round(e,4),st,tg,si,fd

def run(bias=False, vol_mode=None):
    trades=[]; in_until=-1; last=-10000
    for i in range(60,n-1):
        if i<=in_until or i-last<5: continue
        d=detect(i)
        if d is None: continue
        side,e0,stop,tgt,si,fd=d
        if bias and B[i]!=side: continue
        if vol_mode=="disp_high" and not (vavg[fd]>0 and v[fd]>1.2*vavg[fd]): continue   # conviction on reversal
        if vol_mode=="sweep_high" and not (vavg[si]>0 and v[si]>1.2*vavg[si]): continue   # absorption on sweep
        if vol_mode=="sweep_low" and not (vavg[si]>0 and v[si]<0.8*vavg[si]): continue     # no-supply sweep
        e=o[i+1]*(1+SLIP) if side==1 else o[i+1]*(1-SLIP)
        risk=abs(e-stop); reward=abs(tgt-e)
        if risk<=0 or reward/risk<RRMIN: continue
        R=None
        for k in range(i+1,min(i+1+MAXHOLD,n)):
            if side==1:
                if l[k]<=stop: R=(stop*(1-SLIP)-e)/risk;break
                if h[k]>=tgt: R=(tgt-e)/risk;break
            else:
                if h[k]>=stop: R=(e-stop*(1+SLIP))/risk;break
                if l[k]<=tgt: R=(e-tgt)/risk;break
        if R is None:
            px=c[min(i+MAXHOLD,n-1)]; R=((px-e) if side==1 else (e-px))/risk
        trades.append(R); last=i; in_until=k
    rs=np.array(trades)
    if len(rs)==0: return "n=0"
    w=rs[rs>0]; gl=-rs[rs<=0].sum()
    return f"n={len(rs):>4}  win%={100*(rs>0).mean():4.1f}  avg_R={rs.mean():+.3f}  PF={(w.sum()/gl if gl>0 else 9.9):.2f}"

print("Gold CRT + Wyckoff volume (effort/result) filter — TICK volume proxy, indicative\n")
print("baseline                         :", run())
print("+ daily 12m momentum bias        :", run(bias=True))
print("+ high-volume displacement       :", run(vol_mode="disp_high"))
print("+ high-volume sweep (absorption) :", run(vol_mode="sweep_high"))
print("+ low-volume sweep (no supply)   :", run(vol_mode="sweep_low"))
print("+ bias + high-vol displacement   :", run(bias=True, vol_mode="disp_high"))
