"""Cross-sectional momentum / relative-strength backtest (standalone).

The one ICT-report idea with real academic backing: "be long the strongest
instrument, short the weakest."  This is cross-sectional momentum.  It needs a
BASKET — the more (uncorrelated) instruments, the better.  With only 2 it
degenerates to a single long/short pair (still runs, but low-confidence).

Method
  * load each instrument, resample to daily (D1) if intraday
  * align on common dates, compute daily returns
  * every `rebalance` trading days, rank instruments by trailing `lookback`-day
    return; go LONG the top half, SHORT the bottom half
  * weights = inverse-vol (risk parity) within each leg, dollar-neutral
  * hold to next rebalance; subtract `cost_bps` per unit turnover
Reports annualised return/vol/Sharpe, weekly hit-rate, max drawdown — for the
long/short book, a long-only-top variant, and each instrument's buy&hold.

Usage
  python run_relative_strength.py \
      --data ".../XAUUSD_D1.parquet" ".../GBPUSD_M15.parquet" ".../EURUSD_M15.parquet" \
      --lookback 63 --rebalance 5
Add as many --data files as you have; daily or intraday both fine.
"""
from __future__ import annotations
import argparse, json, os
import numpy as np
import pandas as pd

ANN = 252


def load_daily(path):
    df = pd.read_parquet(path)
    if not isinstance(df.index, pd.DatetimeIndex):
        df = df.set_index("timestamp")
    df.index = df.index.tz_localize("UTC") if df.index.tz is None else df.index.tz_convert("UTC")
    df = df.sort_index()
    # resample to D1 if it looks intraday (median gap < 20h)
    gap = df.index.to_series().diff().dt.total_seconds().median()
    if gap is not None and gap < 20 * 3600:
        df = df.resample("1D").agg({"close": "last"}).dropna()
    name = os.path.basename(path).split("_")[0].upper()
    return name, df["close"].rename(name)


def metrics(daily_ret):
    r = daily_ret.dropna()
    if len(r) < 30:
        return {"days": len(r)}
    eq = (1 + r).cumprod()
    dd = (eq / eq.cummax() - 1).min()
    ann_ret = (1 + r.mean()) ** ANN - 1
    ann_vol = r.std() * np.sqrt(ANN)
    sharpe = (r.mean() / r.std() * np.sqrt(ANN)) if r.std() > 0 else 0.0
    return {"days": len(r), "ann_return_%": round(100 * ann_ret, 1),
            "ann_vol_%": round(100 * ann_vol, 1), "sharpe": round(sharpe, 2),
            "max_dd_%": round(100 * dd, 1)}


def run(prices, lookback=63, rebalance=5, cost_bps=2.0, long_only=False):
    """Ragged-date aware: each instrument participates only on dates where it has
    a valid price now and `lookback` days ago. Ranks among available instruments."""
    rets = prices.pct_change()
    dates = prices.index
    cols = prices.columns
    pos = pd.DataFrame(0.0, index=dates, columns=cols)
    cur = pd.Series(0.0, index=cols)
    for i in range(len(dates)):
        if i < lookback:
            pos.iloc[i] = cur
            continue
        if (i - lookback) % rebalance == 0:
            p_now = prices.iloc[i]; p_past = prices.iloc[i - lookback]
            valid = p_now.notna() & p_past.notna()
            mom = (p_now / p_past - 1)[valid].dropna()
            if len(mom) >= 2:
                vol = rets.iloc[i - 20:i].std()
                iv = (1.0 / vol).replace([np.inf, -np.inf], np.nan)
                m = len(mom); k = max(1, m // 2)
                rank = mom.rank(ascending=False)
                longs = rank[rank <= k].index
                shorts = rank[rank > m - k].index
                w = pd.Series(0.0, index=cols)
                ivl = iv.reindex(longs).fillna(0.0)
                if ivl.sum() > 0:
                    w[longs] = ivl / ivl.sum()
                if not long_only and m >= 2:
                    ivs = iv.reindex(shorts).fillna(0.0)
                    if ivs.sum() > 0:
                        w[shorts] = -ivs / ivs.sum()
                cur = w.fillna(0.0)
        pos.iloc[i] = cur
    port = (pos.shift(1) * rets).sum(axis=1, min_count=1)
    turn = pos.diff().abs().sum(axis=1).fillna(0.0)
    port = port - turn * (cost_bps / 10_000.0)
    return port


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", nargs="+", required=True, help="parquet files (daily or intraday)")
    ap.add_argument("--lookback", type=int, default=252)
    ap.add_argument("--rebalance", type=int, default=21)
    ap.add_argument("--cost-bps", type=float, default=2.0)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    series = {}
    for p in args.data:
        name, s = load_daily(p)
        series[name] = s
    prices = pd.concat(series.values(), axis=1).sort_index().dropna(how="all")
    print(f"Instruments: {list(prices.columns)}")
    cnt = int(prices.notna().sum(axis=1).iloc[-1])
    print(f"Window: {prices.index[0].date()} -> {prices.index[-1].date()}  ({len(prices)} days, {cnt} instruments active at end)\n")
    if prices.shape[1] < 2:
        print("Need >=2 instruments for relative strength."); return

    rep = {}
    rep["LongShort relative-strength"] = metrics(run(prices, args.lookback, args.rebalance, args.cost_bps, False))
    rep["LongOnly top-half momentum"] = metrics(run(prices, args.lookback, args.rebalance, args.cost_bps, True))
    for c in prices.columns:
        rep[f"BuyHold {c}"] = metrics(prices[c].pct_change())

    cols = ["days", "ann_return_%", "ann_vol_%", "sharpe", "max_dd_%"]
    w = max(len(k) for k in rep) + 2
    print("strategy".ljust(w) + "  ".join(c.rjust(13) for c in cols))
    print("-" * (w + 15 * len(cols)))
    for k, m in rep.items():
        print(k.ljust(w) + "  ".join(str(m.get(c, "")).rjust(13) for c in cols))
    if args.out:
        json.dump(rep, open(args.out, "w"), indent=2)
        print(f"\nSaved -> {args.out}")
    print(f"\nParams: lookback={args.lookback}d  rebalance={args.rebalance}d  cost={args.cost_bps}bps/turnover")
    if prices.shape[1] < 4:
        print("NOTE: only", prices.shape[1], "instruments — cross-sectional momentum needs a BASKET (6+).",
              "Treat this as a plumbing demo, not a verdict.")


if __name__ == "__main__":
    main()
