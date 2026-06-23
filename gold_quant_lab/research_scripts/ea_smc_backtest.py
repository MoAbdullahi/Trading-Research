"""Faithful re-encoding of automatedSMC v2.30's CORE entry engine, on XAUUSD M15.

Mirrors: forward-confirmed swing pivots (len20) -> close-based structure break
(BOS/CHoCH) -> order block (strongest opposing body in last 10) -> SL=OB-0.5ATR,
TP=2R from OB -> gated by kill zone (London 07-09, NY 13-15 UTC) + ADX(14)>=22 +
premium/discount + OB-edge 40% + minRR 1.2 + same-OB block, confluence >=5/8.
C3(liq pool)/C4(sweep)/C7(POC) are the author's "near-always-pass" conditions
(granted, per his own diagnostic); C6 LTF-CHoCH approximated on M15 internal-5
(EA uses M1, which I don't have). Entry next-bar open, 2bps slip, exit TP/SL.
"""
import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, sys

SLIP=2/10_000
def load(p):
    d=pd.read_parquet(p); d.index=d.index.tz_convert("UTC"); return d.sort_index()

def adx_wilder(h,l,c,n=14):
    up=h.diff(); dn=-l.diff()
    plus=np.where((up>dn)&(up>0),up,0.0); minus=np.where((dn>up)&(dn>0),dn,0.0)
    tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    atr=tr.ewm(alpha=1/n,adjust=False).mean()
    pdi=100*pd.Series(plus,index=h.index).ewm(alpha=1/n,adjust=False).mean()/atr
    mdi=100*pd.Series(minus,index=h.index).ewm(alpha=1/n,adjust=False).mean()/atr
    dx=100*(pdi-mdi).abs()/(pdi+mdi).replace(0,np.nan)
    return dx.ewm(alpha=1/n,adjust=False).mean().to_numpy()

def run(df, use_killzone=True, use_adx=True):
    o=df["open"].to_numpy(); h=df["high"].to_numpy(); l=df["low"].to_numpy()
    c=df["close"].to_numpy(); vol=df["volume"].to_numpy(); hour=df.index.hour.to_numpy()
    n=len(df)
    tr=pd.concat([df["high"]-df["low"],(df["high"]-df["close"].shift()).abs(),(df["low"]-df["close"].shift()).abs()],axis=1).max(axis=1)
    atr=tr.rolling(200).mean().to_numpy()
    adx=adx_wilder(df["high"],df["low"],df["close"],14)
    L=20
    # state
    swH=swL=0.0; swH_cross=swL_cross=True; trend=0
    # ltf internal pivots (approx on M15 internal length 5)
    iL=5; iH=iLp=0.0; iH_cross=iLp_cross=True; ltf_trend=0
    setup=None; last_sl=0.0
    trades=[]

    def killzone(hr):
        if not use_killzone: return True
        return (7<=hr<9) or (13<=hr<15)

    for i in range(2*L+2, n-1):
        a=atr[i]
        if not (a>0): continue
        # --- forward-confirmed HTF pivot at i-L ---
        pc=i-L
        win_h=h[i-2*L:i+1]; win_l=l[i-2*L:i+1]
        ch=h[pc]; cl=l[pc]
        # strict max/min excluding center
        if ch==win_h.max() and (win_h==ch).sum()==1 and ch!=swH:
            swH=ch; swH_cross=False
        if cl==win_l.min() and (win_l==cl).sum()==1 and cl!=swL:
            swL=cl; swL_cross=False
        # --- internal pivots (LTF approx) ---
        ipc=i-iL
        wih=h[i-2*iL:i+1]; wil=l[i-2*iL:i+1]
        if h[ipc]==wih.max() and (wih==h[ipc]).sum()==1 and h[ipc]!=iH: iH=h[ipc]; iH_cross=False
        if l[ipc]==wil.min() and (wil==l[ipc]).sum()==1 and l[ipc]!=iLp: iLp=l[ipc]; iLp_cross=False
        if iH>0 and not iH_cross and c[i]>iH: iH_cross=True; ltf_trend=1
        if iLp>0 and not iLp_cross and c[i]<iLp: iLp_cross=True; ltf_trend=-1
        # --- structure break (close-based, bar i) ---
        if swH>0 and not swH_cross and c[i]>swH:
            swH_cross=True; trend=1
            if setup is None:
                # OB = strongest bearish body in last 10
                bb=-1; bs=0
                for k in range(i-9,i+1):
                    if c[k]<o[k] and abs(c[k]-o[k])>bs: bs=abs(c[k]-o[k]); bb=k
                if bb>=0:
                    obH=h[bb]; obL=l[bb]; sl=obL-0.5*a; tp=obH+(obH-sl)*2.0
                    obvol=vol[bb]; avg=vol[max(0,bb-9):bb+1].mean()
                    setup=dict(bias=1,obH=obH,obL=obL,sl=sl,tp=tp,left=30,
                               strength=(obvol/avg if avg>0 else 1))
        if swL>0 and not swL_cross and c[i]<swL:
            swL_cross=True; trend=-1
            if setup is None:
                bb=-1; bs=0
                for k in range(i-9,i+1):
                    if c[k]>o[k] and abs(c[k]-o[k])>bs: bs=abs(c[k]-o[k]); bb=k
                if bb>=0:
                    obH=h[bb]; obL=l[bb]; sl=obH+0.5*a; tp=obL-(sl-obL)*2.0
                    obvol=vol[bb]; avg=vol[max(0,bb-9):bb+1].mean()
                    setup=dict(bias=-1,obH=obH,obL=obL,sl=sl,tp=tp,left=30,
                               strength=(obvol/avg if avg>0 else 1))
        # --- evaluate active setup ---
        if setup is not None:
            setup["left"]-=1
            if setup["left"]<=0: setup=None
        if setup is not None and killzone(hour[i]) and (adx[i]>=22 or not use_adx):
            bias=setup["bias"]; price=c[i]
            mid=(swH+swL)/2 if (swH>0 and swL>0 and swH>swL) else None
            c1= (bias==1 and trend>=0) or (bias==-1 and trend<=0)
            c2= mid is not None and ((bias==1 and price<mid) or (bias==-1 and price>mid))
            buf=0.4*a
            inzone=(price>=setup["obL"]-buf and price<=setup["obH"]+buf)
            c5= inzone and setup["strength"]>=1.2
            c6= (bias==1 and ltf_trend==1) or (bias==-1 and ltf_trend==-1)
            # C8 FVG: 3-bar gap aligned, near OB/price
            c8=False
            for k in range(max(3,i-12),i+1):
                if bias==1 and h[k-2]<l[k] and price>=h[k-2]-0.3*a and price<=l[k]+0.3*a: c8=True;break
                if bias==-1 and l[k-2]>h[k] and price<=l[k-2]+0.3*a and price>=h[k]-0.3*a: c8=True;break
            c3=c4=c7=True   # author: near-always-pass
            score=sum([c1,c2,c3,c4,c5,c6,c7,c8])
            if score>=5:
                obR=setup["obH"]-setup["obL"]
                atEdge=(price<=setup["obL"]+obR*0.4) if bias==1 else (price>=setup["obH"]-obR*0.4)
                entry=o[i+1]*(1+SLIP) if bias==1 else o[i+1]*(1-SLIP)
                risk=abs(entry-setup["sl"]); reward=abs(setup["tp"]-entry)
                rr=reward/risk if risk>0 else 0
                if atEdge and rr>=1.2 and setup["sl"]!=last_sl and risk>0:
                    last_sl=setup["sl"]; tp=setup["tp"]; sl=setup["sl"]
                    R=None
                    for k in range(i+1,min(i+1+200,n)):
                        if bias==1:
                            if l[k]<=sl: R=(sl*(1-SLIP)-entry)/risk; break
                            if h[k]>=tp: R=(tp-entry)/risk; break
                        else:
                            if h[k]>=sl: R=(entry-sl*(1+SLIP))/risk; break
                            if l[k]<=tp: R=(entry-tp)/risk; break
                    if R is None: R=((c[min(i+200,n-1)]-entry) if bias==1 else (entry-c[min(i+200,n-1)]))/risk
                    trades.append(R); setup=None
    return np.array(trades)

def report(name,rs):
    if len(rs)==0: print(f"{name}: 0 trades"); return
    wins=rs[rs>0]; gl=-rs[rs<=0].sum()
    print(f"{name}: n={len(rs)}  win%={100*(rs>0).mean():.1f}  avg_R={rs.mean():+.3f}  "
          f"PF={(wins.sum()/gl if gl>0 else float('inf')):.2f}  totalR={rs.sum():+.1f}")

g=load("/sessions/awesome-loving-euler/mnt/data/m15/XAUUSD_M15.parquet")
print(f"XAUUSD M15 {g.index[0].date()}->{g.index[-1].date()} ({len(g)} bars)")
report("EA core (killzone+ADX, full gating)", run(g,True,True))
report("EA core (no killzone/ADX gate)     ", run(g,False,False))
gb=load("/sessions/awesome-loving-euler/mnt/data/m15/GBPUSD_M15.parquet")
report("EA core on GBPUSD (killzone+ADX)   ", run(gb,True,True))
