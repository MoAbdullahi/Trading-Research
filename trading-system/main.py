"""Entrypoint wiring the two-speed architecture for a single US-equity symbol.

Phase-1 happy path:
  feature engine -> LangGraph slow loop -> TradePlan -> RiskGateway -> ExecutionEngine
Run with paper credentials. This is a skeleton: adapter methods marked TODO must
be wired before live data flows.
"""
from __future__ import annotations

import asyncio

from core.enums import AssetClass, SymbolState
from core.settings import get_settings
from config.sessions import profile_for
from data.alpaca_adapter import AlpacaEquityAdapter
from agents.graph import build_graph
from risk.gateway import RiskGateway
from risk.models import RiskLimits
from execution.engine import ExecutionEngine
from persistence.logging_db import AuditLog


async def run_symbol(symbol: str) -> None:
    s = get_settings()
    adapter = AlpacaEquityAdapter()
    gateway = RiskGateway(RiskLimits(
        max_per_trade_risk_pct=s.max_per_trade_risk_pct,
        min_reward_to_risk=s.min_reward_to_risk,
        max_concurrent_exposure_pct=s.max_concurrent_exposure_pct,
        max_account_drawdown_pct=s.max_account_drawdown_pct,
    ))
    execution = ExecutionEngine(adapter)
    audit = AuditLog(s.postgres_dsn)
    graph = build_graph()  # add Postgres checkpointer in production

    profile = profile_for(AssetClass.EQUITY)
    print(f"booted symbol={symbol} session_anchor={profile.vwap_anchor.value}")
    # TODO: 1) pull bars via adapter  2) compute_features  3) invoke graph
    #       4) gateway.evaluate(plan, account, market)  5) execution.open_from_plan
    _ = (execution, audit, graph)  # wired in phase 2


if __name__ == "__main__":
    asyncio.run(run_symbol("AAPL"))
