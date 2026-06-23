"""Test the tradingwyckoff.com #1 recommendation: filter CRT by higher-timeframe
daily bias. Re-encodes our CRT (sweep->displacement->MSS->OB retrace, target=
opposite H4 wall, full_target, 2bps slip) on XAUUSD M15, validates vs the
documented 677 trades / -0.099R, then applies daily-bias + killzone filters."""
import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
SLIP=2/10_000; DISP=1.0; BUF=0.1; RRMIN=1.5; MAXHOLD=32

g=pd.read_parquet("/sessions/awesome-loving-euler/mnt/data/m15/XAUUSD_M15.parquet")
g.index=g.index.tz_convert("UTC"); g=g.sort_index()
o=g["open"].to_numpy();h=g["high"].to_numpy();l=g["low"].to_numpy();c=g["close"].to_numpy()
idx=g.index; hour=idx.hour.to_numpy()
tr=pd.concat([g["high"]-g["low"],(g["high"]-g["close"].shift()).abs(),(g["low"]-g["close"].shift()).abs()],axis=1).max(axis=1)
atr=tr.ewm(alpha=1/14,adjust=False).mean().to_numpy()

# H4 buckets (UTC 00/04/08/12/16/20)
bkt=idx.floor("4h"); codes=pd.factorize(bkt,sort=True)[0]
gg=pd.DataFrame({"hi":h,"lo":l,"code":codes})
hi_per=gg.groupby("code")["hi"].max(); lo_per=gg.groupby("code")["lo"].min()
prev_hi=hi_per.shift(1).reindex(codes).to_numpy(); prev_lo=lo_per.shift(1).reindex(codes).to_numpy()
n=len(g); bstart=np.empty(n,np.int64); s=0
for i in range(n):
    if i>0 and codes[i]!=codes[i-1]: s=i
    bstart[i]=s

# --- daily bias from D1 ---
d1=pd.read_parquet("/sessions/awesome-loving-euler/mnt/data/daily/XAUUSD_D1.parquet")
d1.index=(d1.index.tz_localize("UTC") if d1.index.tz is None else d1.index.tz_convert("UTC")); d1=d1.sort_index()
ema50=d1["close"].ewm(span=50,adjust=False).mean()
bias_ema=np.sign(d1["close"]-ema50)                       # trend filter
bias_mom=np.sign(d1["close"]/d1["close"].shift(252)-1)    # 12m momentum
def mapbias(bseries):
    bs=pd.Series(bseries.values,index=bseries.index.normalize()); bs=bs[~bs.index.duplicated()]
    return pd.Series(idx.normalize()).map(bs).ffill().fillna(0).to_numpy()
B_ema=mapbias(bias_ema); B_mom=mapbias(bias_mom)

def detect(i):
    b=bstart[i]
    if i-b+1<3: return None
    rh,rl=prev_hi[i],prev_lo[i]; a=atr[i]
    if not(np.isfinite(rh) and np.isfinite(rl) and a>0): return None
    los=l[b:i+1]; his=h[b:i+1]
    sl_=los.min()<rl; sh=his.max()>rh
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
        entry=obh; stop=round(swe-BUF*a,4); tgt=round(rh,4)
        if not(stop<entry<tgt): return None
        return 1,round(entry,4),stop,tgt
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
        entry=obl; stop=round(swe+BUF*a,4); tgt=round(rl,4)
        if not(tgt<entry<stop): return None
        return -1,round(entry,4),stop,tgt

def run(bias=None, killzone=False):
    trades=[]; in_until=-1; last=-10000
    for i in range(60,n-1):
        if i<=in_until or i-last<5: continue
        d=detect(i)
        if d is None: continue
        side,entry,stop,tgt=d
        if bias is not None and bias[i]!=side: continue          # daily-bias filter
        if killzone and not ((6<=hour[i]<9) or (13<=hour[i]<15)): continue  # London/NY open
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
        trades.append(R); last=i; in_until=i+ (k-i if R is not None else MAXHOLD)
    rs=np.array(trades)
    if len(rs)==0: return "n=0"
    wins=rs[rs>0]; gl=-rs[rs<=0].sum()
    return f"n={len(rs):>4}  win%={100*(rs>0).mean():4.1f}  avg_R={rs.mean():+.3f}  PF={(wins.sum()/gl if gl>0 else 9.9):.2f}  totR={rs.sum():+.0f}"

print("XAUUSD M15 CRT — daily-bias filter test (tradingwyckoff.com recommendation)\n")
print("baseline (no filter)        :", run())
print("+ daily EMA50 trend filter  :", run(bias=B_ema))
print("+ daily 12m momentum filter :", run(bias=B_mom))
print("+ EMA trend + killzone      :", run(bias=B_ema, killzone=True))
print("+ killzone only             :", run(killzone=True))
