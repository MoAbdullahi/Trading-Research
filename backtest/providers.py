"""Pluggable decision layer for replay.

Both providers return a list of AgentSignal for a given feature snapshot; the
replay harness then feeds those into the REAL orchestrator_node + gateway, so the
production decision path is never bypassed.

  DeterministicSignalProvider — regime rules as pure code. Fast, free, fully
      reproducible. Use for plumbing validation and regression. NOTE: this tests
      the machinery, not the LLM's judgement.

  PullbackSignalProvider — variant of the deterministic baseline with two changes:
      (1) trend_up fires LONG only when price has pulled back to within
          pullback_atr_max ATR of the nearest support (ORB high / VWAP / EMA-9),
          buying the retest not the extended breakout; (2) time gate blocks new
          entries after trade_window_end ET (default 11:00 AM). Reversal and
          neutral logic is unchanged so those regimes remain a fair comparison.

  LiveAgentSignalProvider — calls the real LLM agents. Use to evaluate the actual
      edge. Slower and token-costly; temperature 0 keeps it largely reproducible.
"""
from __future__ import annotations

from datetime import time as _time

from core.enums import AgentVote
from core.schemas import AgentSignal
from features.regime import classify_regime


def _bar_in_window(ts, end_time: _time) -> bool:
    """True if the bar's local ET time is strictly before end_time."""
    if ts is None:
        return True
    try:
        local = ts.tz_convert("America/New_York") if hasattr(ts, "tz_convert") \
            else ts.astimezone(__import__("zoneinfo").ZoneInfo("America/New_York"))
        return local.time() < end_time
    except Exception:
        return True


class DeterministicSignalProvider:
    """Encodes the same regime-aware criteria the technical agent prompts for,
    as deterministic code — a faithful, reproducible stand-in and a permanent
    baseline the live agents can be benchmarked against."""

    def __init__(self, rvol_trend: float = 2.0, rvol_reversal: float = 2.0,
                 rsi_low: float = 10.0, rsi_high: float = 90.0) -> None:
        self.rvol_trend = rvol_trend
        self.rvol_reversal = rvol_reversal
        self.rsi_low = rsi_low
        self.rsi_high = rsi_high

    def get_signals(self, fs: dict, window=None, asset_class: str = "equity") -> list[AgentSignal]:
        regime = classify_regime(fs)
        close = fs.get("last_close")
        vwap = fs.get("vwap")
        rvol = fs.get("rvol") or 0.0
        rsi = fs.get("rsi")
        emas = fs.get("ema") or {}
        vote = AgentVote.FLAT

        if regime == "trend_up":
            ema_ok = all(close > v for v in (emas.get(9), emas.get(20)) if v is not None)
            if close and vwap and close > vwap and rvol >= self.rvol_trend and ema_ok:
                vote = AgentVote.LONG
        elif regime == "reversal":
            sup = fs.get("support_levels") or []
            at_support = bool(sup) and close is not None and close <= max(sup) * 1.002
            if rsi is not None and rsi < self.rsi_low and rvol >= self.rvol_reversal and at_support:
                vote = AgentVote.LONG
            elif rsi is not None and rsi > self.rsi_high and rvol >= self.rvol_reversal:
                vote = AgentVote.SHORT
        # neutral -> FLAT

        conf = 0.8 if vote is not AgentVote.FLAT else 0.6
        # macro + sentiment abstain (no data in replay); technical + risk mirror the rule
        return [
            AgentSignal(agent_name="technical", vote=vote, confidence=conf, rationale=f"det:{regime}"),
            AgentSignal(agent_name="risk_manager", vote=vote, confidence=conf, rationale="det:no-corr"),
            AgentSignal(agent_name="macro", vote=AgentVote.ABSTAIN, confidence=0.0),
            AgentSignal(agent_name="sentiment", vote=AgentVote.ABSTAIN, confidence=0.0),
        ]


class PullbackSignalProvider:
    """Fires LONG only on pullbacks to support within the morning session.

    Keeps the entry as the single variable: exits stay on full_target so the
    result is directly comparable to the deterministic-baseline full_target run.
    """

    def __init__(
        self,
        pullback_atr_max: float = 1.0,
        rvol_pullback: float = 1.5,
        rvol_reversal: float = 2.0,
        rsi_low: float = 10.0,
        rsi_high: float = 90.0,
        trade_window_end: _time = _time(11, 0),
    ) -> None:
        self.pullback_atr_max = pullback_atr_max
        self.rvol_pullback = rvol_pullback
        self.rvol_reversal = rvol_reversal
        self.rsi_low = rsi_low
        self.rsi_high = rsi_high
        self.trade_window_end = trade_window_end

    def get_signals(self, fs: dict, window=None, asset_class: str = "equity") -> list[AgentSignal]:
        regime = classify_regime(fs)

        if not _bar_in_window(fs.get("ts"), self.trade_window_end):
            return [
                AgentSignal(agent_name="technical", vote=AgentVote.FLAT,
                            confidence=0.6, rationale=f"time_gate:{regime}"),
                AgentSignal(agent_name="risk_manager", vote=AgentVote.FLAT,
                            confidence=0.6, rationale="time_gate"),
                AgentSignal(agent_name="macro", vote=AgentVote.ABSTAIN, confidence=0.0),
                AgentSignal(agent_name="sentiment", vote=AgentVote.ABSTAIN, confidence=0.0),
            ]

        close = fs.get("last_close")
        vwap = fs.get("vwap")
        rvol = fs.get("rvol") or 0.0
        rsi = fs.get("rsi")
        atr = fs.get("atr") or 0.0
        emas = fs.get("ema") or {}
        vote = AgentVote.FLAT

        if regime == "trend_up" and atr > 0 and close and vwap and close > vwap:
            # highest support at or below current price among {VWAP, EMA-9, ORB high}
            candidates = [
                x for x in (vwap, emas.get(9), fs.get("orb_high"))
                if x is not None and x <= close
            ]
            if candidates:
                nearest = max(candidates)
                if (close - nearest) <= self.pullback_atr_max * atr and rvol >= self.rvol_pullback:
                    vote = AgentVote.LONG

        elif regime == "reversal":
            sup = fs.get("support_levels") or []
            at_support = bool(sup) and close is not None and close <= max(sup) * 1.002
            if rsi is not None and rsi < self.rsi_low and rvol >= self.rvol_reversal and at_support:
                vote = AgentVote.LONG
            elif rsi is not None and rsi > self.rsi_high and rvol >= self.rvol_reversal:
                vote = AgentVote.SHORT

        conf = 0.8 if vote is not AgentVote.FLAT else 0.6
        return [
            AgentSignal(agent_name="technical", vote=vote, confidence=conf,
                        rationale=f"pullback:{regime}"),
            AgentSignal(agent_name="risk_manager", vote=vote, confidence=conf,
                        rationale="det:no-corr"),
            AgentSignal(agent_name="macro", vote=AgentVote.ABSTAIN, confidence=0.0),
            AgentSignal(agent_name="sentiment", vote=AgentVote.ABSTAIN, confidence=0.0),
        ]


class LiveAgentSignalProvider:
    """Runs the real LLM agents (costs tokens). Returns their actual votes."""

    def get_signals(self, fs: dict, window=None, asset_class: str = "equity") -> list[AgentSignal]:
        from agents.agents import (
            macro_agent, risk_manager_agent, sentiment_agent, technical_agent,
        )
        state = {"feature_snapshot": fs, "asset_class": asset_class,
                 "macro_context": {}, "news_items": [], "account_snapshot": {}}
        signals: list[AgentSignal] = []
        for fn in (technical_agent, macro_agent, sentiment_agent, risk_manager_agent):
            signals.extend(fn(state)["signals"])
        return signals
