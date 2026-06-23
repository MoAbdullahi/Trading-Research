"""
CRT + ICT PD Array Research — M5 Data Acquisition
====================================================
Fetches M5 OHLCV data from Dukascopy for 6 instruments, 2022-05-12 to 2026-05-12.
This is in addition to the M15 files — keep both.

Usage:
    pip install dukascopy-python pandas pyarrow
    python fetch_m5_data.py

Output:
    ./data/m5/<INSTRUMENT>_M5.parquet
    ./data/m5/_quality_report_m5.csv

Notes:
- M5 data is ~3x bigger than M15. Expect ~300k bars per instrument.
- Total runtime: ~30-60 minutes (Dukascopy rate-limits the connection).
- Total file size: ~75-100 MB across 6 instruments.
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from dukascopy_python import (
    fetch,
    INTERVAL_MIN_5,
    OFFER_SIDE_BID,
    instruments,
)

# Configuration
START_DATE = datetime(2022, 5, 12, tzinfo=timezone.utc)
END_DATE   = datetime(2026, 5, 12, tzinfo=timezone.utc)

OUTPUT_DIR = Path("./data/m5")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

INSTRUMENTS = {
    "EURUSD": (instruments.INSTRUMENT_FX_MAJORS_EUR_USD,   "EURUSD"),
    "GBPUSD": (instruments.INSTRUMENT_FX_MAJORS_GBP_USD,   "GBPUSD"),
    "USDJPY": (instruments.INSTRUMENT_FX_MAJORS_USD_JPY,   "USDJPY"),
    "XAUUSD": (instruments.INSTRUMENT_FX_METALS_XAU_USD,   "XAUUSD"),
    "NAS100": (instruments.INSTRUMENT_IDX_AMERICA_E_NQ_100, "US100.cash"),
    "US30":   (instruments.INSTRUMENT_IDX_AMERICA_E_D_J_IND, "US30.cash"),
}


def fetch_instrument(name: str, duka_symbol: str) -> pd.DataFrame:
    print(f"[{name}] Fetching {duka_symbol} (M5)...", flush=True)
    t0 = time.time()
    df = fetch(
        instrument=duka_symbol,
        interval=INTERVAL_MIN_5,
        offer_side=OFFER_SIDE_BID,
        start=START_DATE,
        end=END_DATE,
    )
    df.index = pd.to_datetime(df.index, utc=True)
    df.index.name = "timestamp"
    df.columns = [c.lower() for c in df.columns]
    elapsed = time.time() - t0
    print(f"[{name}]   -> {len(df):,} bars in {elapsed:.1f}s", flush=True)
    return df


def quality_check(name: str, df: pd.DataFrame) -> dict:
    rep = {
        "instrument": name,
        "rows": len(df),
        "start": df.index.min(),
        "end":   df.index.max(),
        "duplicate_timestamps": int(df.index.duplicated().sum()),
        "nan_rows": int(df.isna().any(axis=1).sum()),
    }
    deltas = df.index.to_series().diff().dt.total_seconds().div(60)
    # M5 cadence: 5 min. Anything > 10 min and < 40h on a weekday is suspect.
    suspect = deltas[(deltas > 10) & (deltas < 40 * 60)]
    rep["suspect_intra_gaps"] = int(len(suspect))
    rep["max_gap_minutes"] = float(deltas.max()) if len(deltas) else 0.0
    bad_high = (df["high"] < df[["open", "close"]].max(axis=1)).sum()
    bad_low  = (df["low"]  > df[["open", "close"]].min(axis=1)).sum()
    rep["bad_high_rows"] = int(bad_high)
    rep["bad_low_rows"]  = int(bad_low)
    rep["zero_range_bars"] = int(((df["high"] - df["low"]) == 0).sum())
    return rep


def main() -> int:
    print(f"Range: {START_DATE.isoformat()} -> {END_DATE.isoformat()}")
    print(f"Output: {OUTPUT_DIR.resolve()}\n")

    reports = []
    failures = 0

    for name, (duka_symbol, ftmo_symbol) in INSTRUMENTS.items():
        try:
            df = fetch_instrument(name, duka_symbol)
            if df.empty:
                raise RuntimeError("Empty dataframe returned")
            out_path = OUTPUT_DIR / f"{name}_M5.parquet"
            df.to_parquet(out_path, compression="zstd")

            rep = quality_check(name, df)
            rep["status"] = "OK"
            rep["file"] = str(out_path)
            rep["ftmo_symbol_ref"] = ftmo_symbol
            print(f"[{name}]   saved -> {out_path}")
        except Exception as e:
            failures += 1
            rep = {
                "instrument": name,
                "status": "FAIL",
                "error": f"{type(e).__name__}: {e}",
                "ftmo_symbol_ref": ftmo_symbol,
            }
            print(f"[{name}]   FAILED: {e}", file=sys.stderr)
        reports.append(rep)
        print()

    rep_df = pd.DataFrame(reports)
    rep_path = OUTPUT_DIR / "_quality_report_m5.csv"
    rep_df.to_csv(rep_path, index=False)

    print("=" * 80)
    print("M5 QUALITY REPORT")
    print("=" * 80)
    with pd.option_context(
        "display.max_columns", None,
        "display.width", 200,
        "display.max_colwidth", 40,
    ):
        print(rep_df.to_string(index=False))
    print(f"\nReport saved -> {rep_path}")
    print(f"\nSummary: {len(reports) - failures}/{len(reports)} succeeded.")

    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
