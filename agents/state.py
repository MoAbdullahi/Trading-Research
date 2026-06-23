"""Layer 3 — LangGraph state schema.

One graph instance walks one symbol through SCANNING -> PLAN_ARMED -> IN_TRADE
-> MANAGING -> FLAT. The state is the single mutable object LangGraph threads
between nodes and checkpoints to Postgres after every node.
"""
from __future__ import annotations

from typing import Annotated, Optional, TypedDict

from core.enums import AssetClass, SymbolState
from core.schemas import AgentSignal, TradePlan, XSentimentMetrics, XSentimentSignal


def _replace(_old, new):
    """Reducer: last writer wins (agents overwrite their own slot)."""
    return new


def _append(old: list, new: list) -> list:
    return (old or []) + (new or [])


class GraphState(TypedDict, total=False):
    # identity
    symbol: str
    asset_class: AssetClass
    state: SymbolState

    # inputs threaded to the agents (feature snapshot serialized to dict)
    feature_snapshot: dict
    macro_context: dict
    news_items: list[dict]
    account_snapshot: dict

    # agent outputs — each agent writes one AgentSignal
    signals: Annotated[list[AgentSignal], _append]

    # orchestrator output
    consensus_score: int
    consensus_threshold: int        # optional per-run override (lean mode uses 2)
    trade_plan: Optional[TradePlan]

    # X sentiment pipeline
    x_sentiment_metrics: Optional[XSentimentMetrics]   # computed by sentiment_engine.py
    x_sentiment_signal: Optional[XSentimentSignal]     # output of x_sentiment_agent_node
    volatility_alert: bool                              # propagated from orchestrator output

    # control
    turn: int                      # debate turn counter (capped by settings)
    halt_reason: Optional[str]
