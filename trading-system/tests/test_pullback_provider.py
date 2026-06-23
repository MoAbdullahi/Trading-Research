"""Tests for PullbackSignalProvider — time gate and pullback condition.

Each test is designed to be trivially readable: one feature snapshot, one
expected outcome, no mocking required.
"""
from __future__ import annotations

from datetime import time

import pandas as pd
import pytest

from backtest.providers import PullbackSignalProvider
from core.enums import AgentVote


def _fs(**kwargs):
    """Build a minimal feature snapshot dict with sensible defaults."""
    defaults = dict(
        ts=pd.Timestamp("2026-01-02 14:45:00", tz="UTC"),  # 9:45 AM ET (in window)
        last_close=202.0,
        orb_high=200.0,
        orb_low=196.0,
        vwap=200.5,
        rvol=1.8,
        rsi=55.0,
        atr=1.0,
        ema={9: 201.0, 20: 199.0},
        support_levels=[196.0],
        resistance_levels=[206.0],
    )
    defaults.update(kwargs)
    return defaults


def _tech_vote(signals):
    return next(s.vote for s in signals if s.agent_name == "technical")


# ------------------------------------------------------------------ time gate

def test_time_gate_blocks_after_window():
    # January is EST (UTC-5): 11:05 AM ET = 16:05 UTC
    fs = _fs(ts=pd.Timestamp("2026-01-02 16:05:00", tz="UTC"))
    p = PullbackSignalProvider()
    sigs = p.get_signals(fs)
    assert _tech_vote(sigs) is AgentVote.FLAT
    assert sigs[0].rationale.startswith("time_gate")


def test_time_gate_allows_before_window():
    # 10:55 AM ET = 15:55 UTC (January EST, just inside window)
    fs = _fs(ts=pd.Timestamp("2026-01-02 15:55:00", tz="UTC"))
    p = PullbackSignalProvider()
    sigs = p.get_signals(fs)
    # should evaluate normally (not gated); defaults produce a LONG
    assert sigs[0].rationale.startswith("pullback")


def test_time_gate_blocks_exactly_at_end():
    # exactly 11:00 AM ET = 16:00 UTC is NOT in window (strict <)
    fs = _fs(ts=pd.Timestamp("2026-01-02 16:00:00", tz="UTC"))
    p = PullbackSignalProvider()
    sigs = p.get_signals(fs)
    assert _tech_vote(sigs) is AgentVote.FLAT


# -------------------------------------------------------- pullback condition

def test_pullback_fires_when_near_vwap():
    # close is 0.5 ATR above VWAP — within the 1.0 ATR window
    p = PullbackSignalProvider(pullback_atr_max=1.0, rvol_pullback=1.5)
    fs = _fs(last_close=201.0, vwap=200.5, atr=1.0, rvol=1.8)
    # close - vwap = 0.5, atr = 1.0 → 0.5 <= 1.0 → should fire
    assert _tech_vote(p.get_signals(fs)) is AgentVote.LONG


def test_pullback_suppressed_when_extended():
    # All supports at/below 200; close=201.6 is 1.6 ATR above nearest → FLAT
    p = PullbackSignalProvider(pullback_atr_max=1.0, rvol_pullback=1.5)
    fs = _fs(last_close=201.6, vwap=200.0, orb_high=200.0,
             ema={9: 199.0, 20: 198.0}, atr=1.0, rvol=1.8)
    # nearest support = max(200.0, 199.0, 200.0) = 200.0
    # close - nearest = 1.6 > 1.0 × atr → FLAT
    assert _tech_vote(p.get_signals(fs)) is AgentVote.FLAT


def test_pullback_suppressed_when_rvol_low():
    p = PullbackSignalProvider(pullback_atr_max=1.0, rvol_pullback=1.5)
    fs = _fs(last_close=201.0, vwap=200.5, atr=1.0, rvol=1.2)  # RVOL below threshold
    assert _tech_vote(p.get_signals(fs)) is AgentVote.FLAT


def test_pullback_uses_orb_high_as_support():
    # EMA9 and VWAP are both below ORB high; ORB high is the tightest support
    p = PullbackSignalProvider(pullback_atr_max=0.5, rvol_pullback=1.5)
    fs = _fs(
        last_close=200.3,
        orb_high=200.0,  # nearest support
        vwap=198.0,
        ema={9: 199.0, 20: 197.0},
        atr=1.0,
        rvol=2.0,
    )
    # close - orb_high = 0.3, atr = 1.0, pullback_atr_max = 0.5 → 0.3 <= 0.5 → LONG
    assert _tech_vote(p.get_signals(fs)) is AgentVote.LONG


def test_neutral_regime_stays_flat():
    # price inside ORB → neutral regime → always FLAT
    p = PullbackSignalProvider()
    fs = _fs(last_close=198.0, orb_high=200.0, orb_low=196.0)
    assert _tech_vote(p.get_signals(fs)) is AgentVote.FLAT


def test_macro_sentiment_always_abstain():
    p = PullbackSignalProvider()
    sigs = p.get_signals(_fs())
    for s in sigs:
        if s.agent_name in ("macro", "sentiment"):
            assert s.vote is AgentVote.ABSTAIN
