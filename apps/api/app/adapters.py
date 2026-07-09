from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import AsyncIterable

import ccxt.async_support as ccxt

from .schemas import Candle, MarketKind, MarketSymbol, OrderBookLevel, OrderBookSnapshot, Ticker


class ExchangeAdapter(ABC):
    def __init__(self, market: str, exchange_id: str, is_future: bool = False) -> None:
        self.market = market
        self.exchange_id = exchange_id
        self.is_future = is_future

    @abstractmethod
    async def get_markets(self) -> list[MarketSymbol]:
        raise NotImplementedError

    @abstractmethod
    async def get_tickers(self) -> list[Ticker]:
        raise NotImplementedError

    @abstractmethod
    async def get_candles(self, symbol: str, timeframe: str, limit: int) -> list[Candle]:
        raise NotImplementedError

    @abstractmethod
    async def get_order_book(self, symbol: str, depth: int) -> OrderBookSnapshot:
        raise NotImplementedError

    async def subscribe_tickers(self, symbols: list[str], interval_seconds: float = 5.0) -> AsyncIterable[Ticker]:
        while True:
            all_tickers = await self.get_tickers()
            filtered = [ticker for ticker in all_tickers if ticker.symbol in symbols]
            for ticker in filtered:
                yield ticker
            await asyncio.sleep(interval_seconds)

    async def subscribe_order_book(self, symbols: list[str], interval_seconds: float = 5.0) -> AsyncIterable[OrderBookSnapshot]:
        while True:
            for symbol in symbols:
                yield await self.get_order_book(symbol, depth=20)
            await asyncio.sleep(interval_seconds)


class CcxtExchangeAdapter(ExchangeAdapter):
    def __init__(self, market: str, exchange_id: str, is_future: bool = False) -> None:
        super().__init__(market, exchange_id, is_future)
        exchange_class = getattr(ccxt, exchange_id)
        self.exchange = exchange_class({"enableRateLimit": True})
        if is_future and hasattr(self.exchange, "options"):
            self.exchange.options["defaultType"] = "swap"

    async def get_markets(self) -> list[MarketSymbol]:
        await self.exchange.load_markets()
        markets: list[MarketSymbol] = []
        for symbol, info in self.exchange.markets.items():
            markets.append(
                MarketSymbol(
                    symbol=symbol,
                    market=self.market,
                    exchange=self.exchange_id.upper(),
                    active=bool(info.get("active", True)),
                    base=info.get("base"),
                    quote=info.get("quote"),
                )
            )
        return markets

    async def get_tickers(self) -> list[Ticker]:
        tickers = await self.exchange.fetch_tickers()
        result: list[Ticker] = []
        now = datetime.now(timezone.utc)
        for symbol, item in tickers.items():
            last = item.get("last") or item.get("close") or 0.0
            result.append(
                Ticker(
                    symbol=symbol,
                    market=self.market,
                    exchange=self.exchange_id.upper(),
                    last=last,
                    bid=item.get("bid"),
                    ask=item.get("ask"),
                    quoteVolume=item.get("quoteVolume"),
                    baseVolume=item.get("baseVolume"),
                    priceChangePercent=item.get("percentage"),
                    trades=item.get("trades"),
                    ts=now,
                )
            )
        return result

    async def get_candles(self, symbol: str, timeframe: str, limit: int) -> list[Candle]:
        raw = await self.exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        candles: list[Candle] = []
        for ts, open_, high, low, close, volume in raw:
            candles.append(
                Candle(
                    ts=datetime.fromtimestamp(ts / 1000, tz=timezone.utc),
                    open=open_,
                    high=high,
                    low=low,
                    close=close,
                    volume=volume,
                    trades=None,
                )
            )
        return candles

    async def get_order_book(self, symbol: str, depth: int) -> OrderBookSnapshot:
        raw = await self.exchange.fetch_order_book(symbol, limit=depth)
        now = datetime.now(timezone.utc)
        bids = [OrderBookLevel(price=price, size=size, size_usd=price * size) for price, size in raw.get("bids", [])[:depth]]
        asks = [OrderBookLevel(price=price, size=size, size_usd=price * size) for price, size in raw.get("asks", [])[:depth]]
        return OrderBookSnapshot(symbol=symbol, market=self.market, exchange=self.exchange_id.upper(), ts=now, bids=bids, asks=asks)


def build_adapter(market: str) -> ExchangeAdapter:
    exchange_id = market.lower().split("_")[0]
    is_future = market.endswith("FUTURES")
    if exchange_id == "gate":
        exchange_id = "gateio"
    if exchange_id == "mexc":
        exchange_id = "mexc"
    return CcxtExchangeAdapter(market=market, exchange_id=exchange_id, is_future=is_future)


def market_from_kind(kind: MarketKind) -> str:
    return kind.value

