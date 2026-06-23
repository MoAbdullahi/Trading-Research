"""Layer 2 — deterministic quant feature engine.

All features compute strictly on CLOSED bars to prevent look-ahead bias: the
caller passes a frame whose last row is the most recently *closed* bar. No
randomness, no network, no LLM — fully unit-testable and reproducible.

Pandas is used for readability; the hot paths are vectorized. Swap to Polars
later without changing the public surface (compute_features -> FeatureSnapshot).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time
from typing import Optional

import numpy as np
import pandas as pd

from config.sessions import SessionProfile, VwapAnchorMode


# --------------------------------------------------------------------------- #
# Output contract
# --------------------------------------------------------------------------- #
@dataclass
class FeatureSnapshot:
    symbol: str
    ts: pd.Timestamp
    last_close: float
    orb_high: Optional[float]
    orb_low: Optional[float]
    vwap: Optional[float]
    rvol: Optional[float]
    rsi: Optional[float]
    atr: Optional[float]
    ema: dict[int, float] = field(default_factory=dict)
    support_levels: list[float] = field(default_factory=list)
    resistance_levels: list[float] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Primitive indicators
# --------------------------------------------------------------------------- #
def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    return (100 - (100 / (1 + rs))).fillna(100.0)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


# --------------------------------------------------------------------------- #
# Session-aware VWAP
# --------------------------------------------------------------------------- #
def _anchor_mask(df: pd.DataFrame, profile: SessionProfile) -> pd.Series:
    """Return a grouping key so VWAP resets at the right anchor per asset class."""
    idx = df.index
    mode = profile.vwap_anchor
    if mode == VwapAnchorMode.SESSION_OPEN:
        # group by trading date in the profile timezone (reset each 09:30 RTH day)
        local = idx.tz_convert(profile.tz)
        return pd.Series(local.date, index=idx)
    if mode == VwapAnchorMode.UTC_MIDNIGHT:
        return pd.Series(idx.tz_convert("UTC").date, index=idx)
    if mode == VwapAnchorMode.ROLLING_24H:
        # rolling handled separately; group key unused
        return pd.Series(idx.tz_convert("UTC").date, index=idx)
    # MULTI_SESSION: anchor at the most recent session open among windows
    local = idx.tz_convert(profile.tz)
    keys = []
    opens = sorted(w.open_t for w in profile.windows)
    for ts in local:
        anchor = max([o for o in opens if o <= ts.time()], default=opens[0])
        keys.append((ts.date(), anchor))
    return pd.Series(keys, index=idx)


def session_vwap(df: pd.DataFrame, profile: SessionProfile) -> pd.Series:
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    tpv = typical * df["volume"]
    if profile.vwap_anchor == VwapAnchorMode.ROLLING_24H:
        # assumes a uniform bar interval; window = 24h / interval
        window = max(1, int(pd.Timedelta("24h") / (df.index[1] - df.index[0]))) if len(df) > 1 else 1
        return tpv.rolling(window).sum() / df["volume"].rolling(window).sum()
    grp = _anchor_mask(df, profile)
    cum_tpv = tpv.groupby(grp).cumsum()
    cum_vol = df["volume"].groupby(grp).cumsum()
    return cum_tpv / cum_vol.replace(0.0, np.nan)


# --------------------------------------------------------------------------- #
# Opening Range Breakout levels (session-aware)
# --------------------------------------------------------------------------- #
def orb_levels(df: pd.DataFrame, profile: SessionProfile) -> tuple[Optional[float], Optional[float]]:
    """High/low of the first `orb_minutes` of the current session window."""
    if profile.continuous:
        return None, None  # ORB undefined for 24/7 continuous assets (gold, crypto)
    local = df.index.tz_convert(profile.tz)
    open_t = sorted(w.open_t for w in profile.windows)[0]
    today = local[-1].date()
    start = pd.Timestamp.combine(today, open_t)
    end = pd.Timestamp.combine(today, _add_minutes(open_t, profile.orb_minutes))
    mask = (local.date == today) & (local.time >= start.time()) & (local.time < end.time())
    window = df[mask]
    if window.empty:
        return None, None
    return float(window["high"].max()), float(window["low"].min())


def _add_minutes(t: time, minutes: int) -> time:
    total = t.hour * 60 + t.minute + minutes
    return time((total // 60) % 24, total % 60)


# --------------------------------------------------------------------------- #
# Support / Resistance: sliding-window extrema + KDE clustering
# --------------------------------------------------------------------------- #
def _local_extrema(df: pd.DataFrame, left: int = 3, right: int = 3) -> tuple[list[float], list[float]]:
    highs, lows = df["high"].values, df["low"].values
    n = len(df)
    res, sup = [], []
    for i in range(left, n - right):
        hi_win = highs[i - left : i + right + 1]
        lo_win = lows[i - left : i + right + 1]
        if highs[i] == hi_win.max():
            res.append(float(highs[i]))
        if lows[i] == lo_win.min():
            sup.append(float(lows[i]))
    return sup, res


def _kde_cluster(prices: list[float], max_levels: int = 4) -> list[float]:
    """Cluster touch-prices into zones via Gaussian KDE; return density-peak prices."""
    if len(prices) < 3:
        return sorted(set(round(p, 4) for p in prices))
    try:
        from scipy.stats import gaussian_kde
    except ImportError:  # graceful fallback if scipy absent
        return sorted(set(round(p, 4) for p in prices))[:max_levels]
    arr = np.asarray(prices, dtype=float)
    kde = gaussian_kde(arr)
    grid = np.linspace(arr.min(), arr.max(), 400)
    dens = kde(grid)
    # local maxima of the density curve = clustered levels
    peaks = [grid[i] for i in range(1, len(grid) - 1) if dens[i] > dens[i - 1] and dens[i] > dens[i + 1]]
    peaks.sort(key=lambda x: -kde(np.array([x]))[0])
    return sorted(round(float(p), 4) for p in peaks[:max_levels])


def support_resistance(df: pd.DataFrame, left: int = 3, right: int = 3) -> tuple[list[float], list[float]]:
    sup_raw, res_raw = _local_extrema(df, left, right)
    return _kde_cluster(sup_raw), _kde_cluster(res_raw)


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #
def compute_features(
    df: pd.DataFrame,
    profile: SessionProfile,
    symbol: str,
    ema_periods: tuple[int, ...] = (9, 20, 50, 200),
    rvol_lookback: int = 20,
) -> FeatureSnapshot:
    """`df` must be indexed by tz-aware UTC timestamps, sorted ascending, and
    contain ONLY closed bars (drop the forming bar before calling)."""
    if df.empty:
        raise ValueError("empty frame")
    if df.index.tz is None:
        raise ValueError("index must be tz-aware (UTC)")

    vwap_series = session_vwap(df, profile)
    rsi_series = rsi(df["close"])
    atr_series = atr(df)
    orb_hi, orb_lo = orb_levels(df, profile)
    sup, res = support_resistance(df)

    vol_sma = df["volume"].rolling(rvol_lookback).mean()
    rvol = float(df["volume"].iloc[-1] / vol_sma.iloc[-1]) if vol_sma.iloc[-1] else None

    emas = {p: float(ema(df["close"], p).iloc[-1]) for p in ema_periods if len(df) >= 1}

    return FeatureSnapshot(
        symbol=symbol,
        ts=df.index[-1],
        last_close=float(df["close"].iloc[-1]),
        orb_high=orb_hi,
        orb_low=orb_lo,
        vwap=float(vwap_series.iloc[-1]) if not np.isnan(vwap_series.iloc[-1]) else None,
        rvol=rvol,
        rsi=float(rsi_series.iloc[-1]),
        atr=float(atr_series.iloc[-1]),
        ema=emas,
        support_levels=sup,
        resistance_levels=res,
    )
