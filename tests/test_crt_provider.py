"""Tests for CRTSignalProvider: sweep detection, MSS, OB_ONLY, abstain conditions."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backtest.providers_crt import CRTParams, CRTSignalProvider
from core.enums import AgentVote
from core.schemas import KeyLevels


def _make_window(rows: list[dict]) -> pd.DataFrame:
    """Build a tz-aware UTC M15 DataFrame from a list of OHLCV dicts."""
    idx = pd.date_range("2025-01-06 00:00", periods=len(rows), freq="15min", tz="UTC")
    df = pd.DataFrame(rows, index=idx)
    for col in ("open", "high", "low", "close", "volume"):
        if col not in df.columns:
            df[col] = 1.0
    return df[["open", "high", "low", "close", "volume"]]


def _flat_bars(n: int, price: float = 2000.0, atr_noise: float = 2.0) -> list[dict]:
    """Quiet range bars with mild ATR noise so ATR is non-zero."""
    rng = np.random.default_rng(42)
    bars = []
    for _ in range(n):
        o = price + rng.uniform(-atr_noise * 0.1, atr_noise * 0.1)
        h = o + rng.uniform(0, atr_noise * 0.5)
        l = o - rng.uniform(0, atr_noise * 0.5)
        c = o + rng.uniform(-atr_noise * 0.2, atr_noise * 0.2)
        bars.append({"open": o, "high": h, "low": min(l, c - 0.01), "close": c, "volume": 1.0})
    return bars


def _build_bullish_crt(range_high=2010.0, range_low=2000.0) -> pd.DataFrame:
    """Build a minimal valid bullish CRT setup with fully deterministic, hand-crafted bars.

    H4 range candle (bars 0-15): highs at range_high-0.5, lows at range_low+0.5 so
    the computed H4 range is exactly [range_low+0.5, range_high-0.5].

    Active H4 bars (16+):
      sweep: wick to sweep_extreme, high=react_high, closes inside range
      OB: bearish bar (body 3pts)
      displacement: strongly bullish, close above react_high (MSS)
      retrace: close inside OB, low touches OB high (OB_ONLY trigger)
    """
    sweep_extreme = range_low - 5.0    # e.g. 1995.0
    react_high    = range_low + 3.0    # e.g. 2003.0  (reaction high at sweep bar)
    ob_open       = range_low + 3.5    # e.g. 2003.5
    ob_close      = range_low + 0.5    # e.g. 2000.5  (bearish OB body)
    disp_close    = react_high + 4.0   # e.g. 2007.0  (clears react_high for MSS)

    rows: list[dict] = []

    # H4 range candle: alternate tight bars so max-high = range_high-0.5, min-low = range_low+0.5
    for i in range(16):
        h = range_high - 0.5
        l = range_low + 0.5
        rows.append({"open": (h + l) / 2 - 0.2, "high": h, "low": l,
                     "close": (h + l) / 2 + 0.2, "volume": 1.0})

    # Sweep bar: wick below range_low, closes inside range; react_high < range_high so swept_high=False
    rows.append({"open": range_low + 1.0, "high": react_high,
                 "low": sweep_extreme, "close": range_low + 0.8, "volume": 1.0})

    # 2 quiet consolidation bars (inside range, small bullish body)
    for _ in range(2):
        rows.append({"open": range_low + 1.0, "high": range_low + 1.8,
                     "low": range_low + 0.5, "close": range_low + 1.5, "volume": 1.0})

    # OB: last bearish bar before displacement
    rows.append({"open": ob_open, "high": ob_open + 0.5, "low": ob_close - 0.3,
                 "close": ob_close, "volume": 1.0})

    # Displacement: strongly bullish body (>> ATR), close above react_high (MSS)
    rows.append({"open": ob_close, "high": disp_close + 0.5,
                 "low": ob_close - 0.1, "close": disp_close, "volume": 1.0})

    # Retrace: price pulls back to OB (last bar low <= ob_open = ob_high by body rule)
    retrace_mid = (ob_open + ob_close) / 2.0
    rows.append({"open": disp_close, "high": disp_close + 0.2,
                 "low": ob_close, "close": retrace_mid, "volume": 1.0})

    return _make_window(rows)


# --------------------------------------------------------------------------- #

class TestCRTAbstain:
    def test_abstains_on_none_window(self):
        p = CRTSignalProvider()
        sigs = p.get_signals({}, window=None)
        assert all(s.vote is AgentVote.ABSTAIN for s in sigs)

    def test_abstains_on_short_window(self):
        p = CRTSignalProvider()
        w = _make_window(_flat_bars(30))
        sigs = p.get_signals({}, window=w)
        assert all(s.vote is AgentVote.ABSTAIN for s in sigs)

    def test_abstains_on_quiet_range_no_sweep(self):
        p = CRTSignalProvider()
        # 64 quiet bars inside a narrow band — no sweep of either H4 extreme
        w = _make_window(_flat_bars(64, price=2000.0, atr_noise=1.0))
        sigs = p.get_signals({}, window=w)
        assert all(s.vote is AgentVote.ABSTAIN for s in sigs)


_TEST_PARAMS = CRTParams(displacement_atr_mult=0.5, min_m15_bars=20)


class TestCRTBullishDetection:
    def test_bullish_setup_fires_long(self):
        p = CRTSignalProvider(_TEST_PARAMS)
        w = _build_bullish_crt()
        sigs = p.get_signals({}, window=w)
        tech = next(s for s in sigs if s.agent_name == "technical")
        assert tech.vote is AgentVote.LONG

    def test_bullish_levels_geometry(self):
        p = CRTSignalProvider(_TEST_PARAMS)
        w = _build_bullish_crt()  # default range 2010/2000 keeps ATR manageable
        sigs = p.get_signals({}, window=w)
        tech = next(s for s in sigs if s.agent_name == "technical")
        assert tech.proposed_levels is not None
        lv: KeyLevels = tech.proposed_levels
        # stop < entry < target
        assert lv.stop < lv.entry < lv.targets[0], (
            f"geometry violated: stop={lv.stop} entry={lv.entry} target={lv.targets[0]}"
        )

    def test_bullish_target_is_range_high(self):
        p = CRTSignalProvider(_TEST_PARAMS)
        w = _build_bullish_crt(range_high=2010.0, range_low=2000.0)
        sigs = p.get_signals({}, window=w)
        tech = next(s for s in sigs if s.agent_name == "technical")
        # target = H4 range high = range_high - 0.5 (deterministic: every range bar has high=range_high-0.5)
        assert abs(tech.proposed_levels.targets[0] - 2009.5) < 0.01

    def test_risk_manager_mirrors_technical_vote(self):
        p = CRTSignalProvider(_TEST_PARAMS)
        w = _build_bullish_crt()
        sigs = p.get_signals({}, window=w)
        rm = next(s for s in sigs if s.agent_name == "risk_manager")
        assert rm.vote is AgentVote.LONG

    def test_macro_and_sentiment_abstain_always(self):
        p = CRTSignalProvider(_TEST_PARAMS)
        w = _build_bullish_crt()
        sigs = p.get_signals({}, window=w)
        for name in ("macro", "sentiment"):
            sig = next(s for s in sigs if s.agent_name == name)
            assert sig.vote is AgentVote.ABSTAIN


class TestCRTOBOnlyFilter:
    def test_no_signal_when_price_not_yet_retraced(self):
        """If the last bar's low is above OB high, OB_ONLY filter should block the signal."""
        p = CRTSignalProvider(_TEST_PARAMS)
        w = _build_bullish_crt(range_high=2010.0, range_low=2000.0)
        rows = [{"open": r.open, "high": r.high, "low": r.low, "close": r.close, "volume": 1.0}
                for r in w.itertuples()]
        # Replace the last bar: price extended up, low is well above OB (2003.5) — no retrace
        rows[-1] = {"open": 2008.0, "high": 2009.5, "low": 2007.0, "close": 2009.0, "volume": 1.0}
        w2 = _make_window(rows)
        sigs = p.get_signals({}, window=w2)
        tech = next(s for s in sigs if s.agent_name == "technical")
        assert tech.vote is AgentVote.ABSTAIN


class TestCRTProposedLevelsPlumbing:
    """proposed_levels flows through AgentSignal correctly."""

    def test_proposed_levels_is_none_on_abstain(self):
        p = CRTSignalProvider()
        sigs = p.get_signals({}, window=None)
        for s in sigs:
            assert s.proposed_levels is None

    def test_proposed_levels_is_keylevel_on_fire(self):
        p = CRTSignalProvider(_TEST_PARAMS)
        w = _build_bullish_crt()
        sigs = p.get_signals({}, window=w)
        tech = next(s for s in sigs if s.agent_name == "technical")
        assert isinstance(tech.proposed_levels, KeyLevels)
