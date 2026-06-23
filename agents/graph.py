"""Layer 3 — graph construction.

Fan-out the enabled analyst agents in parallel, fan-in to the deterministic
orchestrator, then advance the per-symbol state machine. A Postgres checkpointer
makes the run crash-resumable.

`enabled_agents` lets you start lean (Technical + Risk) in Phase 2 and flip on
Macro + Sentiment later without touching the rest of the system.

    pip install langgraph langgraph-checkpoint-postgres
"""
from __future__ import annotations

from core.enums import Bias, SymbolState
from core.settings import get_settings
from agents.state import GraphState
from agents.agents import (
    macro_agent,
    risk_manager_agent,
    sentiment_agent,
    technical_agent,
)
from agents.orchestrator import orchestrator_node

_AGENT_NODES = {
    "technical": technical_agent,
    "macro": macro_agent,
    "sentiment": sentiment_agent,
    "risk_manager": risk_manager_agent,
}

# Phase 2 lean default
LEAN_AGENTS = ["technical", "risk_manager"]
ALL_AGENTS = list(_AGENT_NODES.keys())


def _route_after_orchestrator(state: dict) -> str:
    plan = state.get("trade_plan")
    if plan is None or plan.bias is Bias.FLAT:
        return "flat"
    return "armed"


def build_graph(checkpointer=None, enabled_agents: list[str] | None = None):
    """Compile a LangGraph app. `enabled_agents` defaults to all four; pass
    LEAN_AGENTS for the Phase 2 Technical+Risk lineup."""
    from langgraph.graph import END, START, StateGraph

    agents = enabled_agents or ALL_AGENTS
    unknown = set(agents) - set(_AGENT_NODES)
    if unknown:
        raise ValueError(f"unknown agents: {unknown}")

    g = StateGraph(GraphState)
    for name in agents:
        g.add_node(name, _AGENT_NODES[name])
    g.add_node("orchestrator", orchestrator_node)
    g.add_node("mark_armed", lambda s: {"state": SymbolState.PLAN_ARMED})
    g.add_node("mark_flat", lambda s: {"state": SymbolState.FLAT})

    for name in agents:                      # parallel fan-out
        g.add_edge(START, name)
        g.add_edge(name, "orchestrator")     # fan-in (orchestrator waits for all)

    g.add_conditional_edges(
        "orchestrator",
        _route_after_orchestrator,
        {"armed": "mark_armed", "flat": "mark_flat"},
    )
    g.add_edge("mark_armed", END)
    g.add_edge("mark_flat", END)

    if checkpointer is None:
        from langgraph.checkpoint.memory import MemorySaver
        checkpointer = MemorySaver()

    return g.compile(checkpointer=checkpointer)


def build_postgres_checkpointer():
    """Production checkpointer. Call .setup() once to create tables."""
    from langgraph.checkpoint.postgres import PostgresSaver
    dsn = get_settings().postgres_dsn
    return PostgresSaver.from_conn_string(dsn)
