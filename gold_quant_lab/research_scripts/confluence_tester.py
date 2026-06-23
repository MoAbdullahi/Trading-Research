"""Confluence tester — does stacking ICT rules improve expectancy, or just cut sample?

Encodes 4 mechanical, directional ICT rules on XAUUSD M15, each voting -1/0/+1:
  A  Liquidity sweep / turtle soup  : pierce prior 20-bar high & close back below -> SHORT (mirror LONG)
  B  Premium/Discount mean-revert   : in bottom 30% of 50-bar range -> LONG ; top 30% -> SHORT
  C  FVG retrace (continuation)     : price re-enters a recent 3-candle gap -> trade gap (displacement) direction
  D  HTF trend / draw on liquidity  : close vs EMA-200 -> above LONG bias, below SHORT bias

Each signal: enter next bar open, stop 1xATR, target 2xATR (=2R), max hold 16 bars (4h),
2bps slippage, stop-before-target. Events fire on transition only (not every bar in a zone).
Confluence tiers: net vote (A+B+C+D) >= 2 or >= 3 agree.
"""
import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, json

SLIP=2/10_000
df=pd.read_parquet("/sessions/awesome-loving-euler/mnt/data/m15/XAUUSD_M15.parquet")
df.index=df.index.tz_convert("America/New_York"); df=df.sort_index()
o=df["open"].to_numpy(); h=df["high"].to_numpy(); l=df["low"].to_numpy(); c=df["close"].to_numpy()
n=len(df); nyhour=df.index.hour.to_numpy()

# ATR (EWMA14)
pc=pd.Series(c).shift(1)
tr=pd.concat([pd.Series(h)-pd.Series(l),(pd.Series(h)-pc).abs(),(pd.Series(l)-pc).abs()],axis=1).max(axis=1)
atr=tr.ewm(alpha=1/14,adjust=False).mean().to_numpy()

# rolling levels
ph=pd.Series(h).rolling(20).max().shift(1).to_numpy()   # prior 20-bar high
pl=pd.Series(l).rolling(20).min().shift(1).to_numpy()
hh=pd.Series(h).rolling(50).max().to_numpy(); ll=pd.Series(l).rolling(50).min().to_numpy()
ema=pd.Series(c).ewm(span=200,adjust=False).mean().to_numpy()

A=np.zeros(n,int); B=np.zeros(n,int); C=np.zeros(n,int); D=np.zeros(n,int)
# A sweep/turtle soup
A[(l<pl)&(c>pl)]=1      # swept low, closed back above -> long
A[(h>ph)&(c<ph)]=-1     # swept high, closed back below -> short
# B premium/discount
rng=hh-ll; pos=np.where(rng>0,(c-ll)/rng,0.5)
B[pos<0.30]=1; B[pos>0.70]=-1
# D HTF trend
D[c>ema]=1; D[c<ema]=-1
# C FVG retrace (loop, keep last open gaps within 12 bars)
for t in range(2,n):
    # bullish gap formed at bar t: high[t-2] < low[t]
    # check recent gaps t-12..t for price re-entry at bar t
    vote=0
    for k in range(max(2,t-12),t+1):
        if h[k-2] < l[k]:          # bullish FVG zone [h[k-2], l[k]]
            if l[t] <= l[k] and c[t] >= h[k-2]:
                vote=1; break
        if l[k-2] > h[k]:          # bearish FVG zone [h[k], l[k-2]]
            if h[t] >= h[k] and c[t] <= l[k-2]:
                vote=-1; break
    C[t]=vote

def events(vote):
    ev=np.zeros(n,bool)
    for t in range(1,n):
        if vote[t]!=0 and vote[t]!=vote[t-1]:
            ev[t]=True
    return ev

def sim(side,i):
    if i+1>=n or not (atr[i]>0): return None
    entry=o[i+1]*(1+SLIP) if side==1 else o[i+1]*(1-SLIP)
    risk=atr[i]; stop=entry-risk if side==1 else entry+risk; tgt=entry+2*risk if side==1 else entry-2*risk
    for k in range(i+1,min(i+1+16,n)):
        hs=(l[k]<=stop) if side==1 else (h[k]>=stop)
        ht=(h[k]>=tgt) if side==1 else (l[k]<=tgt)
        if hs: return -1.0  # stop = -1R (slip already in entry)
        if ht: return 2.0
    px=c[min(i+16,n-1)]
    return ((px-entry) if side==1 else (entry-px))/risk

def evaluate(sig_dir, mask=None):
    rs=[]
    for t in range(n-1):
        s=sig_dir[t]
        if s==0: continue
        if mask is not None and not mask[t]: continue
        r=sim(int(np.sign(s)),t)
        if r is not None: rs.append(r)
    rs=np.array(rs)
    if len(rs)==0: return {"n":0}
    return {"n":int(len(rs)),"win%":round(100*float((rs>0).mean()),1),"avg_R":round(float(rs.mean()),3),
            "total_R":round(float(rs.sum()),1)}

out={}
for name,V in [("A sweep",A),("B prem/disc",B),("C FVG",C),("D HTF trend",D)]:
    ev=events(V); dir_=np.where(ev,V,0); out[name]=evaluate(dir_)

net=A+B+C+D
for thr in (2,3):
    cd=np.where(net>=thr,1,np.where(net<=-thr,-1,0))
    ev=events(cd); dir_=np.where(ev,cd,0); out[f"Confluence >={thr} agree"]=evaluate(dir_)
# confluence>=2 inside NY kill zone (7-10 NY)
cd=np.where(net>=2,1,np.where(net<=-2,-1,0)); ev=events(cd); dir_=np.where(ev,cd,0)
kz=(nyhour>=7)&(nyhour<10)
out["Confluence >=2 + NY killzone"]=evaluate(dir_,mask=kz)

print(f"XAUUSD M15, {df.index[0].date()}->{df.index[-1].date()}, {n} bars")
print(f"{'signal':30s}{'n':>7}{'win%':>8}{'avg_R':>9}{'total_R':>10}")
print("-"*64)
for k,v in out.items():
    if v.get("n",0)==0: print(f"{k:30s}{'0':>7}"); continue
    print(f"{k:30s}{v['n']:>7}{v['win%']:>8}{v['avg_R']:>9}{v['total_R']:>10}")
json.dump(out,open("confluence_results.json","w"),indent=2)

# --- BONUS: confluence>=2 aligned with the PROVEN daily 12-month momentum bias ---
d1=pd.read_parquet("/sessions/awesome-loving-euler/mnt/data/daily/XAUUSD_D1.parquet")
d1.index=d1.index.tz_convert("America/New_York") if d1.index.tz else d1.index.tz_localize("UTC").tz_convert("America/New_York")
d1=d1.sort_index()
mom_sign=np.sign(d1["close"]/d1["close"].shift(252)-1)
mom_by_date=mom_sign.to_dict()
day_key=pd.Index(df.index.normalize())
mday=np.array([mom_by_date.get(k,0) for k in pd.Series(d1.index.normalize()).reindex(range(len(d1))).values]) if False else None
# map each M15 bar to that day's (or prior day's) momentum sign
dseries=pd.Series(mom_sign.values, index=mom_sign.index.normalize())
dseries=dseries[~dseries.index.duplicated()]
align=pd.Series(df.index.normalize()).map(dseries).ffill().fillna(0).to_numpy()

cd=np.where(net>=2,1,np.where(net<=-2,-1,0)); ev=events(cd); cdir=np.where(ev,cd,0)
aligned=np.where(cdir==align, cdir, 0)              # keep only entries agreeing with daily momentum
res=evaluate(aligned)
print(f"{'Confluence >=2 + daily 12m mom':30s}{res['n']:>7}{res['win%']:>8}{res['avg_R']:>9}{res['total_R']:>10}")
# and the same plus killzone
aligned_kz=aligned.copy()
res2=evaluate(aligned_kz, mask=kz)
print(f"{'  ...+ NY killzone':30s}{res2['n']:>7}{res2['win%']:>8}{res2['avg_R']:>9}{res2['total_R']:>10}")
