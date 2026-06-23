"""Crypto adapter (CCXT) — phase 4 stub.

Key differences the rest of the system already accounts for:
  * 24/7 session (no PDT, no SSR, no market-closed gating)
  * spot crypto cannot be shorted -> is_shortable() returns False unless on a
    margin/derivatives endpoint
    pip install ccxt
"""
from __future__ import annotations

from datetime import datetime
from typing import AsyncIterator

from core.enums import AssetClass
from core.schemas import Bar
from data.base import AccountState, BracketOrderRequest, BrokerAdapter, OrderResult


class CcxtCryptoAdapter(BrokerAdapter):
    asset_class = AssetClass.CRYPTO

    def __init__(self) -> None:
        self._exchange = None  # TODO: ccxt.<exchange>({...})

    async def get_historical_bars(self, symbol, timeframe, start, end) -> list[Bar]:
        raise NotImplementedError("wire ccxt fetch_ohlcv")

    async def stream_bars(self, symbols) -> AsyncIterator[Bar]:
        if False:  # pragma: no cover
            yield  # type: ignore[misc]
        raise NotImplementedError("wire ccxt.pro watch_ohlcv")

    async def get_account(self) -> AccountState:
        raise NotImplementedError

    async def submit_bracket(self, req: BracketOrderRequest) -> OrderResult:
        raise NotImplementedError

    async def is_shortable(self, symbol: str) -> bool:
        return False  # spot only in phase 4

    async def is_ssr_active(self, symbol: str) -> bool:
        return False  # N/A for crypto

    async def session_is_open(self, symbol: str, at: datetime) -> bool:
        return True  # 24/7
