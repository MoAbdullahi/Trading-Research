"""Fetch M15 for the faithful CRT multi-instrument test: 7 FX majors + gold +
top-cap cryptos (BTC, ETH). Run locally (Dukascopy needs internet).
    pip install dukascopy-python pandas pyarrow
    python fetch_pairs_m15.py
Output: ./data/m15/<NAME>_M15.parquet
"""
import sys,time
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
from dukascopy_python import fetch, INTERVAL_MIN_15, OFFER_SIDE_BID, instruments as I
OUT=Path("./data/m15"); OUT.mkdir(parents=True,exist_ok=True)
FX_START=datetime(2014,1,1,tzinfo=timezone.utc)
CR_START=datetime(2018,1,1,tzinfo=timezone.utc)   # crypto history shorter
END=datetime(2026,6,1,tzinfo=timezone.utc)
PAIRS={
 "EURUSD":(I.INSTRUMENT_FX_MAJORS_EUR_USD,FX_START),
 "GBPUSD":(I.INSTRUMENT_FX_MAJORS_GBP_USD,FX_START),
 "USDJPY":(I.INSTRUMENT_FX_MAJORS_USD_JPY,FX_START),
 "AUDUSD":(I.INSTRUMENT_FX_MAJORS_AUD_USD,FX_START),
 "NZDUSD":(I.INSTRUMENT_FX_MAJORS_NZD_USD,FX_START),
 "USDCAD":(I.INSTRUMENT_FX_MAJORS_USD_CAD,FX_START),
 "USDCHF":(I.INSTRUMENT_FX_MAJORS_USD_CHF,FX_START),
 "XAUUSD":(I.INSTRUMENT_FX_METALS_XAU_USD,FX_START),
 "BTCUSD":(I.INSTRUMENT_VCCY_BTC_USD,CR_START),
 "ETHUSD":(I.INSTRUMENT_VCCY_ETH_USD,CR_START),
}
ok=0
for name,(sym,start) in PAIRS.items():
    try:
        t=time.time()
        df=fetch(instrument=sym,interval=INTERVAL_MIN_15,offer_side=OFFER_SIDE_BID,start=start,end=END)
        if df is None or df.empty: raise RuntimeError("empty")
        df.index=pd.to_datetime(df.index,utc=True); df.index.name="timestamp"
        df.columns=[c.lower() for c in df.columns]
        df.to_parquet(OUT/f"{name}_M15.parquet",compression="zstd")
        print(f"[{name}] {len(df):>7} bars {df.index[0].date()}->{df.index[-1].date()} ({time.time()-t:.0f}s)"); ok+=1
    except Exception as e:
        print(f"[{name}] FAILED: {type(e).__name__}: {e}",file=sys.stderr)
print(f"\n{ok}/{len(PAIRS)} saved to {OUT.resolve()}")
