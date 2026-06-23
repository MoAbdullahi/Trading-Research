"""
Resample Dukascopy M5 XAUUSD data -> H1, H4, and M15
=====================================================
Source : CRT + ICT PD Array Research project (283k M5 bars, 2022-2026)

Output (used by current strategy - M5 entry):
  data/m5/XAUUSD_M5.parquet        -- M5 as-is (entry TF)
  data/h4/XAUUSD_H1_raw.parquet    -- H1 resampled from M5
  data/h4/XAUUSD_H4.parquet        -- H4 resampled from M5

Output (saved for future M15 strategy test):
  data/m15/XAUUSD_M15.parquet      -- M15 resampled from M5

Usage:
    python data_fetch/resample_dukascopy.py
"""
from __future__ import annotations

from pathlib import Path
import pandas as pd

SRC_M5  = Path(r"C:\Users\Hashim\Desktop\CRT + ICT PD Array Research\Python_Project\data\m5\XAUUSD_M5.parquet")
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
    print("Loading M5 source data (Dukascopy XAUUSD)...")
    m5 = pd.read_parquet(SRC_M5)

    if m5.index.tz is None:
        m5.index = m5.index.tz_localize("UTC")
    m5 = m5.sort_index()

    print(f"  M5: {len(m5):,} bars  |  {m5.index.min().date()} to {m5.index.max().date()}\n")

    print("Resampling and saving...")

    # ── M5 strategy outputs ───────────────────────────────────────────────────
    _save(m5, DST_DIR / "m5" / "XAUUSD_M5.parquet", "M5  ")

    h1 = resample_ohlcv(m5, "1h")
    _save(h1, DST_DIR / "h4" / "XAUUSD_H1_raw.parquet", "H1  ")

    h4 = resample_ohlcv(m5, "4h")
    _save(h4, DST_DIR / "h4" / "XAUUSD_H4.parquet", "H4  ")

    # ── M15 set aside for future strategy test ────────────────────────────────
    m15 = resample_ohlcv(m5, "15min")
    _save(m15, DST_DIR / "m15" / "XAUUSD_M15.parquet", "M15 ")

    print("\nDone.")
    print("  Current test  : python run_backtest.py --tf 5m")
    print("  M15 data ready: data/m15/XAUUSD_M15.parquet (set aside for future use)")


if __name__ == "__main__":
    main()
