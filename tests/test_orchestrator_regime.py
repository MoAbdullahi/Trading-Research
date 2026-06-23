"""Regime-aware consensus tests for the orchestrator.

  trend_up  -> structural = hard VWAP filter (vetoes counter-VWAP trades)
  reversal  -> structural = advisory vote (agents can outvote it)
  neutral   -> structural = advisory vote
Consensus = strict majority of non-abstaining directional signals, floor 2.
"""
import pytest

from core.enums import AgentVote, Bias
from core.schemas import AgentSignal
from agents.orchestrator import orchestrator_node

BASE = dict(vwap=307.64, atr=0.26, orb_high=310.56, orb_low=308.55,
            support_levels=[307.46, 310.66], resistance_levels=[307.74, 311.09])


def _run(fs, votes, threshold=None):
    state = {"symbol": "AAPL", "asset_class": "equity", "feature_snapshot": fs,
             "signals": [AgentSignal(agent_name=n, vote=v, confidence=0.7) for n, v in votes]}
    if threshold:
        state["consensus_threshold"] = threshold
    return orchestrator_node(state)


def test_reversal_agents_outvote_advisory_structural():
    fs = {**BASE, "last_close": 306.26}  # below ORB low -> reversal; below vwap -> structural SHORT
    out = _run(fs, [("technical", AgentVote.LONG), ("risk_manager", AgentVote.LONG),
                    ("macro", AgentVote.ABSTAIN), ("sentiment", AgentVote.ABSTAIN)])
    assert out["regime"] == "reversal"
    assert out["trade_plan"].bias is Bias.LONG
    assert out["structural_filter_applied"] is False


def test_trend_up_aligned_trades():
    fs = {**BASE, "last_close": 311.50, "vwap": 309.0}  # above ORB high & vwap
    out = _run(fs, [("technical", AgentVote.LONG), ("risk_manager", AgentVote.LONG),
                    ("macro", AgentVote.ABSTAIN), ("sentiment", AgentVote.ABSTAIN)])
    assert out["regime"] == "trend_up"
    assert out["trade_plan"].bias is Bias.LONG


def test_trend_up_vwap_filter_vetoes_counter_trend():
    fs = {**BASE, "last_close": 311.50, "vwap": 309.0}
    out = _run(fs, [("technical", AgentVote.SHORT), ("risk_manager", AgentVote.SHORT),
                    ("macro", AgentVote.ABSTAIN), ("sentiment", AgentVote.ABSTAIN)])
    assert out["regime"] == "trend_up"
    assert out["trade_plan"].bias is Bias.FLAT
    assert out["structural_filter_applied"] is True


def test_all_abstain_is_flat():
    fs = {**BASE, "last_close": 306.26}
    out = _run(fs, [(n, AgentVote.ABSTAIN) for n in ("technical", "risk_manager", "macro", "sentiment")])
    assert out["trade_plan"].bias is Bias.FLAT


def test_full_house_three_of_five():
    fs = {**BASE, "last_close": 311.50, "vwap": 309.0}  # structural LONG
    out = _run(fs, [("technical", AgentVote.LONG), ("risk_manager", AgentVote.LONG),
                    ("macro", AgentVote.LONG), ("sentiment", AgentVote.SHORT)])  # +structural = 4L/1S
    assert out["trade_plan"].bias is Bias.LONG
    assert out["consensus_score"] == 4


def test_directional_tie_is_flat():
    # no structural tiebreak: price == vwap -> structural ABSTAIN, agents split 1-1
    fs = {**BASE, "last_close": 307.64, "vwap": 307.64}
    out = _run(fs, [("technical", AgentVote.LONG), ("risk_manager", AgentVote.SHORT),
                    ("macro", AgentVote.ABSTAIN), ("sentiment", AgentVote.ABSTAIN)])
    assert out["trade_plan"].bias is Bias.FLAT
