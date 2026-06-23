"""CRT breadth test across instruments (daily analog: monthly range -> daily entry,
with the validated daily-trend bias filter). Uses the daily basket we have."""
import warnings; warnings.filterwarnings("ignore")
import glob, os, numpy as np, pandas as pd
SLIP=2/10_000; DISP=1.0; BUF=0.1; RRMIN=1.5; MAXHOLD=21

def load(p):
    d=pd.read_parquet(p); d.index=(d.index.tz_localize("UTC") if d.index.tz is None else d.index.tz_convert("UTC"))
    return d.sort_index()

def crt(df, use_bias):
    o=df["open"].to_numpy();h=df["high"].to_numpy();l=df["low"].to_numpy();c=df["close"].to_numpy()
    idx=df.index; n=len(df)
    tr=pd.concat([df["high"]-df["low"],(df["high"]-df["close"].shift()).abs(),(df["low"]-df["close"].shift()).abs()],axis=1).max(axis=1)
    atr=tr.ewm(alpha=1/14,adjust=False).mean().to_numpy()
    bias=np.sign(c-pd.Series(c).ewm(span=200,adjust=False).mean().to_numpy())
    codes=pd.PeriodIndex(idx,freq="M").astype("int64").to_numpy()  # month buckets
    gg=pd.DataFrame({"hi":h,"lo":l,"code":codes})
    prev_hi=gg.groupby("code")["hi"].max().shift(1).reindex(codes).to_numpy()
    prev_lo=gg.groupby("code")["lo"].min().shift(1).reindex(codes).to_numpy()
    bstart=np.empty(n,np.int64); s=0
    for i in range(n):
        if i>0 and codes[i]!=codes[i-1]: s=i
        bstart[i]=s
    def detect(i):
        b=bstart[i]
        if i-b+1<3: return None
        rh,rl=prev_hi[i],prev_lo[i]; a=atr[i]
        if not(np.isfinite(rh) and np.isfinite(rl) and a>0): return None
        los=l[b:i+1];his=h[b:i+1];sl_=los.min()<rl;sh=his.max()>rh
        if sl_==sh: return None
        if sl_:
            si=b+int(los.argmin());swe=l[si];rhi=h[si]
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
            e=obh;st=swe-BUF*a;tg=rh
            return (1,e,st,tg) if st<e<tg else None
        else:
            si=b+int(his.argmax());swe=h[si];rlo=l[si]
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
            e=obl;st=swe+BUF*a;tg=rl
            return (-1,e,st,tg) if tg<e<st else None
    trades=[];in_until=-1;last=-10000
    for i in range(200,n-1):
        if i<=in_until or i-last<2: continue
        d=detect(i)
        if d is None: continue
        side,e0,stop,tgt=d
        if use_bias and bias[i]!=side: continue
        e=o[i+1]*(1+SLIP) if side==1 else o[i+1]*(1-SLIP)
        risk=abs(e-stop);reward=abs(tgt-e)
        if risk<=0 or reward/risk<RRMIN: continue
        R=None
        for k in range(i+1,min(i+1+MAXHOLD,n)):
            if side==1:
                if l[k]<=stop:R=(stop*(1-SLIP)-e)/risk;break
                if h[k]>=tgt:R=(tgt-e)/risk;break
            else:
                if h[k]>=stop:R=(e-stop*(1+SLIP))/risk;break
                if l[k]<=tgt:R=(e-tgt)/risk;break
        if R is None:
            px=c[min(i+MAXHOLD,n-1)];R=((px-e) if side==1 else (e-px))/risk
        trades.append(R);last=i;in_until=k
    return np.array(trades)

files=sorted(glob.glob("/sessions/awesome-loving-euler/mnt/data_fetch/data/d1/*_D1.parquet"))
print(f"{'instrument':10s}{'base n':>8}{'base avgR':>11}{'+bias n':>9}{'+bias avgR':>12}{'+bias PF':>10}")
print("-"*60)
allb=[];allf=[]
for f in files:
    name=os.path.basename(f).split("_")[0]
    df=load(f)
    b=crt(df,False); fl=crt(df,True)
    allb+=list(b); allf+=list(fl)
    def s(x): return (len(x), x.mean() if len(x) else 0)
    bn,ba=s(b); fn,fa=s(fl)
    pf=( fl[fl>0].sum()/ -fl[fl<=0].sum() ) if (len(fl) and (fl<=0).any() and -fl[fl<=0].sum()>0) else float('nan')
    print(f"{name:10s}{bn:>8}{ba:>+11.3f}{fn:>9}{fa:>+12.3f}{pf:>10.2f}")
allb=np.array(allb);allf=np.array(allf)
print("-"*60)
print(f"{'AGG base':10s}{len(allb):>8}{allb.mean():>+11.3f}")
print(f"{'AGG +bias':10s}{'':>8}{'':>11}{len(allf):>9}{allf.mean():>+12.3f}{(allf[allf>0].sum()/-allf[allf<=0].sum()):>10.2f}")
