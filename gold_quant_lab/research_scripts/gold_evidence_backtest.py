"""Evidence-based gold prototypes on XAUUSD, same fill conventions as the CRT test.

Two families the literature actually supports:
  A) Asian-range -> London breakout (session structure: London/NY overlap = 60-70%
     of gold's daily range).
  B) Donchian trend-following with a chandelier ATR trailing stop (time-series
     momentum / Turtle-style breakout — the most replicated edge in commodities).

Conventions (identical to backtest/fills.py so numbers are comparable to CRT):
  * entry at the NEXT bar's open, 2 bps slippage against you
  * stop fills with slippage against; targets are limit fills (no slippage)
  * intrabar: if stop and target sit in the same bar, stop assumed first
  * R = realized move / initial risk-per-unit; qty = 1 (sizing-independent)

Pre-committed kill criterion (set before looking at results):
  PASS requires ALL of: trades >= 150, avg_R >= +0.20R, profit_factor > 1.0
"""
from __future__ import annotations
import json
import numpy as np
import pandas as pd

SLIP = 2.0 / 10_000.0
KILL_MIN_TRADES = 150
KILL_MIN_EV = 0.20

M15 = "/sessions/awesome-loving-euler/mnt/data/m15/XAUUSD_M15.parquet"


def load(path):
    df = pd.read_parquet(path)
    if not isinstance(df.index, pd.DatetimeIndex):
        df = df.set_index("timestamp")
    df.index = df.index.tz_localize("UTC") if df.index.tz is None else df.index.tz_convert("UTC")
    return df.sort_index()[["open", "high", "low", "close"]]


def atr_series(df, period=14):
    pc = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False).mean()


# --------------------------------------------------------------------------- #
def summarize(rs):
    n = len(rs)
    if n == 0:
        return {"trades": 0, "verdict": "NO TRADES"}
    rs = np.array(rs, float)
    wins = rs[rs > 0]; losses = rs[rs <= 0]
    gw = wins.sum(); gl = -losses.sum()
    cum = np.cumsum(rs); mdd = float((cum - np.maximum.accumulate(cum)).min())
    pf = float(gw / gl) if gl > 0 else float("inf")
    avg = float(rs.mean())
    verdict = "PASS" if (n >= KILL_MIN_TRADES and avg >= KILL_MIN_EV and pf > 1.0) else "FAIL"
    return {"trades": n, "win_rate": round(float((rs > 0).mean()), 3),
            "avg_R": round(avg, 3), "total_R": round(float(rs.sum()), 1),
            "avg_win_R": round(float(wins.mean()), 3) if len(wins) else 0.0,
            "avg_loss_R": round(float(losses.mean()), 3) if len(losses) else 0.0,
            "profit_factor": round(pf, 2), "max_dd_R": round(mdd, 1), "verdict": verdict}


def sim_fixed(side, entry, stop, target, fut_h, fut_l, fut_c):
    """Walk forward bars (arrays) until stop/target/forced close. Returns R."""
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    long = side == 1
    for k in range(len(fut_h)):
        hi, lo = fut_h[k], fut_l[k]
        hit_stop = lo <= stop if long else hi >= stop
        hit_tgt = hi >= target if long else lo <= target
        if hit_stop and hit_tgt:
            px = stop * (1 - SLIP) if long else stop * (1 + SLIP)
            return ((px - entry) if long else (entry - px)) / risk
        if hit_stop:
            px = stop * (1 - SLIP) if long else stop * (1 + SLIP)
            return ((px - entry) if long else (entry - px)) / risk
        if hit_tgt:
            return ((target - entry) if long else (entry - target)) / risk
    # forced close at last bar's close
    px = fut_c[-1]
    return ((px - entry) if long else (entry - px)) / risk


# --------------------------------------------------------------------------- #
# A) Asian-range -> London breakout
# --------------------------------------------------------------------------- #
def asian_breakout(df, target_R=2.0, stop_mode="opposite", asia_end=7, win_end=16,
                   day_close=21, min_range_atr=0.5):
    """One trade/day. Asian range = 00:00..asia_end UTC. Breakout (close beyond
    range) inside [asia_end, win_end) UTC -> enter next bar open. stop_mode:
    'opposite' = far side of range; 'mid' = range midpoint. Target = target_R x risk.
    Skip days whose Asian range < min_range_atr x daily ATR (dead days)."""
    h = df["high"].to_numpy(); l = df["low"].to_numpy(); c = df["close"].to_numpy(); o = df["open"].to_numpy()
    hour = df.index.hour.to_numpy(); date = df.index.normalize()
    datr = atr_series(df, 96).to_numpy()  # ~1-day ATR on M15
    rs = []
    for d, grp in df.groupby(date):
        gi = df.index.get_indexer(grp.index)
        ghour = hour[gi]
        asia = gi[ghour < asia_end]
        if len(asia) < 4:
            continue
        a_hi = h[asia].max(); a_lo = l[asia].min(); a_mid = 0.5 * (a_hi + a_lo)
        rng = a_hi - a_lo
        ref_atr = datr[asia[-1]]
        if rng <= 0 or (ref_atr > 0 and rng < min_range_atr * ref_atr):
            continue
        win = gi[(ghour >= asia_end) & (ghour < win_end)]
        sig = None
        for j in win:
            if c[j] > a_hi:
                sig = (1, j); break
            if c[j] < a_lo:
                sig = (-1, j); break
        if sig is None:
            continue
        side, j = sig
        if j + 1 >= len(df):
            continue
        entry = o[j + 1] * (1 + SLIP) if side == 1 else o[j + 1] * (1 - SLIP)
        if stop_mode == "opposite":
            stop = a_lo if side == 1 else a_hi
        else:
            stop = a_mid
        risk = abs(entry - stop)
        if risk <= 0:
            continue
        target = entry + target_R * risk if side == 1 else entry - target_R * risk
        # forced close at end-of-day bars (hour < day_close)
        end = gi[ghour < day_close]
        last_i = end[-1] if len(end) else gi[-1]
        fut = slice(j + 1, last_i + 1)
        r = sim_fixed(side, entry, stop, target, h[fut], l[fut], c[fut])
        if r is not None:
            rs.append(r)
    return rs


# --------------------------------------------------------------------------- #
# B) Donchian trend-following + chandelier ATR trailing stop
# --------------------------------------------------------------------------- #
def donchian_trend(df, lookback=96, atr_mult=3.0, atr_p=22):
    h = df["high"].to_numpy(); l = df["low"].to_numpy(); c = df["close"].to_numpy(); o = df["open"].to_numpy()
    n = len(df)
    upper = pd.Series(h).rolling(lookback).max().shift(1).to_numpy()  # prior N-bar high
    lower = pd.Series(l).rolling(lookback).min().shift(1).to_numpy()
    a = atr_series(df, atr_p).to_numpy()
    rs = []
    i = lookback + 1
    pos = 0; entry = stop = risk = 0.0
    while i < n - 1:
        if pos == 0:
            long_sig = c[i] > upper[i]
            short_sig = c[i] < lower[i]
            if long_sig or short_sig:
                side = 1 if long_sig else -1
                entry = o[i + 1] * (1 + SLIP) if side == 1 else o[i + 1] * (1 - SLIP)
                stop = entry - atr_mult * a[i] if side == 1 else entry + atr_mult * a[i]
                risk = abs(entry - stop)
                pos = side; i += 1
                continue
        else:
            # update chandelier trail from the entry bar onward
            if pos == 1:
                stop = max(stop, h[i] - atr_mult * a[i])
                if l[i] <= stop:
                    px = stop * (1 - SLIP)
                    rs.append((px - entry) / risk); pos = 0
            else:
                stop = min(stop, l[i] + atr_mult * a[i])
                if h[i] >= stop:
                    px = stop * (1 + SLIP)
                    rs.append((entry - px) / risk); pos = 0
        i += 1
    if pos != 0:
        px = c[-1]
        rs.append(((px - entry) if pos == 1 else (entry - px)) / risk)
    return rs


def main():
    df = load(M15)
    print(f"XAUUSD M15: {len(df):,} bars {df.index[0].date()} -> {df.index[-1].date()}\n")
    runs = {}
    runs["Asian->London 2R (opp stop)"] = asian_breakout(df, 2.0, "opposite")
    runs["Asian->London 1R (opp stop)"] = asian_breakout(df, 1.0, "opposite")
    runs["Asian->London 1.5R (mid stop)"] = asian_breakout(df, 1.5, "mid")
    runs["Donchian-96 trend (3xATR trail)"] = donchian_trend(df, 96, 3.0)
    runs["Donchian-192 trend (3xATR trail)"] = donchian_trend(df, 192, 3.0)
    out = {name: summarize(rs) for name, rs in runs.items()}
    print(json.dumps(out, indent=2))
    open("/sessions/awesome-loving-euler/mnt/outputs/gold_evidence_results.json", "w").write(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
