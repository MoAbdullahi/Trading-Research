"""Fetch a DIVERSIFIED DAILY basket from Dukascopy for cross-sectional momentum.

Cross-sectional (relative-strength) momentum needs many uncorrelated markets.
This pulls ~15 liquid instruments at D1 (daily) — small and fast (a few minutes)
— and as far back as Dukascopy provides, so you also get older regimes
(e.g. the 2013-2018 gold bear) for stress-testing.

    pip install dukascopy-python pandas pyarrow
    python fetch_basket_d1.py

Output: ./data/d1/<NAME>_D1.parquet  (UTC index, open/high/low/close/volume)
Then run, from your trading_system folder:
    python run_relative_strength.py --data ../path/to/data/d1/*.parquet --lookback 63
"""
from __future__ import annotations
import sys, time
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
from dukascopy_python import fetch, INTERVAL_DAY_1, OFFER_SIDE_BID, instruments as I

START = datetime(2014, 1, 1, tzinfo=timezone.utc)   # go back for multiple regimes
END   = datetime(2026, 6, 1, tzinfo=timezone.utc)
OUT = Path("./data/d1"); OUT.mkdir(parents=True, exist_ok=True)

# A diversified, liquid basket: metals, FX majors, US indices, dollar index.
BASKET = {
    "XAUUSD": I.INSTRUMENT_FX_METALS_XAU_USD,
    "XAGUSD": I.INSTRUMENT_FX_METALS_XAG_USD,
    "XPTUSD": I.INSTRUMENT_CMD_METALS_XPT_CMD_USD,
    "COPPER": I.INSTRUMENT_CMD_METALS_COPPER_CMD_USD,
    "EURUSD": I.INSTRUMENT_FX_MAJORS_EUR_USD,
    "GBPUSD": I.INSTRUMENT_FX_MAJORS_GBP_USD,
    "AUDUSD": I.INSTRUMENT_FX_MAJORS_AUD_USD,
    "NZDUSD": I.INSTRUMENT_FX_MAJORS_NZD_USD,
    "USDJPY": I.INSTRUMENT_FX_MAJORS_USD_JPY,
    "USDCHF": I.INSTRUMENT_FX_MAJORS_USD_CHF,
    "USDCAD": I.INSTRUMENT_FX_MAJORS_USD_CAD,
    "NAS100": I.INSTRUMENT_IDX_AMERICA_E_NQ_100,
    "US30":   I.INSTRUMENT_IDX_AMERICA_E_D_J_IND,
    "SPX500": I.INSTRUMENT_IDX_AMERICA_E_SANDP_500,
    "DXY":    I.INSTRUMENT_IDX_AMERICA_DOLLAR_IDX_USD,
}


def main() -> int:
    print(f"Range: {START.date()} -> {END.date()}   ({len(BASKET)} instruments, D1)\n")
    ok = 0
    for name, sym in BASKET.items():
        try:
            t0 = time.time()
            df = fetch(instrument=sym, interval=INTERVAL_DAY_1,
                       offer_side=OFFER_SIDE_BID, start=START, end=END)
            if df is None or df.empty:
                raise RuntimeError("empty")
            df.index = pd.to_datetime(df.index, utc=True); df.index.name = "timestamp"
            df.columns = [c.lower() for c in df.columns]
            df.to_parquet(OUT / f"{name}_D1.parquet", compression="zstd")
            print(f"[{name:7s}] {len(df):>5} bars  {df.index[0].date()} -> {df.index[-1].date()}  ({time.time()-t0:.1f}s)")
            ok += 1
        except Exception as e:
            print(f"[{name:7s}] FAILED: {type(e).__name__}: {e}", file=sys.stderr)
    print(f"\n{ok}/{len(BASKET)} saved to {OUT.resolve()}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
