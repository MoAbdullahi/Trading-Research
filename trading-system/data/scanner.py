"""In-play daily scanner — the selection layer Aziz calls "stocks in play."

A symbol is "in play" on a given day if it shows evidence of a fresh catalyst:
gap at open, elevated early volume, and sufficient daily range to be tradeable.
This is a proxy (gap + RVOL) for the catalyst flag that the macro/sentiment
agents will eventually provide; it catches the observable fingerprint without
requiring a live news feed.

Criteria (all must pass):
  gap_pct    — |today_open − prev_close| / prev_close × 100 ≥ min_gap_pct
  open_rvol  — first `rvol_window_bars` bars volume / trailing 20-day avg ≥ min_open_rvol
  atr        — 14-bar ATR of prev_bars ≥ min_atr_dollars (filters untradeable names)
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class InPlayCriteria:
    min_gap_pct: float = 3.0       # absolute gap (either direction) at open
    min_open_rvol: float = 2.0     # early-session RVOL vs trailing average
    min_atr_dollars: float = 0.50  # 14-bar ATR floor (dollar, not %)
    rvol_window_bars: int = 30     # bars used for opening-volume comparison (~30 min)
    min_prev_days: int = 5         # minimum prior-day data to compute baselines


def _first_n_volumes(bars: pd.DataFrame, n: int) -> pd.Series:
    """First-N-bar volumes for each trading date in bars (ET local grouping)."""
    local = bars.index.tz_convert("America/New_York")
    dates = local.date
    vols = []
    for d in sorted(set(dates)):
        day_slice = bars[dates == d]
        vols.append(float(day_slice["volume"].iloc[:n].sum()))
    return pd.Series(vols)


def is_in_play(
    day_bars: pd.DataFrame,
    prev_bars: pd.DataFrame,
    criteria: InPlayCriteria | None = None,
) -> tuple[bool, dict]:
    """
    day_bars  — RTH 1-min bars for the candidate day (UTC, ascending).
    prev_bars — RTH 1-min bars for the preceding N trading days (same symbol).
    Returns (passes, stats) where stats carries the computed values for logging.
    """
    c = criteria or InPlayCriteria()

    if day_bars.empty:
        return False, {"reason": "no_bars"}

    today_open = float(day_bars["open"].iloc[0])

    # --- gap % ---
    prev_close = float(prev_bars["close"].iloc[-1]) if not prev_bars.empty else None
    gap = abs(today_open - prev_close) / prev_close * 100 if prev_close else 0.0

    # --- Daily range proxy (previous session high-low) ---
    # 1-min ATR is ~$0.02 for a $15 stock — wrong scale for min_atr_dollars.
    # Use the previous trading day's full intraday range as the daily-scale proxy.
    atr_val = 0.0
    if not prev_bars.empty:
        prev_local_dates = prev_bars.index.tz_convert("America/New_York").date
        last_date = prev_local_dates[-1]
        last_day_bars = prev_bars[prev_local_dates == last_date]
        if not last_day_bars.empty:
            atr_val = float(last_day_bars["high"].max() - last_day_bars["low"].min())

    # --- opening RVOL ---
    n = c.rvol_window_bars
    today_vol = float(day_bars["volume"].iloc[:n].sum())
    prev_vols = _first_n_volumes(prev_bars, n)
    avg_vol = float(prev_vols.mean()) if len(prev_vols) >= c.min_prev_days else 0.0
    rvol = today_vol / avg_vol if avg_vol > 0 else 0.0

    stats = {
        "gap_pct": round(gap, 2),
        "open_rvol": round(rvol, 2),
        "atr": round(atr_val, 3),
    }

    passes = (
        gap >= c.min_gap_pct
        and rvol >= c.min_open_rvol
        and atr_val >= c.min_atr_dollars
    )
    return passes, stats
