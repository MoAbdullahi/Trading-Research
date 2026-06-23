"""Disk cache for historical bar data.

Caches per (symbol, timeframe, start_date, end_date) to avoid repeat Alpaca
calls across backtest runs. Cache files live in data/bar_cache/ as pickle.
First access fetches and writes; subsequent reads are instant.
"""
from __future__ import annotations

import asyncio
import pickle
from datetime import datetime
from pathlib import Path

_CACHE_DIR = Path(__file__).parent / "bar_cache"


def _cache_path(symbol: str, timeframe: str, start: datetime, end: datetime) -> Path:
    key = f"{symbol}_{timeframe}_{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}.pkl"
    return _CACHE_DIR / key


async def get_bars_cached(adapter, symbol: str, timeframe: str, start: datetime, end: datetime):
    """Return cached bars or fetch-and-cache via adapter."""
    _CACHE_DIR.mkdir(exist_ok=True)
    path = _cache_path(symbol, timeframe, start, end)
    if path.exists():
        with open(path, "rb") as f:
            return pickle.load(f)
    bars = await adapter.get_historical_bars(symbol, timeframe, start, end)
    with open(path, "wb") as f:
        pickle.dump(bars, f)
    return bars
