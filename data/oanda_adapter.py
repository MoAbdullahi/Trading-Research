"""Forex + Gold adapter (OANDA v20) — phase 4 stub.

Drivers and constraints differ from equities: leverage caps by jurisdiction,
multi-session VWAP anchors (see config/sessions.py), weekend gaps.
    pip install oandapyV20
"""
from __future__ import annotations

from datetime import datetime
from typing import AsyncIterator

from core.enums import AssetClass
from core.schemas import Bar
from data.base import AccountState, BracketOrderRequest, BrokerAdapter, OrderResult


class OandaFxAdapter(BrokerAdapter):
    # one instance per asset_class; gold (XAUUSD) uses the same venue/profile shape
    def __init__(self, asset_class: AssetClass = AssetClass.FOREX) -> None:
        self.asset_class = asset_class
        self._client = None  # TODO: oandapyV20.API(access_token=...)

    async def get_historical_bars(self, symbol, timeframe, start, end) -> list[Bar]:
        raise NotImplementedError("wire oandapyV20 instruments.InstrumentsCandles")

    async def stream_bars(self, symbols) -> AsyncIterator[Bar]:
        if False:  # pragma: no cover
            yield  # type: ignore[misc]
        raise NotImplementedError("wire oandapyV20 pricing stream + bar aggregation")

    async def get_account(self) -> AccountState:
        raise NotImplementedError

    async def submit_bracket(self, req: BracketOrderRequest) -> OrderResult:
        raise NotImplementedError

    async def is_shortable(self, symbol: str) -> bool:
        return True  # FX is natively two-sided

    async def is_ssr_active(self, symbol: str) -> bool:
        return False

    async def session_is_open(self, symbol: str, at: datetime) -> bool:
        raise NotImplementedError("24/5 — gate weekends via config/sessions.py")
