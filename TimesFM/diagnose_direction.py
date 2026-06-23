"""
Direction-quality diagnostic — isolates the TimesFM forecast from the entry logic.

The backtest mixes two things: (1) is the H4 direction call any good, and (2) is
the level/rejection entry any good. This script measures ONLY (1): does
sign(forecast) predict the realized H4 forward return over the horizon?

A directional edge shows up as a hit rate meaningfully above 50%. At/below 50%
means the signal is noise (or, well below 50%, anti-predictive).

Writes results/direction_diagnostic.csv AND prints the same table.

    python diagnose_direction.py --forecaster timesfm --stride 8 --min-move-frac 0.0005
    python diagnose_direction.py --forecaster baseline          # sanity ref
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from v2_common import resample_h4_ny  # noqa: E402
from direction_model import make_forecaster  # noqa: E402

_CANDIDATES = [HERE / "data"]
DATA = next((p for p in _CANDIDATES if p.exists()), _CANDIDATES[0])
OUT = HERE / "results"
OUT.mkdir(exist_ok=True)
SPLIT = pd.Timestamp("2025-01-01", tz="UTC")


def _tz(df):
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    df.index = df.index.as_unit("ns")
    return df.sort_index()


def hit_stats(sig, fwd_ret, mask):
    m = mask & (sig != 0) & np.isfinite(fwd_ret)
    n = int(m.sum())
    if n == 0:
        return dict(n=0, hit=float("nan"), long_n=0, long_hit=float("nan"),
                    short_n=0, short_hit=float("nan"), mean_signed_ret=float("nan"))
    correct = np.sign(fwd_ret[m]) == np.sign(sig[m])
    lm = m & (sig == 1)
    sm = m & (sig == -1)
    signed = sig[m] * fwd_ret[m]
    return dict(
        n=n, hit=round(100 * correct.mean(), 1),
        long_n=int(lm.sum()),
        long_hit=round(100 * (np.sign(fwd_ret[lm]) == 1).mean(), 1) if lm.any() else float("nan"),
        short_n=int(sm.sum()),
        short_hit=round(100 * (np.sign(fwd_ret[sm]) == -1).mean(), 1) if sm.any() else float("nan"),
        mean_signed_ret=round(float(np.mean(signed)), 6),
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="XAUUSD")
    ap.add_argument("--forecaster", default="timesfm", choices=["baseline", "timesfm"])
    ap.add_argument("--horizon", type=int, default=6)
    ap.add_argument("--min-move-frac", type=float, default=0.0005)
    ap.add_argument("--stride", type=int, default=8)
    ap.add_argument("--context", type=int, default=512)
    args = ap.parse_args()

    m15 = _tz(pd.read_parquet(DATA / "m15" / f"{args.symbol}_M15.parquet"))
    h4 = resample_h4_ny(m15)

    fc_kw = dict(horizon=args.horizon, min_move_frac=args.min_move_frac)
    if args.forecaster == "timesfm":
        fc_kw.update(stride=args.stride, context=args.context)
    forecaster = make_forecaster(args.forecaster, **fc_kw)
    d = forecaster.predict(h4)

    close = h4["close"].to_numpy(float)
    h = args.horizon
    fwd = np.full(len(close), np.nan)
    fwd[:-h] = close[h:] / close[:-h] - 1.0

    sig = d.signal.to_numpy(int)
    raw = np.sign(np.nan_to_num(d.median_fc.to_numpy(float) - d.last_close.to_numpy(float))).astype(int)

    is_test = np.asarray(h4.index >= SPLIT)
    is_train = ~is_test

    header = (f"{args.forecaster}  {args.symbol}  horizon={h} H4 bars  "
              f"min_move={args.min_move_frac}  stride={args.stride}")
    lines = ["", header, "=" * 74,
             "edge = hit clearly > 50%.  ~50% = noise.  <50% = backwards.", ""]
    csv_rows = []
    for label, key, s in [("GATED signal (what the backtest trades)", "gated", sig),
                          ("RAW median-forecast direction (no gate) ", "raw", raw)]:
        lines.append(label)
        for pname, mask in [("train", is_train), ("test ", is_test)]:
            st = hit_stats(s, fwd, mask)
            lines.append(
                f"  {pname}: n={st['n']:5d}  hit={st['hit']:5}%  "
                f"long(n={st['long_n']:4d},hit={st['long_hit']:5}%)  "
                f"short(n={st['short_n']:4d},hit={st['short_hit']:5}%)  "
                f"mean_signed_ret={st['mean_signed_ret']:+.5f}")
            csv_rows.append({"forecaster": args.forecaster, "symbol": args.symbol,
                             "signal": key, "period": pname.strip(), **st})
        lines.append("")

    text = "\n".join(lines)
    print(text)
    pd.DataFrame(csv_rows).to_csv(OUT / "direction_diagnostic.csv", index=False)
    (OUT / "direction_diagnostic.txt").write_text(text, encoding="utf-8")
    print("saved -> results/direction_diagnostic.csv  (+ .txt)")


if __name__ == "__main__":
    main()
