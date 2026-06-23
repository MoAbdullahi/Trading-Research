"""
Backtest engine: TimesFM H4 direction + lower-timeframe rejection entries.

Flow per the brief:
  1. DIRECTION (H4): a forecaster (TimesFM 2.5 or baseline) stamps each H4 bar
     with +1 / 0 / -1. Mapped causally onto the LTF.
  2. ENTRY (LTF): when the LTF retests a "visited-and-rejected" level in the
     direction of the H4 bias and shows a fresh rejection wick, we enter.
        - bias +1 (long):  price dips to a SUPPORT level, makes a rejection
                           candle (long lower wick + close back above), enter long.
        - bias -1 (short): price taps a RESISTANCE level, rejection candle
                           (long upper wick + close back below), enter short.
  3. RISK: stop beyond the rejection extreme (+ buffer in ATR), TP at fixed RR.
  4. COSTS: round-trip spread + ATR slippage on stop fills (v2_common.apply_costs).

Causal throughout; reuses the parent project's helpers so costs/stats match the
rest of the suite. Output is a trade log compatible with v2_common.summarize.
"""
from __future__ import annotations

import sys
from pathlib import Path
import numpy as np
import pandas as pd

# import shared helpers (local copy in this project)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from v2_common import atr, causal_map, apply_costs  # noqa: E402

from direction_model import make_forecaster, DirectionResult  # noqa: E402
from levels import build_levels  # noqa: E402


def _slice(df: pd.DataFrame, start, end) -> pd.DataFrame:
    if start is not None:
        df = df[df.index >= pd.Timestamp(start, tz="UTC")]
    if end is not None:
        df = df[df.index <= pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)]
    return df


def run_tfm(h4: pd.DataFrame,
            ltf: pd.DataFrame,
            *,
            forecaster=None,
            forecaster_kind: str = "baseline",
            forecaster_kw: dict | None = None,
            level_mode: str = "swing",
            level_kw: dict | None = None,
            tag_tol_atr: float = 0.15,     # how close LTF must come to a level (in ATR) to "tag" it
            min_rejection_wick: float = 0.4,  # entry candle's rejection-wick fraction
            sl_buffer_atr: float = 0.3,
            rr: float = 3.0,
            max_hold_bars: int = 64,
            atr_n: int = 14,
            spread: float = 0.25,
            slip_atr: float = 0.05,
            start_date=None,
            end_date=None,
            one_trade_per_level: bool = True):
    """
    Returns (trades_df, direction_result).

    trades_df columns match the v2 engines: side, entry_time, entry_price, stop,
    target, exit_time, exit_price, exit_reason, realized_r, atr_at_exit,
    cost_r, net_r, plus level_price / level_time / h4_signal for inspection.
    """
    level_kw = level_kw or {}
    forecaster_kw = forecaster_kw or {}

    # ---- 1. direction on full H4 history (causal), then window ----
    if forecaster is None:
        forecaster = make_forecaster(forecaster_kind, **forecaster_kw)
    direction: DirectionResult = forecaster.predict(h4)

    ltf = _slice(ltf, start_date, end_date).copy()
    if ltf.empty:
        return pd.DataFrame(), direction

    # map H4 signal (known at H4 close) forward onto LTF bars
    h4_close_ns = direction.signal.index.values.astype("int64")
    sig_vals = direction.signal.to_numpy(float)
    ltf_ns = ltf.index.values.astype("int64")
    ltf_sig = causal_map(sig_vals, h4_close_ns, ltf_ns)
    ltf["h4_signal"] = np.nan_to_num(ltf_sig, nan=0.0)

    # ---- 2. levels on the LTF ----
    lv = build_levels(ltf, h4, mode=level_mode, **level_kw)
    ltf = ltf.join(lv)

    a = atr(ltf, atr_n)
    ltf["atr"] = a

    o = ltf["open"].to_numpy(float)
    hi = ltf["high"].to_numpy(float)
    lo = ltf["low"].to_numpy(float)
    cl = ltf["close"].to_numpy(float)
    av = ltf["atr"].to_numpy(float)
    sig = ltf["h4_signal"].to_numpy(float)
    sup = ltf["sup_price"].to_numpy(float)
    res = ltf["res_price"].to_numpy(float)
    sup_t = ltf["sup_time"].to_numpy(np.int64)
    res_t = ltf["res_time"].to_numpy(np.int64)
    idx = ltf.index
    n = len(ltf)

    rng = (hi - lo)
    rng_safe = np.where(rng == 0, np.nan, rng)
    upper_wick = (hi - np.maximum(o, cl)) / rng_safe
    lower_wick = (np.minimum(o, cl) - lo) / rng_safe
    upper_wick = np.nan_to_num(upper_wick)
    lower_wick = np.nan_to_num(lower_wick)

    trades = []
    used_levels = set()        # (side, level_time) already traded
    i = 1
    while i < n:
        if not np.isfinite(av[i]) or av[i] <= 0:
            i += 1
            continue
        bias = sig[i]
        tol = tag_tol_atr * av[i]

        entered = False
        # ---- LONG setup: support tag + bullish rejection ----
        if bias > 0 and np.isfinite(sup[i]):
            tagged = lo[i] <= sup[i] + tol            # came down to the level
            rejected = (lower_wick[i] >= min_rejection_wick) and (cl[i] > sup[i])
            lvl_key = (1, int(sup_t[i]))
            if tagged and rejected and not (one_trade_per_level and lvl_key in used_levels):
                entry = cl[i]
                stop = min(lo[i], sup[i]) - sl_buffer_atr * av[i]
                risk = entry - stop
                if risk > 2 * spread:
                    target = entry + rr * risk
                    tr = _simulate(i, +1, entry, stop, target, idx, hi, lo, av,
                                   max_hold_bars)
                    tr.update(level_price=sup[i], level_time=sup_t[i],
                              h4_signal=1)
                    trades.append(tr)
                    used_levels.add(lvl_key)
                    entered = True
                    i = tr["_exit_i"] + 1
        # ---- SHORT setup: resistance tag + bearish rejection ----
        if (not entered) and bias < 0 and np.isfinite(res[i]):
            tagged = hi[i] >= res[i] - tol
            rejected = (upper_wick[i] >= min_rejection_wick) and (cl[i] < res[i])
            lvl_key = (-1, int(res_t[i]))
            if tagged and rejected and not (one_trade_per_level and lvl_key in used_levels):
                entry = cl[i]
                stop = max(hi[i], res[i]) + sl_buffer_atr * av[i]
                risk = stop - entry
                if risk > 2 * spread:
                    target = entry - rr * risk
                    tr = _simulate(i, -1, entry, stop, target, idx, hi, lo, av,
                                   max_hold_bars)
                    tr.update(level_price=res[i], level_time=res_t[i],
                              h4_signal=-1)
                    trades.append(tr)
                    used_levels.add(lvl_key)
                    entered = True
                    i = tr["_exit_i"] + 1
        if not entered:
            i += 1

    cols = ["side", "entry_time", "entry_price", "stop", "target", "exit_time",
            "exit_price", "exit_reason", "realized_r", "atr_at_exit",
            "level_price", "level_time", "h4_signal"]
    df = pd.DataFrame(trades)
    if df.empty:
        return df, direction
    df = df.drop(columns=[c for c in df.columns if c.startswith("_")])
    df = df[cols]
    df = apply_costs(df, spread=spread, slip_atr=slip_atr)
    return df, direction


def _simulate(i, side, entry, stop, target, idx, hi, lo, av, max_hold):
    """Walk forward bar-by-bar from i+1 until stop/target/timeout. Stop priority
    on the same bar (conservative)."""
    n = len(hi)
    exit_i = min(i + max_hold, n - 1)
    exit_price = None
    reason = "timeout"
    for j in range(i + 1, min(i + max_hold + 1, n)):
        if side > 0:
            if lo[j] <= stop:
                exit_i, exit_price, reason = j, stop, "stop"; break
            if hi[j] >= target:
                exit_i, exit_price, reason = j, target, "target"; break
        else:
            if hi[j] >= stop:
                exit_i, exit_price, reason = j, stop, "stop"; break
            if lo[j] <= target:
                exit_i, exit_price, reason = j, target, "target"; break
    if exit_price is None:
        exit_price = (hi[exit_i] + lo[exit_i]) / 2.0  # mid at timeout
    risk = abs(entry - stop)
    realized = ((exit_price - entry) if side > 0 else (entry - exit_price)) / risk
    return {
        "side": "long" if side > 0 else "short",
        "entry_time": idx[i], "entry_price": entry, "stop": stop,
        "target": target, "exit_time": idx[exit_i], "exit_price": exit_price,
        "exit_reason": reason, "realized_r": realized,
        "atr_at_exit": av[exit_i], "_exit_i": exit_i,
    }
