"""
P.O.3 Engine v2 — all review fixes + ICT_MultiTF methodology additions
======================================================================
Fixes vs v1:
  * FVG filter is now CAUSAL (precomputed rolling columns; v1 looked at the
    last 5 bars of the whole dataset — look-ahead + constant result)
  * Transaction costs charged on every trade (round-trip spread) and
    ATR-based slippage on stop fills
  * Causal HTF regime filter (NY-anchored H4 SMA200, or D1 SMA200 via
    regime_daily) replaces hindsight "bull-only" filtering
  * NY 17:00-anchored H4 candles (broker-matching)

Additions from ICT_MultiTF_Strategy + Examples folder:
  * Premium/Discount filter — longs only in discount (below range midpoint),
    shorts only in premium (step 2 of the methodology)
  * Structural take-profit mode — TP at the opposite liquidity pool ($$$ in
    the example charts) instead of fixed RR (step 11)
  * Spread buffering on fills (step 9)

Timeframe-agnostic: `sweep_df` is the sweep-detection TF (M15 or H1, set
`sweep_bar_minutes`), `entry_df` is the entry/management TF (M5 or M15).
`max_hold_bars`, `mss_lookback` are in entry-TF bars; `swing_lookback`,
`max_sweep_bars`, `pd_lookback` are in sweep-TF bars.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from typing import Optional

from v2_common import atr, go_session, resample_h4_ny, causal_map, apply_costs


def run_po3_v2(
    sweep_df: pd.DataFrame,
    entry_df: pd.DataFrame,
    *,
    sweep_bar_minutes: int = 15,
    swing_lookback: int = 20,
    mss_lookback: int = 10,
    rr_target: float = 3.0,
    sl_buffer_atr: float = 0.15,
    max_sweep_bars: int = 8,
    max_hold_bars: int = 192,
    require_fvg: bool = False,
    fvg_lookback: int = 5,
    regime_filter: bool = True,
    regime_sma: int = 200,
    regime_daily: Optional[pd.DataFrame] = None,   # D1 OHLC; if given, D1 SMA replaces H4 SMA
    pd_filter: bool = False,
    pd_lookback: int = 96,
    tp_mode: str = "rr",            # "rr" | "structure"
    min_struct_rr: float = 1.0,
    spread: float = 0.25,
    slip_atr: float = 0.05,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> tuple[pd.DataFrame, dict]:

    _dur_ns = np.int64(sweep_bar_minutes) * np.int64(60_000_000_000)
    m15, m5 = sweep_df, entry_df

    # ── indicators on FULL series (warmup doesn't eat the test window) ──
    m15 = m15.copy()
    m15["atr14"] = atr(m15, 14)
    m15["swing_hi"] = m15["high"].rolling(swing_lookback).max().shift(1)
    m15["swing_lo"] = m15["low"].rolling(swing_lookback).min().shift(1)
    m15["bull_sweep"] = (m15["high"] > m15["swing_hi"]) & (m15["close"] < m15["swing_hi"])
    m15["bear_sweep"] = (m15["low"] < m15["swing_lo"]) & (m15["close"] > m15["swing_lo"])
    rng_hi = m15["high"].rolling(pd_lookback).max().shift(1)
    rng_lo = m15["low"].rolling(pd_lookback).min().shift(1)
    m15["pd_mid"] = (rng_hi + rng_lo) / 2.0

    m5 = m5.copy()
    m5["atr14"] = atr(m5, 14)
    m5["rec_hi"] = m5["high"].rolling(mss_lookback).max().shift(1)
    m5["rec_lo"] = m5["low"].rolling(mss_lookback).min().shift(1)
    pc = m5["close"].shift(1)
    m5["bull_mss"] = (m5["close"] > m5["rec_hi"]) & (pc <= m5["rec_hi"])
    m5["bear_mss"] = (m5["close"] < m5["rec_lo"]) & (pc >= m5["rec_lo"])
    bull_fvg = (m5["low"] > m5["high"].shift(2)).astype(float)
    bear_fvg = (m5["high"] < m5["low"].shift(2)).astype(float)
    m5["bull_fvg_rec"] = bull_fvg.rolling(fvg_lookback, min_periods=1).max()
    m5["bear_fvg_rec"] = bear_fvg.rolling(fvg_lookback, min_periods=1).max()

    # ── causal regime bias ──
    if regime_daily is not None:
        d1 = regime_daily.copy()
        d1["sma"] = d1["close"].rolling(regime_sma, min_periods=regime_sma).mean()
        bias_vals = np.where(d1["sma"].notna(),
                             np.where(d1["close"] > d1["sma"], 1.0, -1.0), 0.0)
        bias_close_ns = (d1.index + pd.Timedelta("1D")).asi8
    else:
        h4 = resample_h4_ny(m15[["open", "high", "low", "close"]])
        h4["sma"] = h4["close"].rolling(regime_sma, min_periods=regime_sma).mean()
        bias_vals = np.where(h4["sma"].notna(),
                             np.where(h4["close"] > h4["sma"], 1.0, -1.0), 0.0)
        bias_close_ns = (h4.index + pd.Timedelta("4h")).asi8

    # ── date slice ──
    if start_date:
        ts0 = pd.Timestamp(start_date, tz="UTC")
        m15, m5 = m15[m15.index >= ts0], m5[m5.index >= ts0]
    if end_date:
        ts1 = pd.Timestamp(end_date, tz="UTC")
        m15, m5 = m15[m15.index <= ts1], m5[m5.index <= ts1]
    if m15.empty or m5.empty:
        return pd.DataFrame(), {"error": "empty after date filter"}

    m5_ns = m5.index.asi8
    bias = causal_map(bias_vals, bias_close_ns, m5_ns)
    pd_mid = causal_map(m15["pd_mid"].to_numpy(), m15.index.asi8 + _dur_ns, m5_ns)

    # ── arrays ──
    a_hi, a_lo, a_cl = (m5[c].to_numpy() for c in ("high", "low", "close"))
    a_atr = m5["atr14"].to_numpy()
    a_go = go_session(m5.index)
    a_rechi = m5["rec_hi"].to_numpy()
    a_bmss = m5["bull_mss"].to_numpy()
    a_smss = m5["bear_mss"].to_numpy()
    a_bfvg = m5["bull_fvg_rec"].to_numpy()
    a_sfvg = m5["bear_fvg_rec"].to_numpy()
    idx5 = m5.index

    s_close_ns = m15.index.asi8 + _dur_ns
    s_bull = m15["bull_sweep"].to_numpy()
    s_bear = m15["bear_sweep"].to_numpy()
    s_hi = m15["high"].to_numpy()
    s_lo = m15["low"].to_numpy()
    s_shi = m15["swing_hi"].to_numpy()
    s_slo = m15["swing_lo"].to_numpy()

    # ── state ──
    sweep_active = False
    sweep_dir = ""          # "bull" (swept buyside -> short) | "bear" (-> long)
    sweep_extreme = np.nan
    sweep_pool = np.nan
    sweep_left = 0

    in_trade = False
    direction = ""
    entry = stop = target = np.nan
    e_i = 0
    hold = 0

    trades: list[dict] = []
    meta = {"bull_sweeps": 0, "bear_sweeps": 0, "entries": 0,
            "skip_regime": 0, "skip_pd": 0, "skip_fvg": 0, "skip_struct_rr": 0}

    ptr = 0
    n15 = len(s_close_ns)

    for i in range(len(m5_ns)):
        ts = m5_ns[i]

        while ptr < n15 and s_close_ns[ptr] <= ts:
            if sweep_active:
                sweep_left -= 1
                if sweep_left <= 0:
                    sweep_active = False
            if not in_trade:
                if s_bull[ptr] and np.isfinite(s_shi[ptr]):
                    sweep_active, sweep_dir = True, "bull"
                    sweep_extreme = s_hi[ptr]
                    sweep_pool = s_slo[ptr]
                    sweep_left = max_sweep_bars
                    meta["bull_sweeps"] += 1
                elif s_bear[ptr] and np.isfinite(s_slo[ptr]):
                    sweep_active, sweep_dir = True, "bear"
                    sweep_extreme = s_lo[ptr]
                    sweep_pool = s_shi[ptr]
                    sweep_left = max_sweep_bars
                    meta["bear_sweeps"] += 1
            ptr += 1

        if in_trade:
            hold += 1
            exited = False
            risk = abs(entry - stop)
            win_r = abs(target - entry) / risk
            if direction == "bear":
                if a_hi[i] >= stop:
                    _r, _ep, _rsn, exited = -1.0, stop, "stop", True
                elif a_lo[i] <= target:
                    _r, _ep, _rsn, exited = win_r, target, "target", True
                elif hold >= max_hold_bars:
                    _r, _ep, _rsn, exited = (entry - a_cl[i]) / risk, a_cl[i], "max_hold", True
            else:
                if a_lo[i] <= stop:
                    _r, _ep, _rsn, exited = -1.0, stop, "stop", True
                elif a_hi[i] >= target:
                    _r, _ep, _rsn, exited = win_r, target, "target", True
                elif hold >= max_hold_bars:
                    _r, _ep, _rsn, exited = (a_cl[i] - entry) / risk, a_cl[i], "max_hold", True
            if exited:
                trades.append({
                    "entry_time": idx5[e_i], "exit_time": idx5[i],
                    "direction": direction,
                    "entry_price": round(entry, 5), "stop": round(stop, 5),
                    "target": round(target, 5), "exit_price": round(_ep, 5),
                    "realized_r": round(_r, 4), "exit_reason": _rsn,
                    "hold_bars": hold, "atr_at_exit": a_atr[i],
                })
                in_trade = False
                sweep_active = False

        if in_trade or not sweep_active or not a_go[i]:
            continue
        if not (np.isfinite(a_atr[i]) and np.isfinite(a_rechi[i])):
            continue

        want = None
        if sweep_dir == "bull" and a_smss[i]:
            want = "bear"
        elif sweep_dir == "bear" and a_bmss[i]:
            want = "bull"
        if want is None:
            continue

        if regime_filter:
            b = bias[i]
            if b == 0 or (want == "bull" and b < 0) or (want == "bear" and b > 0):
                meta["skip_regime"] += 1
                continue
        if pd_filter and np.isfinite(pd_mid[i]):
            if (want == "bull" and a_cl[i] >= pd_mid[i]) or \
               (want == "bear" and a_cl[i] <= pd_mid[i]):
                meta["skip_pd"] += 1
                continue
        if require_fvg:
            ok = a_sfvg[i] > 0 if want == "bear" else a_bfvg[i] > 0
            if not ok:
                meta["skip_fvg"] += 1
                continue

        cl = a_cl[i]
        min_risk = 2.0 * spread       # stop must be at least 2 spreads away
        if want == "bear":
            sl = sweep_extreme + a_atr[i] * sl_buffer_atr
            if cl >= sl or sl - cl < min_risk:
                continue
            risk = sl - cl
            tp = sweep_pool if tp_mode == "structure" else cl - risk * rr_target
            if tp_mode == "structure":
                if not np.isfinite(tp) or tp >= cl or (cl - tp) / risk < min_struct_rr:
                    meta["skip_struct_rr"] += 1
                    continue
        else:
            sl = sweep_extreme - a_atr[i] * sl_buffer_atr
            if cl <= sl or cl - sl < min_risk:
                continue
            risk = cl - sl
            tp = sweep_pool if tp_mode == "structure" else cl + risk * rr_target
            if tp_mode == "structure":
                if not np.isfinite(tp) or tp <= cl or (tp - cl) / risk < min_struct_rr:
                    meta["skip_struct_rr"] += 1
                    continue

        entry, stop, target = cl, sl, tp
        direction, e_i, hold = want, i, 0
        in_trade = True
        meta["entries"] += 1

    out = apply_costs(pd.DataFrame(trades), spread, slip_atr)
    return out, meta
