"""Layer 4 — Execution Engine (fast loop, pure deterministic).

Consumes an approved SizedOrder, submits a broker bracket, then manages the
position bar-by-bar: scale out at targets, ratchet the stop to breakeven after
T1, let the runner go. No LLM is ever called from this module.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from core.enums import OrderType, Side, TimeInForce
from data.base import BracketOrderRequest, BrokerAdapter, OrderResult
from risk.models import SizedOrder


@dataclass
class ManagedPosition:
    order: SizedOrder
    filled_qty: float = 0.0
    remaining_qty: float = 0.0
    targets_hit: int = 0
    stop_at_breakeven: bool = False
    scale_fractions: tuple[float, ...] = (0.5, 0.25)  # T1 50%, T2 25%, runner 25%


class ExecutionEngine:
    def __init__(self, adapter: BrokerAdapter) -> None:
        self.adapter = adapter
        self.positions: dict[str, ManagedPosition] = {}

    async def open_from_plan(self, order: SizedOrder) -> OrderResult:
        req = BracketOrderRequest(
            symbol=order.symbol, side=order.side, qty=order.qty,
            entry_type=OrderType.LIMIT, entry_price=order.entry_price,
            stop_price=order.stop_price, take_profit_prices=order.take_profit_prices,
            tif=TimeInForce.DAY,
        )
        result = await self.adapter.submit_bracket(req)
        if result.accepted:
            self.positions[order.symbol] = ManagedPosition(
                order=order, filled_qty=order.qty, remaining_qty=order.qty
            )
        return result

    def on_price(self, symbol: str, price: float) -> list[str]:
        """Deterministic management actions for a new price tick/bar.
        Returns a list of action descriptors (the caller routes them to the broker)."""
        pos = self.positions.get(symbol)
        if not pos:
            return []
        actions: list[str] = []
        long = pos.order.side is Side.LONG
        tps = pos.order.take_profit_prices

        # scale out at each target
        if pos.targets_hit < len(tps):
            t = tps[pos.targets_hit]
            hit = price >= t if long else price <= t
            if hit:
                frac = pos.scale_fractions[min(pos.targets_hit, len(pos.scale_fractions) - 1)]
                qty = round(pos.order.qty * frac, 8)
                pos.remaining_qty = max(0.0, pos.remaining_qty - qty)
                pos.targets_hit += 1
                actions.append(f"scale_out:{qty}@{t}")
                if pos.targets_hit == 1 and not pos.stop_at_breakeven:
                    pos.stop_at_breakeven = True
                    actions.append(f"move_stop_breakeven:{pos.order.entry_price}")
        return actions
