"""Layer 5 — out-of-process immutable audit log.

Append-only record of every LLM prompt/response, agent signal, feature snapshot,
risk decision, and trade outcome. Separate from the LangGraph checkpointer so a
state rollback never erases the audit trail. Implementation stub: swap the body
for asyncpg / SQLAlchemy against an append-only (no UPDATE/DELETE grant) table.
"""
from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from typing import Any


def _ser(obj: Any) -> Any:
    if is_dataclass(obj):
        return asdict(obj)
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    return obj


class AuditLog:
    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self._pool = None  # TODO: asyncpg.create_pool(dsn)

    async def record(self, kind: str, symbol: str, payload: Any) -> None:
        row = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "kind": kind,            # e.g. llm_io | agent_signal | feature_snapshot | risk_decision | fill
            "symbol": symbol,
            "payload": json.dumps(_ser(payload), default=str),
        }
        # TODO: INSERT INTO audit_log(...) VALUES (...)  -- table has no UPDATE/DELETE grants
        print(f"[AUDIT] {row['kind']} {row['symbol']}")  # placeholder sink
