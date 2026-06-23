"""
End-to-end smoke test on SYNTHETIC data — no project data or TimesFM needed.

Generates a fake M15 OHLC series with a regime-switching trend (so the direction
model has something to find) plus intrabar noise, resamples to H4, then runs the
full pipeline with the baseline forecaster for BOTH level modes.

Purpose: prove the wiring works (forecaster -> signal -> level detection ->
causal mapping -> entries -> cost-adjusted trade log). It is NOT a performance
claim.

    python smoke_test.py
"""
from __future__ import annotations

import sys
from pathlib import Path
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from v2_common import resample_h4_ny, summarize  # noqa: E402
from tfm_engine import run_tfm  # noqa: E402


def make_synthetic_m15(n_days: int = 400, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    bars = n_days * 96  # 96 M15 bars / day
    idx = pd.date_range("2022-06-01", periods=bars, freq="15min", tz="UTC")

    # regime-switching drift to create trends the forecaster can latch onto
    drift = np.zeros(bars)
    state = 0.0
    for i in range(bars):
        if rng.random() < 0.002:                 # ~ switch every ~500 bars
            state = rng.choice([-1.0, 0.0, 1.0]) * 0.00025
        drift[i] = state
    shock = rng.normal(0, 0.0009, bars)
    logp = np.cumsum(drift + shock) + np.log(1900.0)
    close = np.exp(logp)

    # build OHLC with wicks around the close path
    spread = np.abs(rng.normal(0, 0.0012, bars)) * close
    high = close + spread * rng.uniform(0.3, 1.0, bars)
    low = close - spread * rng.uniform(0.3, 1.0, bars)
    open_ = np.empty(bars)
    open_[0] = close[0]
    open_[1:] = close[:-1]
    high = np.maximum.reduce([high, open_, close])
    low = np.minimum.reduce([low, open_, close])
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close},
                        index=idx)


def main():
    m15 = make_synthetic_m15()
    h4 = resample_h4_ny(m15)
    print(f"synthetic data: {len(m15)} M15 bars, {len(h4)} H4 bars, "
          f"{m15.index[0].date()} -> {m15.index[-1].date()}")

    any_trades = False
    for mode in ("swing", "h4candle"):
        trades, direction = run_tfm(
            h4, m15, forecaster_kind="baseline",
            forecaster_kw=dict(horizon=6, min_move_frac=0.001),
            level_mode=mode, rr=3.0, spread=0.25, slip_atr=0.05)
        nonzero = int((direction.signal != 0).sum())
        s = summarize(trades, "net_r") if len(trades) else {"n": 0}
        print(f"\n[mode={mode}] H4 directional bars={nonzero}/{len(direction.signal)} "
              f"-> trades={s['n']}")
        if len(trades):
            any_trades = True
            print(trades[["side", "entry_time", "entry_price", "exit_reason",
                          "realized_r", "net_r"]].head(8).to_string(index=False))
            print("  summary:", summarize(trades, "net_r"))

    assert any_trades, "pipeline produced zero trades in both modes — check wiring"
    print("\nSMOKE TEST PASSED: full pipeline runs and produces trades.")


if __name__ == "__main__":
    main()
