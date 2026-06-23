"""
CRT Engine v2 — review fixes applied
====================================
  * Transaction costs (round-trip spread) + slippage on stop fills
  * min_rr defaults to 2.0 — the natural-RR bucket analysis showed ALL of
    CRT's edge sits in trades with natural RR > 2 (+70R vs −89R below)
  * 5-decimal rounding (v1's 3dp corrupted GBPUSD logs: 522 trades showed
    entry == stop)
  * Accepts NY-anchored H4 candles (broker-matching dealing ranges)
  * Fast array loop (no iterrows)
Logic is otherwise identical to v1: SMA-200 trend filter, one trade per
reference candle, conservative both-touch resolution.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from typing import Optional

from v2_common import atr, crt_session, apply_costs


def run_crt_v2(
    h4: pd.DataFrame,
    ltf: pd.DataFrame,
    *,
    sl_buffer_atr: float = 0.1,
    min_range_atr: float = 0.5,
    min_rr: float = 2.0,
    trend_sma: int = 200,
    session_mode: str = "broad",
    max_hold_bars: int = 576,
    htf_bar_size: str = "4h",
    spread: float = 0.00008,
    slip_atr: float = 0.05,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> tuple[pd.DataFrame, dict]:

    # indicators on full series, then slice (warmup preserved for test windows)
    h4 = h4.copy()
    h4["h4_atr"] = atr(h4, 14)
    h4["sma"] = h4["close"].rolling(trend_sma, min_periods=trend_sma).mean()
    ltf = ltf.copy()
    ltf["atr14"] = atr(ltf, 14)

    if start_date:
        ts0 = pd.Timestamp(start_date, tz="UTC")
        h4, ltf = h4[h4.index >= ts0], ltf[ltf.index >= ts0]
    if end_date:
        ts1 = pd.Timestamp(end_date, tz="UTC")
        h4, ltf = h4[h4.index <= ts1], ltf[ltf.index <= ts1]
    if h4.empty or ltf.empty:
        return pd.DataFrame(), {"error": "empty after date filter"}

    h_close_ns = h4.index.asi8 + pd.Timedelta(htf_bar_size).value
    h_hi, h_lo, h_cl = (h4[c].to_numpy() for c in ("high", "low", "close"))
    h_atr = h4["h4_atr"].to_numpy()
    h_sma = h4["sma"].to_numpy()

    l_ns = ltf.index.asi8
    a_hi, a_lo, a_cl = (ltf[c].to_numpy() for c in ("high", "low", "close"))
    a_atr = ltf["atr14"].to_numpy()
    a_sess = crt_session(ltf.index, session_mode)
    idx = ltf.index

    ref_high = ref_low = np.nan
    h4_atr_cur = np.nan
    trend = 0                       # +1 bull / -1 bear / 0 unknown
    swept_bull = swept_bear = False
    sweep_lo, sweep_hi = np.inf, -np.inf
    ref_traded = False

    in_trade = False
    direction = ""
    entry = stop = target = np.nan
    e_i = hold = 0
    ref_hi_snap = ref_lo_snap = np.nan

    trades: list[dict] = []
    meta = {"refs_qualified": 0, "sweeps_bull": 0, "sweeps_bear": 0,
            "skipped_min_rr": 0, "entries_bull": 0, "entries_bear": 0}

    ptr, nh = 0, len(h_close_ns)

    for i in range(len(l_ns)):
        ts = l_ns[i]

        while ptr < nh and h_close_ns[ptr] <= ts:
            if np.isfinite(h_atr[ptr]):
                h4_atr_cur = h_atr[ptr]
            trend = 0 if np.isnan(h_sma[ptr]) else (1 if h_cl[ptr] > h_sma[ptr] else -1)
            if trend != 0 and np.isfinite(h4_atr_cur):
                rng = h_hi[ptr] - h_lo[ptr]
                if rng >= min_range_atr * h4_atr_cur:
                    ref_high, ref_low = h_hi[ptr], h_lo[ptr]
                    swept_bull = swept_bear = False
                    sweep_lo, sweep_hi = np.inf, -np.inf
                    ref_traded = False
                    meta["refs_qualified"] += 1
            ptr += 1

        if in_trade:
            hold += 1
            exited = False
            risk = abs(entry - stop)
            if direction == "bull":
                if a_lo[i] <= stop:
                    _r, _ep, _rsn, exited = -1.0, stop, "stop", True
                elif a_hi[i] >= target:
                    _r, _ep, _rsn, exited = (target - entry) / risk, target, "target", True
                elif hold >= max_hold_bars:
                    _r, _ep, _rsn, exited = (a_cl[i] - entry) / risk, a_cl[i], "max_hold", True
            else:
                if a_hi[i] >= stop:
                    _r, _ep, _rsn, exited = -1.0, stop, "stop", True
                elif a_lo[i] <= target:
                    _r, _ep, _rsn, exited = (entry - target) / risk, target, "target", True
                elif hold >= max_hold_bars:
                    _r, _ep, _rsn, exited = (entry - a_cl[i]) / risk, a_cl[i], "max_hold", True
            if exited:
                nat = abs(target - entry) / risk if risk > 0 else 0.0
                trades.append({
                    "entry_time": idx[e_i], "exit_time": idx[i],
                    "direction": direction,
                    "entry_price": round(entry, 5), "stop": round(stop, 5),
                    "target": round(target, 5), "exit_price": round(_ep, 5),
                    "realized_r": round(_r, 4), "natural_rr": round(nat, 2),
                    "exit_reason": _rsn, "hold_bars": hold,
                    "ref_high": round(ref_hi_snap, 5), "ref_low": round(ref_lo_snap, 5),
                    "atr_at_exit": a_atr[i],
                })
                in_trade = False

        if in_trade or ref_traded or not np.isfinite(ref_high) or not np.isfinite(a_atr[i]) or trend == 0:
            continue

        if a_lo[i] < ref_low:
            if not swept_bull:
                meta["sweeps_bull"] += 1
            swept_bull = True
            sweep_lo = min(sweep_lo, a_lo[i])
        if a_hi[i] > ref_high:
            if not swept_bear:
                meta["sweeps_bear"] += 1
            swept_bear = True
            sweep_hi = max(sweep_hi, a_hi[i])

        if not a_sess[i]:
            continue

        cl = a_cl[i]
        if swept_bull and trend == 1 and ref_low < cl <= ref_high and np.isfinite(sweep_lo):
            sl = sweep_lo - a_atr[i] * sl_buffer_atr
            tp = ref_high
            if cl > sl:
                nat = (tp - cl) / (cl - sl)
                if min_rr > 0 and nat < min_rr:
                    meta["skipped_min_rr"] += 1
                else:
                    entry, stop, target = cl, sl, tp
                    direction, e_i, hold = "bull", i, 0
                    in_trade, ref_traded = True, True
                    ref_hi_snap, ref_lo_snap = ref_high, ref_low
                    meta["entries_bull"] += 1
                continue

        if swept_bear and trend == -1 and ref_low <= cl < ref_high and np.isfinite(sweep_hi):
            sl = sweep_hi + a_atr[i] * sl_buffer_atr
            tp = ref_low
            if cl < sl:
                nat = (cl - tp) / (sl - cl)
                if min_rr > 0 and nat < min_rr:
                    meta["skipped_min_rr"] += 1
                else:
                    entry, stop, target = cl, sl, tp
                    direction, e_i, hold = "bear", i, 0
                    in_trade, ref_traded = True, True
                    ref_hi_snap, ref_lo_snap = ref_high, ref_low
                    meta["entries_bear"] += 1

    out = apply_costs(pd.DataFrame(trades), spread, slip_atr)
    return out, meta
