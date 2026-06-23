"""Trend-following / momentum backtest runner (standalone).

Built after the CRT sweep-reversal failed on every timeframe: the evidence
(Moskowitz 2012; Hurst/Ooi/Pedersen 2017) says momentum/trend has a real edge,
but on DAILY+ horizons, not intraday.  This runner confirmed that on XAUUSD:
daily Donchian / EMA-cross are profitable (PF ~2-3.7) while intraday loses.

Only needs pandas + numpy.  No dependency on the rest of the trading system.

Fill conventions (match backtest/fills.py so results compare to the CRT runs):
  * entry at the NEXT bar's open, 2 bps slippage against you
  * stop fills with slippage against; targets are limit fills (no slippage)
  * intrabar: stop assumed before target if both sit in one bar
  * R = realised move / initial risk-per-unit (sizing-independent)

Strategies:
  donchian      N-bar breakout, chandelier (k x ATR) trailing stop
  ema_cross     fast/slow EMA cross, k x ATR trailing stop, exit on opposite cross
  asian_breakout  Asian-range -> London breakout, fixed R target (intraday only)

Usage
-----
Single test:
  python run_gold_trend.py --data data/daily/XAUUSD_D1.parquet \
      --strategy donchian --lookback 55 --atr-mult 3

  python run_gold_trend.py --data data/daily/XAUUSD_D1.parquet \
      --strategy ema_cross --fast 50 --slow 200

Full suite (point at whichever files you have; any subset works):
  python run_gold_trend.py --suite \
      --d1  data/daily/XAUUSD_D1.parquet \
      --h4  data/h4/XAUUSD_H4.parquet \
      --h1  data/h4/XAUUSD_H1_raw.parquet \
      --m15 data/m15/XAUUSD_M15.parquet

Optional: --start 2021-06-01 --end 2026-06-05  (UTC date filters)
          --out results.json
"""
from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd

SLIP = 2.0 / 10_000.0          # 2 bps, applied against you on entries and stops
KILL_MIN_EV = 0.20             # pre-committed: avg_R must clear this with PF > 1


# --------------------------------------------------------------------------- #
# Data + indicators
# --------------------------------------------------------------------------- #
def load(path: str, start=None, end=None) -> pd.DataFrame:
    df = pd.read_parquet(path)
    if not isinstance(df.index, pd.DatetimeIndex):
        df = df.set_index("timestamp")
    df.index = df.index.tz_localize("UTC") if df.index.tz is None else df.index.tz_convert("UTC")
    df = df.sort_index()
    need = {"open", "high", "low", "close"}
    missing = need - set(df.columns)
    if missing:
        raise ValueError(f"{path}: missing columns {missing}")
    if start:
        df = df[df.index >= pd.Timestamp(start, tz="UTC")]
    if end:
        df = df[df.index <= pd.Timestamp(end, tz="UTC")]
    return df[["open", "high", "low", "close"]]


def atr_arr(df: pd.DataFrame, period: int = 14) -> np.ndarray:
    pc = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"],
                    (df["high"] - pc).abs(),
                    (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False).mean().to_numpy()


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #
def summarize(rs: list[float], label: str, buy_hold_pct: float | None = None) -> dict:
    n = len(rs)
    if n == 0:
        return {"strategy": label, "trades": 0, "verdict": "NO TRADES"}
    a = np.asarray(rs, float)
    wins, losses = a[a > 0], a[a <= 0]
    gw, gl = wins.sum(), -losses.sum()
    cum = np.cumsum(a)
    mdd = float((cum - np.maximum.accumulate(cum)).min())
    pf = float(gw / gl) if gl > 0 else float("inf")
    avg = float(a.mean())
    out = {
        "strategy": label, "trades": n,
        "win_rate": round(float((a > 0).mean()), 3),
        "avg_R": round(avg, 3), "total_R": round(float(a.sum()), 1),
        "avg_win_R": round(float(wins.mean()), 3) if len(wins) else 0.0,
        "avg_loss_R": round(float(losses.mean()), 3) if len(losses) else 0.0,
        "profit_factor": round(pf, 2), "max_dd_R": round(mdd, 1),
        "verdict": "PASS" if (avg >= KILL_MIN_EV and pf > 1.0) else "FAIL",
    }
    if buy_hold_pct is not None:
        out["buy_hold_%"] = buy_hold_pct
    return out


# --------------------------------------------------------------------------- #
# Strategies
# --------------------------------------------------------------------------- #
def donchian(df: pd.DataFrame, lookback=55, atr_mult=3.0, atr_p=14) -> list[float]:
    h = df["high"].to_numpy(); l = df["low"].to_numpy()
    c = df["close"].to_numpy(); o = df["open"].to_numpy()
    up = pd.Series(h).rolling(lookback).max().shift(1).to_numpy()
    lo = pd.Series(l).rolling(lookback).min().shift(1).to_numpy()
    a = atr_arr(df, atr_p)
    n = len(df); rs = []; i = lookback + 1; pos = 0; entry = stop = risk = 0.0
    while i < n - 1:
        if pos == 0:
            long_sig, short_sig = c[i] > up[i], c[i] < lo[i]
            if long_sig or short_sig:
                side = 1 if long_sig else -1
                entry = o[i + 1] * (1 + SLIP) if side == 1 else o[i + 1] * (1 - SLIP)
                stop = entry - atr_mult * a[i] if side == 1 else entry + atr_mult * a[i]
                risk = abs(entry - stop); pos = side; i += 1; continue
        else:
            if pos == 1:
                stop = max(stop, h[i] - atr_mult * a[i])
                if l[i] <= stop:
                    rs.append((stop * (1 - SLIP) - entry) / risk); pos = 0
            else:
                stop = min(stop, l[i] + atr_mult * a[i])
                if h[i] >= stop:
                    rs.append((entry - stop * (1 + SLIP)) / risk); pos = 0
        i += 1
    if pos != 0:
        rs.append(((c[-1] - entry) if pos == 1 else (entry - c[-1])) / risk)
    return rs


def ema_cross(df: pd.DataFrame, fast=50, slow=200, atr_mult=3.0, atr_p=14) -> list[float]:
    c = df["close"]
    ef = c.ewm(span=fast, adjust=False).mean().to_numpy()
    es = c.ewm(span=slow, adjust=False).mean().to_numpy()
    cc = c.to_numpy(); o = df["open"].to_numpy(); h = df["high"].to_numpy(); l = df["low"].to_numpy()
    a = atr_arr(df, atr_p)
    n = len(df); rs = []; i = slow + 1; pos = 0; entry = stop = risk = 0.0
    while i < n - 1:
        up, dn = ef[i] > es[i], ef[i] < es[i]
        if pos == 0:
            if up or dn:
                side = 1 if up else -1
                entry = o[i + 1] * (1 + SLIP) if side == 1 else o[i + 1] * (1 - SLIP)
                stop = entry - atr_mult * a[i] if side == 1 else entry + atr_mult * a[i]
                risk = abs(entry - stop); pos = side; i += 1; continue
        elif pos == 1:
            stop = max(stop, h[i] - atr_mult * a[i])
            if l[i] <= stop:
                rs.append((stop * (1 - SLIP) - entry) / risk); pos = 0
            elif dn:
                rs.append((o[i] * (1 - SLIP) - entry) / risk); pos = 0
        else:
            stop = min(stop, l[i] + atr_mult * a[i])
            if h[i] >= stop:
                rs.append((entry - stop * (1 + SLIP)) / risk); pos = 0
            elif up:
                rs.append((entry - o[i] * (1 + SLIP)) / risk); pos = 0
        i += 1
    if pos != 0:
        rs.append(((cc[-1] - entry) if pos == 1 else (entry - cc[-1])) / risk)
    return rs


def asian_breakout(df, target_R=2.0, stop_mode="opposite",
                   asia_end=7, win_end=16, day_close=21, min_range_atr=0.5) -> list[float]:
    h = df["high"].to_numpy(); l = df["low"].to_numpy()
    c = df["close"].to_numpy(); o = df["open"].to_numpy()
    hour = df.index.hour.to_numpy(); date = df.index.normalize()
    datr = atr_arr(df, 96)
    rs = []
    for _, grp in df.groupby(date):
        gi = df.index.get_indexer(grp.index); gh = hour[gi]
        asia = gi[gh < asia_end]
        if len(asia) < 4:
            continue
        a_hi, a_lo = h[asia].max(), l[asia].min(); a_mid = 0.5 * (a_hi + a_lo)
        rng = a_hi - a_lo; ref = datr[asia[-1]]
        if rng <= 0 or (ref > 0 and rng < min_range_atr * ref):
            continue
        win = gi[(gh >= asia_end) & (gh < win_end)]
        sig = None
        for j in win:
            if c[j] > a_hi:
                sig = (1, j); break
            if c[j] < a_lo:
                sig = (-1, j); break
        if sig is None or sig[1] + 1 >= len(df):
            continue
        side, j = sig
        entry = o[j + 1] * (1 + SLIP) if side == 1 else o[j + 1] * (1 - SLIP)
        stop = (a_lo if side == 1 else a_hi) if stop_mode == "opposite" else a_mid
        risk = abs(entry - stop)
        if risk <= 0:
            continue
        target = entry + target_R * risk if side == 1 else entry - target_R * risk
        end = gi[gh < day_close]; last_i = end[-1] if len(end) else gi[-1]
        long = side == 1; r = None
        for k in range(j + 1, last_i + 1):
            hit_stop = l[k] <= stop if long else h[k] >= stop
            hit_tgt = h[k] >= target if long else l[k] <= target
            if hit_stop:
                px = stop * (1 - SLIP) if long else stop * (1 + SLIP)
                r = ((px - entry) if long else (entry - px)) / risk; break
            if hit_tgt:
                r = ((target - entry) if long else (entry - target)) / risk; break
        if r is None:
            px = c[last_i]; r = ((px - entry) if long else (entry - px)) / risk
        rs.append(r)
    return rs


def bh(df):
    return round(100 * (df["close"].iloc[-1] / df["close"].iloc[0] - 1), 1)


def print_table(rows):
    cols = ["strategy", "trades", "win_rate", "avg_R", "profit_factor", "max_dd_R", "verdict"]
    w = {c: max(len(c), *(len(str(r.get(c, ""))) for r in rows)) for c in cols}
    line = "  ".join(c.ljust(w[c]) for c in cols)
    print(line); print("-" * len(line))
    for r in rows:
        print("  ".join(str(r.get(c, "")).ljust(w[c]) for c in cols))


# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description="Gold trend-following backtest")
    ap.add_argument("--data", help="single parquet file")
    ap.add_argument("--strategy", choices=["donchian", "ema_cross", "asian_breakout"], default="donchian")
    ap.add_argument("--lookback", type=int, default=55)
    ap.add_argument("--atr-mult", type=float, default=3.0)
    ap.add_argument("--atr-period", type=int, default=14)
    ap.add_argument("--fast", type=int, default=50)
    ap.add_argument("--slow", type=int, default=200)
    ap.add_argument("--target-r", type=float, default=2.0)
    ap.add_argument("--start", default=None)
    ap.add_argument("--end", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--suite", action="store_true", help="run the standard multi-timeframe suite")
    ap.add_argument("--d1"); ap.add_argument("--h4"); ap.add_argument("--h1"); ap.add_argument("--m15")
    args = ap.parse_args()

    rows = []

    if args.suite:
        if args.m15:
            df = load(args.m15, args.start, args.end); b = bh(df)
            rows.append(summarize(donchian(df, 96, args.atr_mult, args.atr_period), "M15 Donchian-96", b))
            rows.append(summarize(asian_breakout(df, 2.0), "M15 Asian->London 2R", b))
        if args.h1:
            df = load(args.h1, args.start, args.end); b = bh(df)
            rows.append(summarize(donchian(df, 20, args.atr_mult, args.atr_period), "H1 Donchian-20", b))
            rows.append(summarize(donchian(df, 60, args.atr_mult, args.atr_period), "H1 Donchian-60", b))
        if args.h4:
            df = load(args.h4, args.start, args.end); b = bh(df)
            rows.append(summarize(donchian(df, 20, args.atr_mult, args.atr_period), "H4 Donchian-20", b))
            rows.append(summarize(donchian(df, 60, args.atr_mult, args.atr_period), "H4 Donchian-60", b))
        if args.d1:
            df = load(args.d1, args.start, args.end); b = bh(df)
            rows.append(summarize(donchian(df, 20, args.atr_mult, args.atr_period), "D1 Donchian-20", b))
            rows.append(summarize(donchian(df, 55, args.atr_mult, args.atr_period), "D1 Donchian-55", b))
            rows.append(summarize(ema_cross(df, args.fast, args.slow, args.atr_mult, args.atr_period), "D1 EMA cross", b))
        if not rows:
            ap.error("--suite needs at least one of --d1/--h4/--h1/--m15")
    else:
        if not args.data:
            ap.error("provide --data FILE (or use --suite)")
        df = load(args.data, args.start, args.end); b = bh(df)
        print(f"{args.data}: {len(df):,} bars  {df.index[0].date()} -> {df.index[-1].date()}  (buy&hold {b:+}%)\n")
        if args.strategy == "donchian":
            rs = donchian(df, args.lookback, args.atr_mult, args.atr_period)
            lbl = f"Donchian-{args.lookback} ({args.atr_mult}xATR trail)"
        elif args.strategy == "ema_cross":
            rs = ema_cross(df, args.fast, args.slow, args.atr_mult, args.atr_period)
            lbl = f"EMA {args.fast}/{args.slow} cross"
        else:
            rs = asian_breakout(df, args.target_r)
            lbl = f"Asian->London {args.target_r}R"
        rows.append(summarize(rs, lbl, b))

    print()
    print_table(rows)
    if args.out:
        with open(args.out, "w") as f:
            json.dump(rows, f, indent=2)
        print(f"\nSaved -> {args.out}")


if __name__ == "__main__":
    main()
