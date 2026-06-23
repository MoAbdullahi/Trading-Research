"""US-equities adapter backed by alpaca-py."""
from __future__ import annotations

from datetime import datetime
from typing import AsyncIterator

from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.data.enums import DataFeed
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetAssetsRequest, MarketOrderRequest
from alpaca.trading.enums import AssetClass as AlpacaAssetClass, OrderSide, TimeInForce as AlpacaTIF

from core.enums import AssetClass, OrderType, Side, TimeInForce
from core.schemas import Bar
from core.settings import get_settings
from data.base import AccountState, BracketOrderRequest, BrokerAdapter, OrderResult


def _parse_timeframe(tf: str) -> TimeFrame:
    mapping = {
        "1Min": TimeFrame(1, TimeFrameUnit.Minute),
        "5Min": TimeFrame(5, TimeFrameUnit.Minute),
        "15Min": TimeFrame(15, TimeFrameUnit.Minute),
        "1Hour": TimeFrame(1, TimeFrameUnit.Hour),
        "1Day": TimeFrame(1, TimeFrameUnit.Day),
    }
    return mapping.get(tf, TimeFrame(1, TimeFrameUnit.Minute))


class AlpacaEquityAdapter(BrokerAdapter):
    asset_class = AssetClass.EQUITY

    def __init__(self) -> None:
        s = get_settings()
        self._key = s.alpaca_api_key
        self._secret = s.alpaca_secret_key
        self._paper = s.alpaca_use_paper
        self._trading = TradingClient(
            api_key=self._key,
            secret_key=self._secret,
            paper=self._paper,
        )
        self._data = StockHistoricalDataClient(
            api_key=self._key,
            secret_key=self._secret,
        )

    # ----------------------------- data ----------------------------------- #

    async def get_historical_bars(
        self, symbol: str, timeframe: str, start: datetime, end: datetime
    ) -> list[Bar]:
        req = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=_parse_timeframe(timeframe),
            start=start,
            end=end,
            feed=DataFeed.IEX,
        )
        bars_resp = self._data.get_stock_bars(req)
        bars = bars_resp.data.get(symbol, [])
        return [
            Bar(
                symbol=symbol,
                asset_class=AssetClass.EQUITY,
                ts=b.timestamp,
                open=float(b.open),
                high=float(b.high),
                low=float(b.low),
                close=float(b.close),
                volume=float(b.volume),
            )
            for b in bars
        ]

    async def stream_bars(self, symbols: list[str]) -> AsyncIterator[Bar]:
        if False:  # pragma: no cover
            yield  # type: ignore[misc]
        raise NotImplementedError("wire alpaca-py StockDataStream")

    # --------------------------- account/exec ------------------------------ #

    async def get_account(self) -> AccountState:
        acct = self._trading.get_account()
        positions = self._trading.get_all_positions()
        open_value = sum(float(p.market_value) for p in positions if p.market_value)
        return AccountState(
            equity=float(acct.equity),
            cash=float(acct.cash),
            buying_power=float(acct.buying_power),
            is_pattern_day_trader=acct.pattern_day_trader,
            day_trade_count_5d=int(acct.daytrade_count),
            open_positions_value=open_value,
        )

    async def submit_bracket(self, req: BracketOrderRequest) -> OrderResult:
        side = OrderSide.BUY if req.side is Side.LONG else OrderSide.SELL
        tif = AlpacaTIF.DAY if req.tif is TimeInForce.DAY else AlpacaTIF.GTC
        try:
            order = self._trading.submit_order(
                MarketOrderRequest(
                    symbol=req.symbol,
                    qty=req.qty,
                    side=side,
                    time_in_force=tif,
                )
            )
            return OrderResult(accepted=True, broker_order_id=str(order.id))
        except Exception as exc:
            return OrderResult(accepted=False, broker_order_id=None, message=str(exc))

    async def is_shortable(self, symbol: str) -> bool:
        asset = self._trading.get_asset(symbol)
        return bool(asset.shortable)

    async def is_ssr_active(self, symbol: str) -> bool:
        return False

    async def session_is_open(self, symbol: str, at: datetime) -> bool:
        clock = self._trading.get_clock()
        return bool(clock.is_open)
