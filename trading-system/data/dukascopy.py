"""Dukascopy parquet loader for FX/metals backtest data.

Returns the harness-shape DataFrame (tz-aware UTC DatetimeIndex, OHLCV columns)
that run_replay consumes directly.

WARNING: `volume` is TICK volume for FX and metals, not share volume. Do not
build RVOL-style features on it expecting equity semantics -- tick count is a
much weaker signal. The CRT strong-filter keys off candle displacement (close
past the 0.5 midpoint of the prior range), not volume.

Usage:
    df = load_dukascopy_parquet("data/m15/XAUUSD_M15.parquet",
                                start="2025-01-01", end="2026-05-12")
    report = run_replay("XAUUSD", df, provider,
                        ReplayConfig(asset_class=AssetClass.GOLD))
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd


def load_dukascopy_parquet(
    path: str | Path,
    start: str | None = None,
    end: str | None = None,
) -> pd.DataFrame:
    """Load a Dukascopy M15/M5 parquet file into the harness-standard DataFrame.

    The parquet files from this project have:
      - index: `timestamp`, DatetimeIndex, datetime64[ms, UTC] -- already tz-aware
      - columns: open, high, low, close, volume (all float64)
      - volume: tick count proxy (0.3-0.9 range), NOT share volume

    Parameters
    ----------
    path  : path to the .parquet file
    start : optional ISO date string, inclusive lower bound (UTC)
    end   : optional ISO date string, inclusive upper bound (UTC)
    """
    df = pd.read_parquet(path)

    # normalise index: handle both named-column and already-indexed files
    if not isinstance(df.index, pd.DatetimeIndex):
        df = df.set_index("timestamp")

    # ensure tz-aware UTC
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")

    df = df.sort_index()

    missing = {"open", "high", "low", "close", "volume"} - set(df.columns)
    if missing:
        raise ValueError(f"parquet missing required columns: {missing}")

    if start is not None:
        df = df[df.index >= pd.Timestamp(start, tz="UTC")]
    if end is not None:
        df = df[df.index <= pd.Timestamp(end, tz="UTC")]

    return df[["open", "high", "low", "close", "volume"]]
