"""Shared helpers for v2 engines — all causal, all cost-aware."""
from __future__ import annotations
import numpy as np
import pandas as pd

NY = "America/New_York"

# Realistic default costs (round-trip spread in price units, slippage as ATR mult on stop fills)
COSTS = {
    "XAUUSD": {"spread": 0.25, "slip_atr": 0.05},
    "GBPUSD": {"spread": 0.00008, "slip_atr": 0.05},
}


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    pc = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"],
                    (df["high"] - pc).abs(),
                    (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()


def go_session(idx: pd.DatetimeIndex) -> np.ndarray:
    """London KZ through NY AM KZ: 02:00-10:00 NY."""
    h = idx.tz_convert(NY).hour
    return ((h >= 2) & (h < 10)).to_numpy() if hasattr((h >= 2), "to_numpy") else np.asarray((h >= 2) & (h < 10))


def crt_session(idx: pd.DatetimeIndex, mode: str = "broad") -> np.ndarray:
    h = idx.tz_convert(NY).hour
    if mode == "tight":
        m = (h >= 4) & (h < 11)
    elif mode == "kz":
        m = (h >= 5) & (h < 10)
    else:
        m = (h >= 2) & (h < 13)
    return np.asarray(m)


def resample_h4_ny(m15: pd.DataFrame) -> pd.DataFrame:
    """H4 candles anchored to NY 17:00 session start (bins at 01/05/09/13/17/21 NY),
    matching broker / TradingView gold charts — fixes the UTC-anchor mismatch."""
    loc = m15.tz_convert(NY)
    h4 = loc.resample("4h", offset="1h").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    h4.index = h4.index.tz_convert("UTC").as_unit("ns")
    return h4


def causal_map(values: np.ndarray, close_times_ns: np.ndarray, target_ns: np.ndarray) -> np.ndarray:
    """For each target timestamp, return the most recent value whose bar CLOSED at or before it."""
    pos = np.searchsorted(close_times_ns, target_ns, side="right") - 1
    out = np.full(len(target_ns), np.nan)
    ok = pos >= 0
    out[ok] = values[pos[ok]]
    return out


def apply_costs(trades: pd.DataFrame, spread: float, slip_atr: float) -> pd.DataFrame:
    """Charge round-trip spread on every trade + ATR-based slippage on stop fills."""
    if trades.empty:
        return trades
    t = trades.copy()
    risk = (t["entry_price"] - t["stop"]).abs()
    slip = np.where(t["exit_reason"] == "stop", slip_atr * t["atr_at_exit"], 0.0)
    t["cost_r"] = (spread + slip) / risk
    t["net_r"] = t["realized_r"] - t["cost_r"]
    return t


def summarize(trades: pd.DataFrame, col: str = "net_r") -> dict:
    if trades.empty:
        return {"n": 0, "win_rate": 0.0, "avg_r": 0.0, "total_r": 0.0,
                "pf": 0.0, "max_dd": 0.0, "max_loss_streak": 0}
    r = trades[col]
    wins, losses = r[r > 0], r[r <= 0]
    gl = abs(losses.sum())
    pf = (wins.sum() / gl) if gl > 0 else float("inf")
    cum = r.cumsum()
    dd = (cum.cummax() - cum).max()
    streak = mx = 0
    for x in r:
        streak = streak + 1 if x <= 0 else 0
        mx = max(mx, streak)
    return {"n": len(r), "win_rate": round(100 * len(wins) / len(r), 1),
            "avg_r": round(r.mean(), 3), "total_r": round(r.sum(), 2),
            "pf": round(min(pf, 999), 2), "max_dd": round(dd, 2),
            "max_loss_streak": mx}
