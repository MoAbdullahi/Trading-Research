"""
Resample Dukascopy M5 GBPUSD data -> H1, H4, and M15
=====================================================
Source : CRT + ICT PD Array Research project (M5 bars)

Output:
  data/m5/GBPUSD_M5.parquet        -- M5 as-is (entry TF)
  data/h4/GBPUSD_H1_raw.parquet    -- H1 resampled from M5
  data/h4/GBPUSD_H4.parquet        -- H4 resampled from M5
  data/m15/GBPUSD_M15.parquet      -- M15 resampled from M5

Usage:
    python data_fetch/resample_gbpusd.py
"""
from __future__ import annotations

from pathlib import Path
import pandas as pd

SRC_M5  = Path(r"C:\Users\Hashim\Desktop\CRT + ICT PD Array Research\Python_Project\data\m5\GBPUSD_M5.parquet")
DST_DIR = Path(__file__).parent.parent / "data"


def _save(df: pd.DataFrame, path: Path, label: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, compression="zstd")
    print(f"  [{label}]  {len(df):>7,} bars  |  {df.index.min().date()} to {df.index.max().date()}")
    print(f"            saved -> {path}")


def resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    return (
        df.resample(rule, label="left", closed="left")
        .agg({"open": "first", "high": "max", "low": "min",
              "close": "last", "volume": "sum"})
        .dropna(subset=["open", "close"])
    )


def main() -> None:
    print("Loading M5 source data (Dukascopy GBPUSD)...")
    m5 = pd.read_parquet(SRC_M5)

    if m5.index.tz is None:
        m5.index = m5.index.tz_localize("UTC")
    m5 = m5.sort_index()

    print(f"  M5: {len(m5):,} bars  |  {m5.index.min().date()} to {m5.index.max().date()}\n")

    print("Resampling and saving...")

    _save(m5, DST_DIR / "m5" / "GBPUSD_M5.parquet", "M5  ")

    h1 = resample_ohlcv(m5, "1h")
    _save(h1, DST_DIR / "h4" / "GBPUSD_H1_raw.parquet", "H1  ")

    h4 = resample_ohlcv(m5, "4h")
    _save(h4, DST_DIR / "h4" / "GBPUSD_H4.parquet", "H4  ")

    m15 = resample_ohlcv(m5, "15min")
    _save(m15, DST_DIR / "m15" / "GBPUSD_M15.parquet", "M15 ")

    print("\nDone.")


if __name__ == "__main__":
    main()
