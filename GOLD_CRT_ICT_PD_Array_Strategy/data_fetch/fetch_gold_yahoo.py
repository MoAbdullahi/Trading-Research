"""
GOLD ICT Strategy — Yahoo Finance Data Fetcher
===============================================
Downloads Gold (GC=F) OHLCV data from Yahoo Finance.

Ticker: GC=F (Gold Futures continuous contract)

Yahoo Finance data limits:
  - Daily  : full history from 2010+  -> covers 2021-2026 ✓
  - 1H     : last ~730 days (~2 years) -> covers ~2024-2026
  - 5M     : last 60 days only         -> covers last 2 months

What this script produces:
  data/daily/XAUUSD_D1.parquet   — full 2021-2026 daily bars
  data/h4/XAUUSD_H4.parquet      — 4H bars resampled from 1H (~2 years)
  data/h4/XAUUSD_H1_raw.parquet  — raw 1H bars (source for 4H)
  data/m5/XAUUSD_M5.parquet      — 5M bars (last 60 days)

NOTE: For a full 2021-2026 5M/1H backtest, a premium source is needed.
      This project uses Yahoo's available range and clearly reports coverage.

Usage:
    pip install yfinance pandas pyarrow
    python data_fetch/fetch_gold_yahoo.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd

try:
    import yfinance as yf
except ImportError:
    print("ERROR: yfinance not installed. Run: pip install yfinance", file=sys.stderr)
    sys.exit(1)

TICKER     = "GC=F"
START_FULL = "2021-01-01"
END_FULL   = "2026-06-01"

_HERE      = Path(__file__).parent
DATA_DIR   = _HERE.parent / "data"


def _download(ticker: str, interval: str, start: str, end: str) -> pd.DataFrame:
    """Download from Yahoo Finance and normalise columns/index."""
    df = yf.download(
        ticker,
        interval=interval,
        start=start,
        end=end,
        auto_adjust=True,
        progress=False,
        multi_level_index=False,
    )
    if df is None or df.empty:
        return pd.DataFrame()

    df.columns = [c.lower() for c in df.columns]
    df.index   = pd.to_datetime(df.index, utc=True)
    df.index.name = "timestamp"

    cols = [c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]
    df   = df[cols].dropna(subset=["open", "close"])
    return df.sort_index()


def resample_to_4h(df_1h: pd.DataFrame) -> pd.DataFrame:
    return (
        df_1h
        .resample("4h", label="left", closed="left")
        .agg({"open": "first", "high": "max", "low": "min",
              "close": "last", "volume": "sum"})
        .dropna(subset=["open"])
    )


def _save(df: pd.DataFrame, path: Path, label: str) -> None:
    if df.empty:
        print(f"  [{label}] EMPTY — nothing saved.")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, compression="zstd")
    print(f"  [{label}] {len(df):,} bars  |  {df.index.min().date()} -> {df.index.max().date()}")
    print(f"           saved -> {path}")


def main() -> int:
    print(f"=== GOLD Yahoo Fetcher  |  ticker={TICKER} ===\n")

    # ── 1. Daily 2021-2026 ────────────────────────────────────────────────────
    print("[1/3] Daily bars  (2021-01-01 -> 2026-06-01)")
    daily = _download(TICKER, "1d", START_FULL, END_FULL)
    _save(daily, DATA_DIR / "daily" / "XAUUSD_D1.parquet", "Daily")

    # ── 2. 1H -> resample to 4H (Yahoo limit: 730 days back from today) ─────────
    print("\n[2/3] 1H bars  (Yahoo limit: last 730 days from today ~2 years)")
    now      = datetime.now(timezone.utc)
    h1_start = (now - timedelta(days=729)).strftime("%Y-%m-%d")
    h1_end   = now.strftime("%Y-%m-%d")
    h1 = _download(TICKER, "1h", h1_start, h1_end)
    _save(h1, DATA_DIR / "h4" / "XAUUSD_H1_raw.parquet", "1H raw")

    if not h1.empty:
        h4 = resample_to_4h(h1)
        _save(h4, DATA_DIR / "h4" / "XAUUSD_H4.parquet", "4H resampled")
    else:
        print("  [4H] Skipped — no 1H data.")

    # ── 3. 5M last 60 days ────────────────────────────────────────────────────
    print("\n[3/3] 5M bars  (last 60 days — Yahoo limit)")
    now      = datetime.now(timezone.utc)
    m5_start = (now - timedelta(days=58)).strftime("%Y-%m-%d")
    m5_end   = now.strftime("%Y-%m-%d")
    m5 = _download(TICKER, "5m", m5_start, m5_end)
    _save(m5, DATA_DIR / "m5" / "XAUUSD_M5.parquet", "5M")

    print("\n=== Coverage summary ===")
    print("  4H analysis : resampled from 1H  (~2024-2026 on Yahoo)")
    print("  5M entry    : last 60 days only  (Yahoo hard limit)")
    print("  For full 2021-2026 coverage at 1H/5M, export from MT5 or use Dukascopy.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
