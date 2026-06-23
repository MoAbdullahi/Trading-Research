"""PCA residual mean-reversion stat-arb (Avellaneda-Lee style) — the portable core
alpha of noterminusgit/statarb, tested on the 15-instrument daily basket.

Method (per the repo's pca.py / pca_generator_daily.py concept):
  * rolling WINDOW of daily returns -> standardize -> top-k PCs = systematic factors
  * regress each asset on the factors -> idiosyncratic residual series
  * model cumulative residual as OU; s-score = how stretched it is
  * trade AGAINST the residual: short rich (s>+entry), long cheap (s<-entry),
    exit near 0. Dollar-neutral, equal risk. Daily rebalance, cost per turnover.
"""
import warnings; warnings.filterwarnings("ignore")
import glob, os, numpy as np, pandas as pd

WINDOW=60; K=3; ENTRY=1.25; EXIT=0.50; COST_BPS=2.0; ANN=252

files=sorted(glob.glob("/sessions/awesome-loving-euler/mnt/data_fetch/data/d1/*_D1.parquet"))
ser={}
for f in files:
    d=pd.read_parquet(f)
    d.index=d.index.tz_localize("UTC") if d.index.tz is None else d.index.tz_convert("UTC")
    ser[os.path.basename(f).split("_")[0]]=d.sort_index()["close"]
px=pd.concat(ser,axis=1).sort_index()
# keep instruments with full 2014 history for a clean PCA matrix
start="2014-08-01"
px=px[px.index>=start].dropna(axis=1, thresh=int(0.95*len(px[px.index>=start])))
px=px.dropna()
rets=np.log(px).diff().dropna()
cols=list(px.columns); T,N=rets.shape
print(f"PCA stat-arb | {N} instruments {cols}")
print(f"window {px.index[WINDOW].date()}..{px.index[-1].date()} | {T} days, k={K} PCs\n")

R=rets.to_numpy()
pos=np.zeros((T,N)); cur=np.zeros(N)
for t in range(WINDOW,T):
    win=R[t-WINDOW:t]                          # window x N
    mu=win.mean(0); sd=win.std(0); sd[sd==0]=1e-9
    Z=(win-mu)/sd                              # standardized
    # PCA via SVD
    U,S,Vt=np.linalg.svd(Z,full_matrices=False)
    Vk=Vt[:K].T                                # N x k loadings
    F=Z@Vk                                      # window x k factor returns
    new=cur.copy()
    for i in range(N):
        beta,_,_,_=np.linalg.lstsq(F, Z[:,i], rcond=None)
        e=Z[:,i]-F@beta                         # residual series (window,)
        X=np.cumsum(e)                          # OU process
        x0=X[:-1]; x1=X[1:]
        b,a=np.polyfit(x0,x1,1)                 # x1 = b*x0 + a
        if 0<b<1:
            resid=x1-(b*x0+a)
            m=a/(1-b); seq=resid.std()/np.sqrt(1-b*b)
            s=(X[-1]-m)/seq if seq>0 else 0.0
        else:
            s=0.0
        # mean-reversion bands with hysteresis
        if cur[i]==0:
            if s> ENTRY: new[i]=-1
            elif s<-ENTRY: new[i]=1
        else:
            if abs(s)<EXIT: new[i]=0
            else: new[i]=cur[i]
    # dollar-neutral, equal risk
    longs=new>0; shorts=new<0
    w=np.zeros(N)
    if longs.sum()>0: w[longs]= 1.0/longs.sum()
    if shorts.sum()>0: w[shorts]=-1.0/shorts.sum()
    pos[t]=w; cur=new

pos=pd.DataFrame(pos,index=rets.index,columns=cols)
port=(pos.shift(1)*rets).sum(axis=1)
turn=pos.diff().abs().sum(axis=1).fillna(0)
port=port-turn*(COST_BPS/10000)
r=port.dropna()
def stats(x,lbl):
    if len(x)<30: print(lbl,"n/a"); return
    eq=(1+x).cumprod(); dd=(eq/eq.cummax()-1).min()
    print(f"{lbl}: ann={100*((1+x.mean())**ANN-1):.1f}%  vol={100*x.std()*np.sqrt(ANN):.1f}%  "
          f"Sharpe={x.mean()/x.std()*np.sqrt(ANN):.2f}  maxDD={100*dd:.1f}%")
stats(r,"PCA stat-arb (full)")
mid=r.index[len(r)//2]
stats(r[r.index<mid], "  2014-2020")
stats(r[r.index>=mid],"  2020-2026")
