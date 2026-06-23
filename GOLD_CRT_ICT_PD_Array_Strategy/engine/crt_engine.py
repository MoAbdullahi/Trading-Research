"""
GOLD CRT (Candle Range Theory) Backtest Engine
===============================================
Implements the 3-candle CRT rule exactly as defined in the methodology:

  Candle 1  — Reference candle (closed HTF bar): establishes the dealing range.
  Candle 2  — Sweep / Liquidation: a LTF candle wicks BEYOND one extreme.
  Candle 3  — Confirmation / Re-entry: a LTF candle closes BACK INSIDE the range.
              This is the entry candle.

Entry rules
-----------
  Bull CRT : price sweeps below ref_low → LTF candle closes back above ref_low
             while still inside the range (close ≤ ref_high).
             Entry at that candle's close price.

  Bear CRT : price sweeps above ref_high → LTF candle closes back below ref_high
             while still inside the range (close ≥ ref_low).
             Entry at that candle's close price.

Stop-loss  : beyond the deepest sweep wick  ±  ATR(14) × sl_buffer
Take-profit: opposite extreme of the reference candle (ref_high / ref_low)

Trend filter (anti-overfitting, economically motivated)
--------------------------------------------------------
  HTF close vs H4 200-period SMA (≈33 trading days — the industry-standard
  long-term trend filter).  Only bull CRTs when HTF > SMA200; only bear CRTs
  when HTF < SMA200.  SMA200 uses only past data (no look-ahead).

Session filter
--------------
  Entry candle must fall within London or New York trading windows (NY time):
    London    : 02:00 – 08:00
    New York  : 08:00 – 13:00
  Matches the killzones stated in the CRT methodology.

Other rules
-----------
  - One trade per reference candle (mitigation rule).
  - Reference candle range must be ≥ min_range_atr × ATR(14) to qualify.
  - Maximum hold = max_hold_bars LTF bars; force-close at market price.
  - Only data available at bar-close is ever used (zero look-ahead bias).
"""
from __future__ import annotations

from typing import Optional
import numpy as np
import pandas as pd

from engine.gold_ict_engine import _atr


# ── Session helpers (NY time) ────────────────────────────────────────────────

def _crt_session(idx: pd.DatetimeIndex, mode: str = "broad") -> pd.Series:
    """
    Session windows in NY time.

    broad  : 02-13  (original — London open through NY session)
    tight  : 04-11  (removes noisy 02-03 early-London and 11-12 lunch)
    kz     : 05-10  (London body + NY AM kill zone only — highest quality)
    """
    ny = idx.tz_convert("America/New_York")
    h  = ny.hour
    if mode == "tight":
        mask = (h >= 4) & (h < 11)
    elif mode == "kz":
        mask = (h >= 5) & (h < 10)
    else:  # broad (original)
        mask = (h >= 2) & (h < 13)
    return pd.Series(mask, index=idx, dtype=bool)


# ── Main engine ───────────────────────────────────────────────────────────────

def run_crt_backtest(
    h4:  pd.DataFrame,
    ltf: pd.DataFrame,
    *,
    sl_buffer_atr:  float = 0.1,
    min_range_atr:  float = 0.5,
    min_rr:         float = 0.0,
    trend_sma:      int   = 200,
    vol_filter:     bool  = False,
    vol_period:     int   = 50,
    session_mode:   str   = "broad",
    max_hold_bars:  int   = 576,
    htf_bar_size:   str   = "4h",
    start_date: Optional[str] = None,
    end_date:   Optional[str] = None,
) -> tuple[pd.DataFrame, dict]:
    """
    Parameters
    ----------
    h4             : HTF OHLCV (4H or 1H) with UTC DatetimeIndex
    ltf            : Entry-TF OHLCV (5M or 15M) with UTC DatetimeIndex
    sl_buffer_atr  : ATR(14) multiplier added beyond sweep extreme for SL
    min_range_atr  : Minimum HTF candle range (in ATR multiples) to qualify
    min_rr         : Skip trade if natural (TP-entry)/(entry-SL) < this (0 = off)
    trend_sma      : Period of the HTF SMA used for trend bias (default 200)
    vol_filter     : If True, only trade when HTF ATR > vol_period-bar rolling mean
    vol_period     : Rolling period for the volatility regime filter (default 50)
    session_mode   : "broad" (02-13 NY) | "tight" (04-11 NY) | "kz" (05-10 NY)
    max_hold_bars  : Force-close after this many LTF bars (default 576 = 48 h × 12)
    htf_bar_size   : Duration of one HTF candle — "4h" or "1h"
    start_date     : Optional "YYYY-MM-DD" filter (inclusive)
    end_date       : Optional "YYYY-MM-DD" filter (inclusive)
    """
    # ── Date filter ───────────────────────────────────────────────────────────
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

    # ── HTF indicators (all causal — no future data) ──────────────────────────
    h4 = h4.copy()
    h4["h4_atr"] = _atr(h4, 14)
    h4["sma"]    = h4["close"].rolling(window=trend_sma, min_periods=trend_sma).mean()
    # Volatility regime: ATR vs its own rolling mean (expanding vol = trending)
    h4["atr_avg"] = h4["h4_atr"].rolling(window=vol_period, min_periods=vol_period).mean()

    # ── LTF indicators ────────────────────────────────────────────────────────
    ltf = ltf.copy()
    ltf["atr14"]     = _atr(ltf, 14)
    ltf["in_session"] = _crt_session(ltf.index, mode=session_mode)

    # ── State variables ───────────────────────────────────────────────────────
    ref_high    = ref_low    = np.nan   # current reference candle extremes
    h4_atr_cur  = np.nan                # most recent valid H4 ATR value
    trend_bias  = None                  # "bull" | "bear" | None

    swept_bull  = False                 # True once sweep below ref_low detected
    swept_bear  = False                 # True once sweep above ref_high detected
    sweep_lo    = np.inf                # deepest wick below ref_low
    sweep_hi    = -np.inf               # highest wick above ref_high
    ref_traded  = False                 # True after first trade on this reference

    in_trade    = False
    direction   = None                  # "bull" | "bear"
    entry_price = stop = target = np.nan
    entry_time  = None
    hold_count  = 0
    ref_hi_snap = ref_lo_snap = np.nan  # snapshot of reference at entry time

    vol_ok      = not vol_filter   # True when volatility condition is met

    trades: list[dict] = []
    meta = {
        "refs_qualified":   0,
        "refs_rejected":    0,
        "refs_no_trend":    0,
        "refs_low_vol":     0,   # skipped by volatility filter
        "sweeps_bull":      0,
        "sweeps_bear":      0,
        "skipped_min_rr":   0,
        "entries_bull":     0,
        "entries_bear":     0,
    }

    h4_ptr  = 0
    _htf_td = pd.Timedelta(htf_bar_size)

    # ── Bar-by-bar simulation ─────────────────────────────────────────────────
    for ltf_ts, row in ltf.iterrows():
        ltf_close   = row["close"]
        ltf_hi      = row["high"]
        ltf_lo      = row["low"]
        ltf_atr     = row["atr14"]
        in_session  = bool(row["in_session"])

        # ── 1. Advance HTF reference ──────────────────────────────────────────
        # Process all HTF bars that have fully closed before this LTF bar.
        while h4_ptr < len(h4):
            h4_ts       = h4.index[h4_ptr]
            h4_close_ts = h4_ts + _htf_td
            if h4_close_ts > ltf_ts:
                break

            h4_row     = h4.iloc[h4_ptr]
            h4_atr_val = float(h4_row["h4_atr"])
            h4_sma_val = h4_row["sma"]

            if np.isfinite(h4_atr_val):
                h4_atr_cur = h4_atr_val

            # Determine trend bias from SMA (must be fully warm)
            if not np.isnan(h4_sma_val):
                trend_bias = "bull" if float(h4_row["close"]) > float(h4_sma_val) else "bear"
            else:
                trend_bias = None   # SMA not yet warm — skip trading

            # Volatility regime check: ATR > its rolling mean
            atr_avg_val = h4_row["atr_avg"]
            if vol_filter:
                vol_ok = np.isfinite(atr_avg_val) and h4_atr_cur > float(atr_avg_val)
            else:
                vol_ok = True

            # Qualify reference candle by minimum range (and vol regime if enabled)
            if trend_bias is not None and np.isfinite(h4_atr_cur):
                rng = float(h4_row["high"]) - float(h4_row["low"])
                if not vol_ok:
                    meta["refs_low_vol"] += 1
                elif rng >= min_range_atr * h4_atr_cur:
                    ref_high   = float(h4_row["high"])
                    ref_low    = float(h4_row["low"])
                    swept_bull = False
                    swept_bear = False
                    sweep_lo   = np.inf
                    sweep_hi   = -np.inf
                    ref_traded = False
                    meta["refs_qualified"] += 1
                else:
                    meta["refs_rejected"] += 1
            elif trend_bias is None:
                meta["refs_no_trend"] += 1

            h4_ptr += 1

        # ── 2. Manage open trade ──────────────────────────────────────────────
        if in_trade:
            hold_count += 1
            exited = False

            if direction == "bull":
                r_dist = entry_price - stop
                if ltf_lo <= stop and ltf_hi >= target:
                    # Bar touches both — conservative: stop wins
                    _r, _ep, _rsn = -1.0, stop, "stop"
                    exited = True
                elif ltf_hi >= target:
                    _r = (target - entry_price) / r_dist
                    _ep, _rsn = target, "target"
                    exited = True
                elif ltf_lo <= stop:
                    _r, _ep, _rsn = -1.0, stop, "stop"
                    exited = True
                elif hold_count >= max_hold_bars:
                    _r = (ltf_close - entry_price) / r_dist
                    _ep, _rsn = ltf_close, "max_hold"
                    exited = True

            else:  # bear
                r_dist = stop - entry_price
                if ltf_hi >= stop and ltf_lo <= target:
                    _r, _ep, _rsn = -1.0, stop, "stop"
                    exited = True
                elif ltf_lo <= target:
                    _r = (entry_price - target) / r_dist
                    _ep, _rsn = target, "target"
                    exited = True
                elif ltf_hi >= stop:
                    _r, _ep, _rsn = -1.0, stop, "stop"
                    exited = True
                elif hold_count >= max_hold_bars:
                    _r = (entry_price - ltf_close) / r_dist
                    _ep, _rsn = ltf_close, "max_hold"
                    exited = True

            if exited:
                r_dist_check = abs(entry_price - stop)
                nat_rr = (
                    abs(target - entry_price) / r_dist_check
                    if r_dist_check > 0 else 0.0
                )
                trades.append({
                    "entry_time":  entry_time,
                    "exit_time":   ltf_ts,
                    "direction":   direction,
                    "entry_price": round(entry_price, 3),
                    "stop":        round(stop, 3),
                    "target":      round(target, 3),
                    "exit_price":  round(_ep, 3),
                    "realized_r":  round(_r, 4),
                    "natural_rr":  round(nat_rr, 2),
                    "exit_reason": _rsn,
                    "hold_bars":   hold_count,
                    "ref_high":    round(ref_hi_snap, 3),
                    "ref_low":     round(ref_lo_snap, 3),
                })
                in_trade = False

        # ── 3. Setup tracking + entry ─────────────────────────────────────────
        # Skip if already in a trade, no valid reference, or indicator not ready
        if in_trade or ref_traded:
            continue
        if not np.isfinite(ref_high) or not np.isfinite(ltf_atr):
            continue
        if trend_bias is None:
            continue

        # --- Track sweeps (can happen outside session) -----------------------
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

        # --- Entry: only during session, aligned with trend ------------------
        if not in_session:
            continue

        # Bull CRT: sweep of low confirmed, candle closes back inside range
        if (
            swept_bull
            and trend_bias == "bull"
            and ltf_close > ref_low           # closed back above swept level
            and ltf_close <= ref_high         # still inside range (not above TP)
            and np.isfinite(sweep_lo)
        ):
            sl = sweep_lo - ltf_atr * sl_buffer_atr
            tp = ref_high
            if ltf_close > sl:               # price is above SL (valid placement)
                nat_rr = (tp - ltf_close) / (ltf_close - sl)
                if min_rr > 0 and nat_rr < min_rr:
                    meta["skipped_min_rr"] += 1
                else:
                    entry_price  = ltf_close
                    stop         = sl
                    target       = tp
                    entry_time   = ltf_ts
                    direction    = "bull"
                    in_trade     = True
                    hold_count   = 0
                    ref_traded   = True
                    ref_hi_snap  = ref_high
                    ref_lo_snap  = ref_low
                    meta["entries_bull"] += 1
                continue

        # Bear CRT: sweep of high confirmed, candle closes back inside range
        if (
            swept_bear
            and trend_bias == "bear"
            and ltf_close < ref_high          # closed back below swept level
            and ltf_close >= ref_low          # still inside range
            and np.isfinite(sweep_hi)
        ):
            sl = sweep_hi + ltf_atr * sl_buffer_atr
            tp = ref_low
            if ltf_close < sl:
                nat_rr = (ltf_close - tp) / (sl - ltf_close)
                if min_rr > 0 and nat_rr < min_rr:
                    meta["skipped_min_rr"] += 1
                else:
                    entry_price  = ltf_close
                    stop         = sl
                    target       = tp
                    entry_time   = ltf_ts
                    direction    = "bear"
                    in_trade     = True
                    hold_count   = 0
                    ref_traded   = True
                    ref_hi_snap  = ref_high
                    ref_lo_snap  = ref_low
                    meta["entries_bear"] += 1

    return pd.DataFrame(trades), meta
