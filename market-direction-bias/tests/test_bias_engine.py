"""Unit tests for the bias engine using deterministic synthetic OHLC.

These fixtures are hand-built so the *right answer* is known: a clean uptrend
should read bullish, a clean downtrend bearish, and a tight oscillating range
should trip the ADX regime gate and refuse to commit. Because the engine is
deterministic, these assertions are stable run to run.

Run with:  pytest -q   (or)   python tests/test_bias_engine.py
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bias_engine import BiasEngine, BiasConfig, FactorWeights
from bias_engine.factors import FACTORS


def _ohlc_from_close(close: np.ndarray, spread: float = 0.4, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    n = len(close)
    high = close + np.abs(rng.normal(0, spread, n)) + spread
    low = close - np.abs(rng.normal(0, spread, n)) - spread
    op = close + rng.normal(0, spread / 2, n)
    idx = pd.date_range("2024-01-01", periods=n, freq="h")
    return pd.DataFrame(
        {"Open": op, "High": high, "Low": low, "Close": close,
         "Volume": rng.integers(1000, 10000, n)},
        index=idx,
    )


def uptrend(n: int = 400) -> pd.DataFrame:
    close = np.linspace(100, 200, n) + np.sin(np.linspace(0, 12, n)) * 1.5
    return _ohlc_from_close(close)


def downtrend(n: int = 400) -> pd.DataFrame:
    close = np.linspace(200, 100, n) + np.sin(np.linspace(0, 12, n)) * 1.5
    return _ohlc_from_close(close)


def ranging(n: int = 400) -> pd.DataFrame:
    # Directionless white noise around a constant: frequent reversals keep +DI
    # and -DI balanced and small, so ADX stays low (~5) -> the regime gate
    # should classify this as ranging and refuse a high-conviction call.
    rng = np.random.default_rng(3)
    close = 130 + rng.normal(0, 1.5, n)
    return _ohlc_from_close(close, spread=0.25)


# --------------------------------------------------------------------------

def test_default_weights_sum_to_one():
    assert abs(FactorWeights().total() - 1.0) < 1e-9


def test_uptrend_reads_bullish():
    res = BiasEngine().current_bias(uptrend())
    assert res.bias == 1, res.breakdown_table()
    assert res.label == "bullish"
    assert res.score > 0
    # the dominant structure factor should agree with the trend
    structure = next(c for c in res.components if c.name == "structure")
    assert structure.vote == 1


def test_downtrend_reads_bearish():
    res = BiasEngine().current_bias(downtrend())
    assert res.bias == -1, res.breakdown_table()
    assert res.label == "bearish"
    assert res.score < 0


def test_ranging_market_gate_engages():
    """In a tight range the engine should detect the ranging regime and not
    return a high-conviction directional call."""
    res = BiasEngine().current_bias(ranging())
    assert res.regime == "ranging", res.breakdown_table()
    # widened band applied
    assert res.neutral_band == BiasConfig().neutral_band_ranging
    # effective score is the halved score
    assert abs(res.effective_score - res.score * 0.5) < 1e-6


def test_current_bias_has_all_components():
    res = BiasEngine().current_bias(uptrend())
    names = [c.name for c in res.components]
    assert names == [k for k, _, _ in FACTORS]
    # contribution == vote * weight for every component
    for c in res.components:
        assert abs(c.contribution - c.vote * c.weight) < 1e-9
    # score is the sum of contributions
    assert abs(res.score - sum(c.contribution for c in res.components)) < 1e-6


def test_score_is_bounded():
    for df in (uptrend(), downtrend(), ranging()):
        out = BiasEngine().compute(df)
        assert out["bias_score"].between(-1.0, 1.0).all()
        assert out["bias_effective_score"].between(-1.0, 1.0).all()
        assert set(out["bias"].unique()).issubset({-1, 0, 1})


def test_compute_adds_expected_columns():
    out = BiasEngine().compute(uptrend())
    for k, _, _ in FACTORS:
        assert f"bias_vote_{k}" in out.columns
    for col in ("bias_score", "bias_effective_score", "bias_regime", "bias", "bias_label"):
        assert col in out.columns


def test_ablation_changes_score():
    """Zeroing a factor's weight must change the composite score -- proof the
    factor was actually contributing."""
    df = uptrend()
    full = BiasEngine().current_bias(df)
    ablated = BiasEngine(
        BiasConfig(weights=FactorWeights(supertrend=0.0))
    ).current_bias(df)
    st = next(c for c in full.components if c.name == "supertrend")
    if st.vote != 0:
        assert abs(ablated.score - full.score) > 1e-9
    # the ablated factor now has zero weight and zero contribution
    st2 = next(c for c in ablated.components if c.name == "supertrend")
    assert st2.weight == 0.0 and st2.contribution == 0.0


def test_premium_discount_sign_is_configurable():
    df = uptrend()
    bar = BiasEngine()._ensure_indicators(df).iloc[-1]
    from bias_engine.factors import premium_discount_vote
    smc = premium_discount_vote(bar, BiasConfig(discount_is_bullish=True))
    inv = premium_discount_vote(bar, BiasConfig(discount_is_bullish=False))
    assert smc.direction == -inv.direction


def test_premium_discount_regime_aware():
    """With pd_regime_aware on (default), the location factor abstains in a
    trend and only votes in a range -- so it stops fighting clean trends."""
    from bias_engine.factors import premium_discount_vote
    cfg = BiasConfig()  # pd_regime_aware=True by default
    trend_bar = {"pdz_zone": "discount", "pdz_zone_pct": 100, "ADX": 30.0}
    range_bar = {"pdz_zone": "discount", "pdz_zone_pct": 100, "ADX": 12.0}
    assert premium_discount_vote(trend_bar, cfg).direction == 0      # muted in trend
    assert premium_discount_vote(range_bar, cfg).direction == 1      # votes in range
    # turning it off restores voting in the trend
    off = BiasConfig(pd_regime_aware=False)
    assert premium_discount_vote(trend_bar, off).direction == 1


def test_missing_ohlc_raises():
    df = uptrend().drop(columns=["High"])
    try:
        BiasEngine().current_bias(df)
        assert False, "expected ValueError for missing OHLC column"
    except ValueError:
        pass


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        fn()
        print(f"PASS  {fn.__name__}")
        passed += 1
    print(f"\n{passed}/{len(fns)} tests passed")


if __name__ == "__main__":
    _run_all()
