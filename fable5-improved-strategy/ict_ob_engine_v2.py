"""
ICT H4 OB + M5 MSS Engine v2 — review fixes applied
===================================================
  * Transaction costs + stop slippage
  * Causal regime filter (H4 SMA200) replaces hindsight "bull-only"
  * Accepts NY-anchored H4 candles
  * Fast array loop
Logic otherwise mirrors v1 (impulse OB detection, OB invalidation,
conservative both-touch resolution).
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from typing import Optional

from v2_common import atr, go_session, apply_costs


def run_ict_v2(
    h4: pd.DataFrame,
    ltf: pd.DataFrame,
    *,
    rr_target: float = 3.0,
    sl_buffer_atr: float = 0.3,
    ob_invalid_atr: float = 0.2,
    mss_lookback: int = 10,
    max_hold_bars: int = 576,
    htf_bar_size: str = "4h",
    regime_filter: bool = True,
    regime_sma: int = 200,
    spread: float = 0.25,
    slip_atr: float = 0.05,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> tuple[pd.DataFrame, dict]:

    h4 = h4.copy()
    h4["h4_atr"] = atr(h4, 14)
    h4["sma"] = h4["close"].rolling(regime_sma, min_periods=regime_sma).mean()
    body = (h4["close"] - h4["open"]).abs()
    bull_c = h4["close"] > h4["open"]
    bear_c = h4["close"] < h4["open"]
    imp_up = bull_c & (body > h4["h4_atr"] * 0.8) & (h4["close"] > h4["close"].shift(2))
    imp_dn = bear_c & (body > h4["h4_atr"] * 0.8) & (h4["close"] < h4["close"].shift(2))
    h4["new_bull_ob"] = imp_up & bear_c.shift(1).fillna(False)
    h4["new_bear_ob"] = imp_dn & bull_c.shift(1).fillna(False)
    prev_hi = h4[["open", "close"]].shift(1).max(axis=1)
    prev_lo = h4[["open", "close"]].shift(1).min(axis=1)
    h4["ob_hi"] = prev_hi
    h4["ob_lo"] = prev_lo

    ltf = ltf.copy()
    ltf["atr14"] = atr(ltf, 14)
    ltf["rec_hi"] = ltf["high"].rolling(mss_lookback).max().shift(1)
    ltf["rec_lo"] = ltf["low"].rolling(mss_lookback).min().shift(1)
    pc = ltf["close"].shift(1)
    ltf["bull_mss"] = (ltf["close"] > ltf["rec_hi"]) & (pc <= ltf["rec_hi"])
    ltf["bear_mss"] = (ltf["close"] < ltf["rec_lo"]) & (pc >= ltf["rec_lo"])

    if start_date:
        ts0 = pd.Timestamp(start_date, tz="UTC")
        h4, ltf = h4[h4.index >= ts0], ltf[ltf.index >= ts0]
    if end_date:
        ts1 = pd.Timestamp(end_date, tz="UTC")
        h4, ltf = h4[h4.index <= ts1], ltf[ltf.index <= ts1]
    if h4.empty or ltf.empty:
        return pd.DataFrame(), {"error": "empty after date filter"}

    h_close_ns = h4.index.asi8 + pd.Timedelta(htf_bar_size).value
    h_cl = h4["close"].to_numpy()
    h_atr = h4["h4_atr"].to_numpy()
    h_sma = h4["sma"].to_numpy()
    h_nbo = h4["new_bull_ob"].to_numpy()
    h_nso = h4["new_bear_ob"].to_numpy()
    h_obhi = h4["ob_hi"].to_numpy()
    h_oblo = h4["ob_lo"].to_numpy()

    l_ns = ltf.index.asi8
    a_hi, a_lo, a_cl = (ltf[c].to_numpy() for c in ("high", "low", "close"))
    a_atr = ltf["atr14"].to_numpy()
    a_go = go_session(ltf.index)
    a_rechi = ltf["rec_hi"].to_numpy()
    a_bmss = ltf["bull_mss"].to_numpy()
    a_smss = ltf["bear_mss"].to_numpy()
    idx = ltf.index

    bull_on = bear_on = False
    b_hi = b_lo = s_hi = s_lo = np.nan
    h4_atr_cur = np.nan
    trend = 0

    in_trade = False
    direction = ""
    entry = stop = target = np.nan
    e_i = hold = 0

    trades: list[dict] = []
    meta = {"h4_obs_created": 0, "entries_taken": 0, "skip_regime": 0}

    ptr, nh = 0, len(h_close_ns)

    for i in range(len(l_ns)):
        ts = l_ns[i]

        while ptr < nh and h_close_ns[ptr] <= ts:
            if np.isfinite(h_atr[ptr]):
                h4_atr_cur = h_atr[ptr]
            trend = 0 if np.isnan(h_sma[ptr]) else (1 if h_cl[ptr] > h_sma[ptr] else -1)
            if h_nbo[ptr]:
                b_hi, b_lo, bull_on = h_obhi[ptr], h_oblo[ptr], True
                meta["h4_obs_created"] += 1
            if h_nso[ptr]:
                s_hi, s_lo, bear_on = h_obhi[ptr], h_oblo[ptr], True
                meta["h4_obs_created"] += 1
            if bull_on and np.isfinite(h4_atr_cur) and h_cl[ptr] < b_lo - h4_atr_cur * ob_invalid_atr:
                bull_on = False
            if bear_on and np.isfinite(h4_atr_cur) and h_cl[ptr] > s_hi + h4_atr_cur * ob_invalid_atr:
                bear_on = False
            ptr += 1

        if in_trade:
            hold += 1
            exited = False
            risk = abs(entry - stop)
            if direction == "bull":
                if a_lo[i] <= stop:
                    _r, _ep, _rsn, exited = -1.0, stop, "stop", True
                elif a_hi[i] >= target:
                    _r, _ep, _rsn, exited = rr_target, target, "target", True
                elif hold >= max_hold_bars:
                    _r, _ep, _rsn, exited = (a_cl[i] - entry) / risk, a_cl[i], "max_hold", True
                if not exited and np.isfinite(a_atr[i]) and bull_on and \
                        a_cl[i] < b_lo - a_atr[i] * ob_invalid_atr:
                    bull_on = False
                    _r, _ep, _rsn, exited = (a_cl[i] - entry) / risk, a_cl[i], "ob_invalidated", True
            else:
                if a_hi[i] >= stop:
                    _r, _ep, _rsn, exited = -1.0, stop, "stop", True
                elif a_lo[i] <= target:
                    _r, _ep, _rsn, exited = rr_target, target, "target", True
                elif hold >= max_hold_bars:
                    _r, _ep, _rsn, exited = (entry - a_cl[i]) / risk, a_cl[i], "max_hold", True
                if not exited and np.isfinite(a_atr[i]) and bear_on and \
                        a_cl[i] > s_hi + a_atr[i] * ob_invalid_atr:
                    bear_on = False
                    _r, _ep, _rsn, exited = (entry - a_cl[i]) / risk, a_cl[i], "ob_invalidated", True
            if exited:
                trades.append({
                    "entry_time": idx[e_i], "exit_time": idx[i],
                    "direction": direction,
                    "entry_price": round(entry, 5), "stop": round(stop, 5),
                    "target": round(target, 5), "exit_price": round(_ep, 5),
                    "realized_r": round(_r, 4), "exit_reason": _rsn,
                    "hold_bars": hold, "atr_at_exit": a_atr[i],
                })
                in_trade = False

        if in_trade or not a_go[i] or not (np.isfinite(a_atr[i]) and np.isfinite(a_rechi[i])):
            continue

        if bull_on and a_cl[i] < b_lo - a_atr[i] * ob_invalid_atr:
            bull_on = False
        if bear_on and a_cl[i] > s_hi + a_atr[i] * ob_invalid_atr:
            bear_on = False

        if bull_on and a_bmss[i] and a_lo[i] <= b_hi and a_hi[i] >= b_lo and np.isfinite(b_lo):
            if regime_filter and trend != 1:
                meta["skip_regime"] += 1
            else:
                sl = b_lo - a_atr[i] * sl_buffer_atr
                if a_cl[i] > sl:
                    entry, stop = a_cl[i], sl
                    target = a_cl[i] + (a_cl[i] - sl) * rr_target
                    direction, e_i, hold = "bull", i, 0
                    in_trade = True
                    meta["entries_taken"] += 1
                    continue

        if bear_on and a_smss[i] and a_hi[i] >= s_lo and a_lo[i] <= s_hi and np.isfinite(s_hi):
            if regime_filter and trend != -1:
                meta["skip_regime"] += 1
            else:
                sl = s_hi + a_atr[i] * sl_buffer_atr
                if a_cl[i] < sl:
                    entry, stop = a_cl[i], sl
                    target = a_cl[i] - (sl - a_cl[i]) * rr_target
                    direction, e_i, hold = "bear", i, 0
                    in_trade = True
                    meta["entries_taken"] += 1

    out = apply_costs(pd.DataFrame(trades), spread, slip_atr)
    return out, meta
