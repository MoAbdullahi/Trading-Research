"""
GOLD CRT Full Strategy Engine
==============================
Combines three ICT components into one high-RR strategy:

  1. CRT Reference Candle (HTF — 4H or 1H)
     - Each completed candle defines a dealing range [ref_low, ref_high]
     - Range must be >= min_range_atr * ATR to qualify

  2. Liquidity Sweep (LTF — 5M or 15M)
     - Bull setup : a 5M candle wicks BELOW ref_low  (sell-side liquidity taken)
     - Bear setup : a 5M candle wicks ABOVE ref_high (buy-side liquidity taken)
     - The lowest/highest wick becomes the SL anchor

  3. OB Formation + MSS Entry (LTF)
     - After the sweep, the engine marks the last opposing-colour 5M candle
       before the sweep extreme as the micro Order Block (OB)
     - Entry triggers on a 5M Market Structure Shift (MSS) — a close above
       the mss_lookback-bar high (bull) or below the low (bear) — that occurs
       AFTER the sweep AND while price is inside the reference range
     - SL  = sweep_extreme - ATR*sl_buffer  (bull)
             sweep_extreme + ATR*sl_buffer  (bear)
     - TP  = ref_high  (bull)  /  ref_low  (bear)   ← full CRT range target

  4. Minimum RR Gate
     - Natural RR = (TP - entry) / (entry - SL)
     - Trade is skipped if natural RR < min_rr (default 2.0)
     - This keeps only setups where the sweep is tight relative to the range

  Session filter: London KZ 02-05, London 05-08, NY AM KZ 07-10 (NY time)
  One trade per reference candle.  Reset on each new HTF bar.
  Max hold = max_hold_bars LTF bars → force-close at market.
"""
from __future__ import annotations

from typing import Optional
import numpy as np
import pandas as pd

from engine.gold_ict_engine import _atr, _go_session


def run_crt_full_backtest(
    h4:  pd.DataFrame,
    ltf: pd.DataFrame,
    *,
    sl_buffer_atr:  float = 0.1,
    min_range_atr:  float = 0.5,
    min_rr:         float = 2.0,
    mss_lookback:   int   = 10,
    max_hold_bars:  int   = 576,
    htf_bar_size:   str   = "4h",
    start_date: Optional[str] = None,
    end_date:   Optional[str] = None,
) -> tuple[pd.DataFrame, dict]:
    """
    Parameters
    ----------
    h4             : HTF OHLCV (4H or 1H) UTC DatetimeIndex
    ltf            : Entry-TF OHLCV (5M or 15M) UTC DatetimeIndex
    sl_buffer_atr  : ATR multiplier beyond sweep extreme for SL
    min_range_atr  : HTF candle must be this many ATRs wide to qualify
    min_rr         : Skip trade if natural (TP-entry)/(entry-SL) < this
    mss_lookback   : Bars for MSS swing detection
    max_hold_bars  : Force-close after this many LTF bars
    htf_bar_size   : "4h" or "1h"
    """
    if start_date:
        ts0 = pd.Timestamp(start_date, tz="UTC")
        h4  = h4[h4.index >= ts0]
        ltf = ltf[ltf.index >= ts0]
    if end_date:
        ts1 = pd.Timestamp(end_date, tz="UTC")
        h4  = h4[h4.index <= ts1]
        ltf = ltf[ltf.index <= ts1]

    if h4.empty or ltf.empty:
        return pd.DataFrame(), {"error": "empty data after date filter"}

    # ── HTF ATR ───────────────────────────────────────────────────────────────
    h4 = h4.copy()
    h4["h4_atr"] = _atr(h4, 14)

    # ── LTF indicators ────────────────────────────────────────────────────────
    ltf = ltf.copy()
    ltf["atr14"]      = _atr(ltf, 14)
    ltf["in_go"]      = _go_session(ltf.index)
    ltf["rec_hi"]     = ltf["high"].rolling(mss_lookback).max().shift(1)
    ltf["rec_lo"]     = ltf["low"].rolling(mss_lookback).min().shift(1)
    ltf["prev_close"] = ltf["close"].shift(1)
    ltf["bull_mss"]   = (ltf["close"] > ltf["rec_hi"]) & (ltf["prev_close"] <= ltf["rec_hi"])
    ltf["bear_mss"]   = (ltf["close"] < ltf["rec_lo"]) & (ltf["prev_close"] >= ltf["rec_lo"])

    # ── State ─────────────────────────────────────────────────────────────────
    ref_high = ref_low = h4_atr_cur = np.nan

    # Sweep state (reset each new reference candle)
    swept_bull = swept_bear = False
    sweep_lo   = np.inf     # lowest wick during bull sweep
    sweep_hi   = -np.inf    # highest wick during bear sweep

    # Trade state
    in_trade    = False
    direction   = None
    entry_price = stop = target = np.nan
    entry_time  = None
    hold_count  = 0
    ref_hi_at_entry = ref_lo_at_entry = np.nan

    trades: list[dict] = []
    meta = {
        "refs_used":        0,
        "refs_skipped":     0,
        "sweeps_bull":      0,
        "sweeps_bear":      0,
        "mss_after_sweep":  0,
        "skipped_min_rr":   0,
        "entries_taken":    0,
    }

    h4_ptr  = 0
    _htf_td = pd.Timedelta(htf_bar_size)

    # ── Bar-by-bar simulation ─────────────────────────────────────────────────
    for ltf_ts, row in ltf.iterrows():
        ltf_close = row["close"]
        ltf_hi    = row["high"]
        ltf_lo    = row["low"]
        ltf_atr   = row["atr14"]
        in_go     = bool(row["in_go"])

        # ── 1. Advance HTF reference ──────────────────────────────────────────
        while h4_ptr < len(h4):
            h4_ts       = h4.index[h4_ptr]
            h4_close_ts = h4_ts + _htf_td
            if h4_close_ts > ltf_ts:
                break

            h4_row     = h4.iloc[h4_ptr]
            h4_atr_cur = float(h4_row["h4_atr"]) if np.isfinite(h4_row["h4_atr"]) else h4_atr_cur

            if np.isfinite(h4_atr_cur):
                rng = float(h4_row["high"]) - float(h4_row["low"])
                if rng >= min_range_atr * h4_atr_cur:
                    ref_high = float(h4_row["high"])
                    ref_low  = float(h4_row["low"])
                    swept_bull = swept_bear = False
                    sweep_lo   = np.inf
                    sweep_hi   = -np.inf
                    meta["refs_used"] += 1
                else:
                    meta["refs_skipped"] += 1

            h4_ptr += 1

        # ── 2. Manage open trade ──────────────────────────────────────────────
        if in_trade:
            hold_count += 1
            exited = False

            if direction == "bull":
                r_dist = entry_price - stop
                if ltf_lo <= stop and ltf_hi >= target:
                    _r, _ep, _reason = -1.0, stop, "stop"
                    exited = True
                elif ltf_hi >= target:
                    _r = (target - entry_price) / r_dist
                    _ep, _reason = target, "target"
                    exited = True
                elif ltf_lo <= stop:
                    _r, _ep, _reason = -1.0, stop, "stop"
                    exited = True
                elif hold_count >= max_hold_bars:
                    _r = (ltf_close - entry_price) / r_dist
                    _ep, _reason = ltf_close, "max_hold"
                    exited = True
            else:
                r_dist = stop - entry_price
                if ltf_hi >= stop and ltf_lo <= target:
                    _r, _ep, _reason = -1.0, stop, "stop"
                    exited = True
                elif ltf_lo <= target:
                    _r = (entry_price - target) / r_dist
                    _ep, _reason = target, "target"
                    exited = True
                elif ltf_hi >= stop:
                    _r, _ep, _reason = -1.0, stop, "stop"
                    exited = True
                elif hold_count >= max_hold_bars:
                    _r = (entry_price - ltf_close) / r_dist
                    _ep, _reason = ltf_close, "max_hold"
                    exited = True

            if exited:
                trades.append({
                    "entry_time":  entry_time,
                    "exit_time":   ltf_ts,
                    "direction":   direction,
                    "entry_price": entry_price,
                    "stop":        stop,
                    "target":      target,
                    "exit_price":  round(_ep, 3),
                    "realized_r":  round(_r, 4),
                    "natural_rr":  round((target - entry_price) / (entry_price - stop)
                                         if direction == "bull"
                                         else (entry_price - target) / (stop - entry_price), 2),
                    "exit_reason": _reason,
                    "hold_bars":   hold_count,
                    "ref_high":    round(ref_hi_at_entry, 3),
                    "ref_low":     round(ref_lo_at_entry, 3),
                })
                in_trade = False

        # ── 3. Setup tracking + entry ─────────────────────────────────────────
        if in_trade or not in_go:
            continue
        if not np.isfinite(ltf_atr) or not np.isfinite(ref_high):
            continue
        if not np.isfinite(row["rec_hi"]):
            continue

        # Track sweeps (5M candle wicks beyond the reference range)
        if ltf_lo < ref_low:
            if not swept_bull:
                meta["sweeps_bull"] += 1
            swept_bull = True
            sweep_lo   = min(sweep_lo, ltf_lo)

        if ltf_hi > ref_high:
            if not swept_bear:
                meta["sweeps_bear"] += 1
            swept_bear = True
            sweep_hi   = max(sweep_hi, ltf_hi)

        # ── Bull CRT + MSS entry ──────────────────────────────────────────────
        if swept_bull and bool(row["bull_mss"]):
            # Price must be inside the reference range
            in_range = ltf_close <= ref_high and ltf_close >= ref_low
            if in_range and np.isfinite(sweep_lo):
                meta["mss_after_sweep"] += 1
                sl = sweep_lo - ltf_atr * sl_buffer_atr
                tp = ref_high
                if ltf_close > sl:
                    rr = (tp - ltf_close) / (ltf_close - sl)
                    if rr >= min_rr:
                        entry_price      = ltf_close
                        stop             = sl
                        target           = tp
                        entry_time       = ltf_ts
                        direction        = "bull"
                        in_trade         = True
                        hold_count       = 0
                        swept_bull       = False
                        ref_hi_at_entry  = ref_high
                        ref_lo_at_entry  = ref_low
                        meta["entries_taken"] += 1
                        continue
                    else:
                        meta["skipped_min_rr"] += 1

        # ── Bear CRT + MSS entry ──────────────────────────────────────────────
        if swept_bear and bool(row["bear_mss"]):
            in_range = ltf_close >= ref_low and ltf_close <= ref_high
            if in_range and np.isfinite(sweep_hi):
                meta["mss_after_sweep"] += 1
                sl = sweep_hi + ltf_atr * sl_buffer_atr
                tp = ref_low
                if ltf_close < sl:
                    rr = (ltf_close - tp) / (sl - ltf_close)
                    if rr >= min_rr:
                        entry_price      = ltf_close
                        stop             = sl
                        target           = tp
                        entry_time       = ltf_ts
                        direction        = "bear"
                        in_trade         = True
                        hold_count       = 0
                        swept_bear       = False
                        ref_hi_at_entry  = ref_high
                        ref_lo_at_entry  = ref_low
                        meta["entries_taken"] += 1
                    else:
                        meta["skipped_min_rr"] += 1

    return pd.DataFrame(trades), meta
