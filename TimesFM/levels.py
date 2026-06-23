"""
"Visited-and-rejected" level detection on the lower timeframe.

A level is a price the market has already traded TO and then rejected (left a
wick / reversed away from). The thesis: once the H4 direction is known, we want
to enter on a pullback into such a level *in the direction of the trend* and
only when the lower-timeframe shows the level rejecting again.

Two selectable modes (chosen with `mode=`):

  mode="swing"
      Levels come from LTF swing pivots: a fractal high/low with `left`/`right`
      bars lower/higher around it, that ALSO showed wick rejection (a real
      upper/lower shadow). Support levels = rejected swing lows; resistance =
      rejected swing highs.

  mode="h4candle"
      Levels come from the extremes of recently CLOSED H4 candles whose own wick
      shows rejection (long upper wick -> resistance at its high; long lower
      wick -> support at its low). Mapped down to the LTF causally.

Both modes return, for every LTF bar, the nearest *active* support below and
resistance above, so the engine can test "did price tag a level and reject it".

Everything is causal: a level created by a bar that closes at time t is only
visible at bars at/after t (+ the pivot's right-confirmation lag for swings).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Swing-pivot levels (mode="swing")
# ---------------------------------------------------------------------------
def _wick_fracs(df: pd.DataFrame):
    rng = (df["high"] - df["low"]).replace(0, np.nan)
    upper = (df["high"] - df[["open", "close"]].max(axis=1)) / rng
    lower = (df[["open", "close"]].min(axis=1) - df["low"]) / rng
    return upper.fillna(0.0), lower.fillna(0.0)


def swing_levels(ltf: pd.DataFrame, left: int = 3, right: int = 3,
                 min_wick: float = 0.33) -> pd.DataFrame:
    """
    Return a DataFrame indexed like `ltf` with columns:
        sup_price, sup_time  - nearest rejected swing LOW at/below current price
        res_price, res_time  - nearest rejected swing HIGH at/above current price

    A swing high at bar i is confirmed (becomes visible) at bar i+right.
    `min_wick` filters for genuine rejection: the pivot bar's relevant shadow
    must be >= this fraction of its range.
    """
    h = ltf["high"].to_numpy(float)
    l = ltf["low"].to_numpy(float)
    n = len(ltf)
    upper, lower = _wick_fracs(ltf)
    upper = upper.to_numpy(float)
    lower = lower.to_numpy(float)

    # Identify fractal pivots.
    piv_hi = np.zeros(n, dtype=bool)
    piv_lo = np.zeros(n, dtype=bool)
    for i in range(left, n - right):
        seg_h = h[i - left:i + right + 1]
        seg_l = l[i - left:i + right + 1]
        if h[i] == seg_h.max() and (seg_h.argmax() == left) and upper[i] >= min_wick:
            piv_hi[i] = True
        if l[i] == seg_l.min() and (seg_l.argmin() == left) and lower[i] >= min_wick:
            piv_lo[i] = True

    # Confirmation time = pivot bar + right (when it first becomes known).
    hi_prices, hi_conf = [], []   # list of (price, confirm_index)
    lo_prices, lo_conf = [], []
    for i in range(n):
        if piv_hi[i]:
            hi_prices.append(h[i]); hi_conf.append(i + right)
        if piv_lo[i]:
            lo_prices.append(l[i]); lo_conf.append(i + right)
    hi_prices = np.array(hi_prices); hi_conf = np.array(hi_conf)
    lo_prices = np.array(lo_prices); lo_conf = np.array(lo_conf)

    idx = ltf.index
    close = ltf["close"].to_numpy(float)
    sup_p = np.full(n, np.nan); res_p = np.full(n, np.nan)
    sup_t = np.full(n, -1, dtype=np.int64); res_t = np.full(n, -1, dtype=np.int64)

    for i in range(n):
        c = close[i]
        # nearest confirmed swing low at/below current close
        if len(lo_prices):
            m = (lo_conf <= i) & (lo_prices <= c)
            if m.any():
                cand = np.where(m)[0]
                k = cand[np.argmax(lo_prices[cand])]   # highest support below
                sup_p[i] = lo_prices[k]; sup_t[i] = idx[lo_conf[k]].value if lo_conf[k] < n else -1
        # nearest confirmed swing high at/above current close
        if len(hi_prices):
            m = (hi_conf <= i) & (hi_prices >= c)
            if m.any():
                cand = np.where(m)[0]
                k = cand[np.argmin(hi_prices[cand])]   # lowest resistance above
                res_p[i] = hi_prices[k]; res_t[i] = idx[hi_conf[k]].value if hi_conf[k] < n else -1

    return pd.DataFrame({"sup_price": sup_p, "res_price": res_p,
                         "sup_time": sup_t, "res_time": res_t}, index=idx)


# ---------------------------------------------------------------------------
# Prior-H4-candle levels (mode="h4candle")
# ---------------------------------------------------------------------------
def h4_candle_levels(ltf: pd.DataFrame, h4: pd.DataFrame,
                     min_wick: float = 0.33, lookback: int = 12) -> pd.DataFrame:
    """
    Levels = extremes of recently CLOSED H4 candles that show wick rejection.
    A long upper wick -> resistance at that candle's high.
    A long lower wick -> support  at that candle's low.

    For each LTF bar we expose the nearest such support below and resistance
    above, considering only the last `lookback` qualifying H4 candles that have
    already closed (causal via searchsorted on H4 close times).
    """
    upper, lower = _wick_fracs(h4)
    h4c = h4.copy()
    h4c["is_res"] = upper.to_numpy(float) >= min_wick
    h4c["is_sup"] = lower.to_numpy(float) >= min_wick
    h4_close_ns = h4.index.values.astype("int64")

    res_levels = h4["high"].to_numpy(float)
    sup_levels = h4["low"].to_numpy(float)
    is_res = h4c["is_res"].to_numpy(bool)
    is_sup = h4c["is_sup"].to_numpy(bool)

    idx = ltf.index
    tns = idx.values.astype("int64")
    close = ltf["close"].to_numpy(float)
    n = len(ltf)
    sup_p = np.full(n, np.nan); res_p = np.full(n, np.nan)
    sup_t = np.full(n, -1, dtype=np.int64); res_t = np.full(n, -1, dtype=np.int64)

    # position of the most recent CLOSED H4 bar for each LTF bar
    pos = np.searchsorted(h4_close_ns, tns, side="right") - 1
    for i in range(n):
        p = pos[i]
        if p < 0:
            continue
        lo_idx = max(0, p - lookback + 1)
        c = close[i]
        # resistance candidates above
        seg = slice(lo_idx, p + 1)
        rsel = is_res[seg] & (res_levels[seg] >= c)
        if rsel.any():
            cand = np.where(rsel)[0] + lo_idx
            k = cand[np.argmin(res_levels[cand])]
            res_p[i] = res_levels[k]; res_t[i] = h4_close_ns[k]
        ssel = is_sup[seg] & (sup_levels[seg] <= c)
        if ssel.any():
            cand = np.where(ssel)[0] + lo_idx
            k = cand[np.argmax(sup_levels[cand])]
            sup_p[i] = sup_levels[k]; sup_t[i] = h4_close_ns[k]

    return pd.DataFrame({"sup_price": sup_p, "res_price": res_p,
                         "sup_time": sup_t, "res_time": res_t}, index=idx)


def build_levels(ltf: pd.DataFrame, h4: pd.DataFrame, mode: str = "swing",
                 **kw) -> pd.DataFrame:
    mode = mode.lower()
    if mode == "swing":
        keys = {k: kw[k] for k in ("left", "right", "min_wick") if k in kw}
        return swing_levels(ltf, **keys)
    if mode in ("h4candle", "h4", "candle"):
        keys = {k: kw[k] for k in ("min_wick", "lookback") if k in kw}
        return h4_candle_levels(ltf, h4, **keys)
    raise ValueError(f"unknown level mode: {mode!r}")
