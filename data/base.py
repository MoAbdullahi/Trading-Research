"""Broker / data abstraction.

Every venue implements the same interface so the feature engine, gateway, and
execution engine never import a vendor SDK directly. Add a new asset class by
adding an adapter — nothing upstream changes.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass
from datetime import datetime
from typing import AsyncIterator, Optional

from core.enums import AssetClass, OrderType, Side, TimeInForce
from core.schemas import Bar


@dataclass
class AccountState:
    equity: float
    cash: float
    buying_power: float
    is_pattern_day_trader: bool = False
    day_trade_count_5d: int = 0          # for PDT tracking on sub-$25k US accounts
    open_positions_value: float = 0.0


@dataclass
class BracketOrderRequest:
    symbol: str
    side: Side
    qty: float
    entry_type: OrderType
    entry_price: Optional[float]   # None for market
    stop_price: float
    take_profit_prices: list[float]
    tif: TimeInForce = TimeInForce.DAY


@dataclass
class OrderResult:
    accepted: bool
    broker_order_id: Optional[str]
    message: str = ""


class BrokerAdapter(abc.ABC):
    """Unified data + execution gateway for one venue/asset class."""

    asset_class: AssetClass

    # --- market data ---
    @abc.abstractmethod
    async def get_historical_bars(
        self, symbol: str, timeframe: str, start: datetime, end: datetime
    ) -> list[Bar]:
        ...

    @abc.abstractmethod
    async def stream_bars(self, symbols: list[str]) -> AsyncIterator[Bar]:
        """Async generator of closed bars for the fast loop."""
        ...

    # --- account + execution ---
    @abc.abstractmethod
    async def get_account(self) -> AccountState:
        ...

    @abc.abstractmethod
    async def submit_bracket(self, req: BracketOrderRequest) -> OrderResult:
        ...

    @abc.abstractmethod
    async def is_shortable(self, symbol: str) -> bool:
        ...

    @abc.abstractmethod
    async def is_ssr_active(self, symbol: str) -> bool:
        """Short-sale restriction (equities). Non-equity adapters return False."""
        ...

    @abc.abstractmethod
    async def session_is_open(self, symbol: str, at: datetime) -> bool:
        ...
