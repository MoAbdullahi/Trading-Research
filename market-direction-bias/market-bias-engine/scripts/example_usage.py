"""Minimal end-to-end example for the bias engine.

Run:  python example_usage.py

It builds a synthetic regime-switching series (bull -> range -> bear) so the
example is self-contained and needs no network, then shows the three things a
caller cares about: the per-bar bias frame, the current_bias() summary with its
component breakdown, and how a TradePlan would consume it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from bias_engine import BiasEngine, BiasConfig, FactorWeights


def synthetic_series() -> pd.DataFrame:
    rng = np.random.default_rng(42)

    def leg(mu, sig, n, p0):
        return p0 * np.exp(np.cumsum(rng.normal(mu, sig, n)))

    bull = leg(0.004, 0.010, 180, 100.0)
    rng_seg = bull[-1] + rng.normal(0, 1.2, 160)          # flat, choppy
    bear = leg(-0.004, 0.010, 180, rng_seg[-1])
    close = np.concatenate([bull, rng_seg, bear])

    n = len(close)
    high = close * (1 + np.abs(rng.normal(0, 0.004, n)))
    low = close * (1 - np.abs(rng.normal(0, 0.004, n)))
    op = close * (1 + rng.normal(0, 0.002, n))
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {"Open": op, "High": high, "Low": low, "Close": close,
         "Volume": rng.integers(100_000, 1_000_000, n)},
        index=idx,
    )


def main():
    df = synthetic_series()

    engine = BiasEngine()                       # defaults match the spec

    # 1) Per-bar bias columns (good for backtests / plotting).
    out = engine.compute(df)
    cols = ["Close", "bias_score", "bias_effective_score", "bias_regime", "bias_label"]
    print("Last 5 bars:")
    print(out[cols].tail(5).to_string(), "\n")

    # 2) The summary a TradePlan calls, with the transparent breakdown.
    result = engine.current_bias(df)
    print(result.breakdown_table(), "\n")

    # 3) How a TradePlan would gate off it.
    if result.bias != 0 and result.regime == "trending":
        side = "LONG" if result.bias > 0 else "SHORT"
        print(f"TradePlan: trend regime, conviction {result.effective_score:+.2f} "
              f"-> look for {side} entries.")
    else:
        print(f"TradePlan: bias is {result.label} / regime {result.regime} "
              f"-> stand aside, no forced entry.")

    # 4) Ablation: zero out a factor and see the score move.
    print("\nAblation (drop SuperTrend to weight 0):")
    ablated = BiasEngine(BiasConfig(weights=FactorWeights(supertrend=0.0)))
    print(f"  full score    = {result.score:+.3f}")
    print(f"  ablated score = {ablated.current_bias(df).score:+.3f}")


if __name__ == "__main__":
    main()
