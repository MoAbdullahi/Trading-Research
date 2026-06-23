"""
ICT Power of 3 (P.O.3) Backtest Engine
========================================
Pattern from Examples/ folder — visible in every trade chart:

  Phase 1 — ACCUMULATION
    Price consolidates, building liquidity pools on both sides.
    Equal highs = buyside liquidity.  Equal lows = sellside liquidity.

  Phase 2 — MANIPULATION  (Turtle Soup / Liquidity Sweep)
    M15 candle wick breaches the N-bar swing level but CLOSES back inside.
      Bull sweep : high > N-bar swing high  AND  close < N-bar swing high
      Bear sweep : low  < N-bar swing low   AND  close > N-bar swing low

  Phase 3 — DISTRIBUTION  (MSS entry in opposite direction)
    After bull sweep  -> expect bearish move -> wait for M5 bearish MSS
    After bear sweep  -> expect bullish move -> wait for M5 bullish MSS
    MSS = M5 close crosses the K-bar swing in the expected direction.
    Entry at MSS bar close (GO sessions only).

  Trade management
    SL  = sweep extreme + ATR * sl_buffer   (beyond the wick)
    TP  = entry +/- risk * rr_target
    FVG = optional Fair Value Gap confluence filter
    Sweep expires after max_sweep_m15 M15 bars with no entry

Timeframes
    M15 -> swing detection + sweep trigger
    M5  -> MSS entry + trade management

GO Sessions (NY time): London KZ 02-05, London 05-08, NY AM KZ 07-10
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional
import pandas as pd
import numpy as np

_ENGINE_DIR      = Path(__file__).parent
_PROJECT_ROOT    = _ENGINE_DIR.parent
DEFAULT_DATA_DIR = _PROJECT_ROOT / "data"

SPREADS = {"XAUUSD": 0.25, "GBPUSD": 0.00008}


# ── Data loaders ──────────────────────────────────────────────────────────────

def _tz(df: pd.DataFrame) -> pd.DataFrame:
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    return df.sort_index()


def load_m15(symbol: str = "XAUUSD", data_dir: Optional[Path] = None) -> pd.DataFrame:
    p = (data_dir or DEFAULT_DATA_DIR) / "m15" / f"{symbol}_M15.parquet"
    return _tz(pd.read_parquet(p))


def load_m5(symbol: str = "XAUUSD", data_dir: Optional[Path] = None) -> pd.DataFrame:
    p = (data_dir or DEFAULT_DATA_DIR) / "m5" / f"{symbol}_M5.parquet"
    return _tz(pd.read_parquet(p))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    pc = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - pc).abs(),
        (df["low"]  - pc).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()


def _go_session(idx: pd.DatetimeIndex) -> pd.Series:
    ny = idx.tz_convert("America/New_York")
    h  = ny.hour
    return pd.Series(
        ((h >= 2) & (h < 5)) | ((h >= 5) & (h < 8)) | ((h >= 7) & (h < 10)),
        index=idx, dtype=bool,
    )


def _fvg_present(highs: pd.Series, lows: pd.Series,
                 direction: str, lookback: int = 5) -> bool:
    n = min(lookback, len(highs) - 2)
    for i in range(-n, -1):
        if direction == "bear":
            if lows.iloc[i - 1] > highs.iloc[i + 1]:
                return True
        else:
            if highs.iloc[i - 1] < lows.iloc[i + 1]:
                return True
    return False


def summarize(trades: pd.DataFrame) -> dict:
    if trades.empty:
        return {
            "n": 0, "win_rate": 0.0, "avg_r": 0.0, "total_r": 0.0,
            "pf": 0.0, "max_dd": 0.0, "max_loss_streak": 0, "exits": {},
        }
    wins   = trades[trades["realized_r"] > 0]
    losses = trades[trades["realized_r"] <= 0]
    gw = wins["realized_r"].sum()
    gl = abs(losses["realized_r"].sum())
    pf = (gw / gl) if gl > 0 else float("inf")
    cum = trades["realized_r"].cumsum()
    dd  = (cum.cummax() - cum).max()
    streak = max_streak = 0
    for r in trades["realized_r"]:
        if r <= 0:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
    return {
        "n":               len(trades),
        "win_rate":        round(100 * len(wins) / len(trades), 1),
        "avg_r":           round(trades["realized_r"].mean(), 3),
        "total_r":         round(trades["realized_r"].sum(), 2),
        "pf":              round(pf, 2) if pf != float("inf") else 999.0,
        "max_dd":          round(dd, 2),
        "max_loss_streak": max_streak,
        "exits":           trades["exit_reason"].value_counts().to_dict(),
    }


# ── Main engine ───────────────────────────────────────────────────────────────

def run_backtest(
    m15: pd.DataFrame,
    m5:  pd.DataFrame,
    *,
    swing_lookback:   int   = 20,
    mss_lookback:     int   = 10,
    rr_target:        float = 3.0,
    sl_buffer_atr:    float = 0.15,
    max_sweep_m15:    int   = 8,
    max_hold_bars:    int   = 192,
    require_fvg:      bool  = False,
    spread:           float = 0.0,
    start_date: Optional[str] = None,
    end_date:   Optional[str] = None,
) -> tuple[pd.DataFrame, dict]:

    if start_date:
        ts0 = pd.Timestamp(start_date, tz="UTC")
        m15 = m15[m15.index >= ts0]
        m5  = m5[m5.index  >= ts0]
    if end_date:
        ts1 = pd.Timestamp(end_date, tz="UTC")
        m15 = m15[m15.index <= ts1]
        m5  = m5[m5.index  <= ts1]

    if m15.empty or m5.empty:
        return pd.DataFrame(), {"error": "empty after date filter"}

    # M15 indicators
    m15 = m15.copy()
    m15["atr14"]      = _atr(m15, 14)
    m15["swing_hi"]   = m15["high"].rolling(swing_lookback).max().shift(1)
    m15["swing_lo"]   = m15["low"].rolling(swing_lookback).min().shift(1)
    m15["bull_sweep"] = (m15["high"] > m15["swing_hi"]) & (m15["close"] < m15["swing_hi"])
    m15["bear_sweep"] = (m15["low"]  < m15["swing_lo"]) & (m15["close"] > m15["swing_lo"])

    # M5 indicators
    m5 = m5.copy()
    m5["atr14"]      = _atr(m5, 14)
    m5["in_go"]      = _go_session(m5.index)
    m5["rec_hi"]     = m5["high"].rolling(mss_lookback).max().shift(1)
    m5["rec_lo"]     = m5["low"].rolling(mss_lookback).min().shift(1)
    m5["prev_close"] = m5["close"].shift(1)
    m5["bull_mss"]   = (m5["close"] > m5["rec_hi"]) & (m5["prev_close"] <= m5["rec_hi"])
    m5["bear_mss"]   = (m5["close"] < m5["rec_lo"]) & (m5["prev_close"] >= m5["rec_lo"])

    sweep_active    = False
    sweep_direction = None
    sweep_extreme   = np.nan
    sweep_bars_left = 0

    in_trade    = False
    direction   = None
    entry_price = stop = target = np.nan
    entry_time  = None
    hold_count  = 0

    trades: list[dict] = []
    meta = {
        "bull_sweeps": 0, "bear_sweeps": 0,
        "mss_signals": 0, "entries": 0, "sweep_expired": 0,
    }

    m15_ptr  = 0
    _m15_dur = pd.Timedelta("15min")

    for m5_ts, row in m5.iterrows():
        m5_close = row["close"]
        m5_hi    = row["high"]
        m5_lo    = row["low"]
        m5_atr   = row["atr14"]
        in_go    = bool(row["in_go"])

        # Advance M15 state
        while m15_ptr < len(m15):
            if m15.index[m15_ptr] + _m15_dur > m5_ts:
                break
            m15_row = m15.iloc[m15_ptr]

            if sweep_active:
                sweep_bars_left -= 1
                if sweep_bars_left <= 0:
                    sweep_active = False
                    meta["sweep_expired"] += 1

            if not in_trade:
                if bool(m15_row["bull_sweep"]) and np.isfinite(m15_row["swing_hi"]):
                    sweep_active    = True
                    sweep_direction = "bull"
                    sweep_extreme   = float(m15_row["high"])
                    sweep_bars_left = max_sweep_m15
                    meta["bull_sweeps"] += 1
                elif bool(m15_row["bear_sweep"]) and np.isfinite(m15_row["swing_lo"]):
                    sweep_active    = True
                    sweep_direction = "bear"
                    sweep_extreme   = float(m15_row["low"])
                    sweep_bars_left = max_sweep_m15
                    meta["bear_sweeps"] += 1
            m15_ptr += 1

        # Manage open trade
        if in_trade:
            hold_count += 1
            exited = False
            if direction == "bear":
                r_dist = stop - entry_price
                if m5_hi >= stop and m5_lo <= target:
                    _r, _ep, _reason = -1.0, stop, "stop"
                    exited = True
                elif m5_lo <= target:
                    _r, _ep, _reason = rr_target, target, "target"
                    exited = True
                elif m5_hi >= stop:
                    _r, _ep, _reason = -1.0, stop, "stop"
                    exited = True
                elif hold_count >= max_hold_bars:
                    _r = (entry_price - m5_close) / r_dist if r_dist > 0 else 0
                    _ep, _reason = m5_close, "max_hold"
                    exited = True
            else:
                r_dist = entry_price - stop
                if m5_lo <= stop and m5_hi >= target:
                    _r, _ep, _reason = -1.0, stop, "stop"
                    exited = True
                elif m5_hi >= target:
                    _r, _ep, _reason = rr_target, target, "target"
                    exited = True
                elif m5_lo <= stop:
                    _r, _ep, _reason = -1.0, stop, "stop"
                    exited = True
                elif hold_count >= max_hold_bars:
                    _r = (m5_close - entry_price) / r_dist if r_dist > 0 else 0
                    _ep, _reason = m5_close, "max_hold"
                    exited = True

            if exited:
                trades.append({
                    "entry_time":  entry_time,  "exit_time":   m5_ts,
                    "sweep_dir":   "bull" if direction == "bear" else "bear",
                    "direction":   direction,   "entry_price": round(entry_price, 5),
                    "stop":        round(stop, 5), "target":   round(target, 5),
                    "exit_price":  round(_ep, 5), "realized_r": round(_r, 4),
                    "exit_reason": _reason,       "hold_bars":  hold_count,
                })
                in_trade     = False
                sweep_active = False

        # Entry signal
        if in_trade or not sweep_active or not in_go:
            continue
        if not np.isfinite(m5_atr) or not np.isfinite(row["rec_hi"]):
            continue

        if sweep_direction == "bull" and bool(row["bear_mss"]):
            meta["mss_signals"] += 1
            if require_fvg and not _fvg_present(m5["high"], m5["low"], "bear"):
                continue
            sl = sweep_extreme + m5_atr * sl_buffer_atr + spread
            tp = m5_close - (sl - m5_close) * rr_target
            if m5_close < sl:
                entry_price = m5_close; stop = sl; target = tp
                entry_time  = m5_ts;    direction = "bear"
                in_trade    = True;     hold_count = 0
                meta["entries"] += 1

        elif sweep_direction == "bear" and bool(row["bull_mss"]):
            meta["mss_signals"] += 1
            if require_fvg and not _fvg_present(m5["high"], m5["low"], "bull"):
                continue
            sl = sweep_extreme - m5_atr * sl_buffer_atr - spread
            tp = m5_close + (m5_close - sl) * rr_target
            if m5_close > sl:
                entry_price = m5_close; stop = sl; target = tp
                entry_time  = m5_ts;    direction = "bull"
                in_trade    = True;     hold_count = 0
                meta["entries"] += 1

    return pd.DataFrame(trades), meta
