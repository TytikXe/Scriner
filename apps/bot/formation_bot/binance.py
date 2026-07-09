from __future__ import annotations

import asyncio
import logging
import socket
import time
from typing import Any

import aiohttp

from .models import Candle, SymbolInfo


logger = logging.getLogger(__name__)


class BinanceClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url
        self._session: aiohttp.ClientSession | None = None
        self._symbols_cache: tuple[float, list[SymbolInfo]] | None = None

    async def __aenter__(self) -> "BinanceClient":
        timeout = aiohttp.ClientTimeout(total=20)
        connector = aiohttp.TCPConnector(
            family=socket.AF_INET,
            resolver=aiohttp.ThreadedResolver(),
        )
        self._session = aiohttp.ClientSession(timeout=timeout, connector=connector)
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._session:
            await self._session.close()

    async def _request(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if not self._session:
            raise RuntimeError("BinanceClient session is not initialized")
        url = f"{self.base_url}{path}"
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                async with self._session.get(url, params=params) as response:
                    if response.status in {418, 429}:
                        retry_after = int(response.headers.get("Retry-After", "2"))
                        logger.warning("Binance rate limit response: status=%s", response.status)
                        await asyncio.sleep(min(retry_after, 10))
                        continue
                    if response.status >= 400:
                        body = await response.text()
                        raise RuntimeError(f"Binance HTTP {response.status}: {body[:160]}")
                    return await response.json()
            except (aiohttp.ClientError, asyncio.TimeoutError, RuntimeError) as exc:
                last_error = exc
                logger.warning("Binance request failed: path=%s attempt=%s error=%s", path, attempt + 1, exc)
                await asyncio.sleep(0.7 * (attempt + 1))
        raise last_error or RuntimeError("Binance request failed")

    async def futures_symbols(self, max_symbols: int, min_quote_volume_24h: float = 0.0) -> list[SymbolInfo]:
        now = time.time()
        if self._symbols_cache and self._symbols_cache[0] > now:
            symbols = self._symbols_cache[1]
            filtered = [item for item in symbols if item.quote_volume >= min_quote_volume_24h]
            return filtered[:max_symbols] if max_symbols else filtered

        exchange_info_task = asyncio.create_task(self._request("/fapi/v1/exchangeInfo"))
        ticker_task = asyncio.create_task(self._request("/fapi/v1/ticker/24hr"))
        exchange_info, tickers = await asyncio.gather(exchange_info_task, ticker_task)

        volume_by_symbol = {
            str(item.get("symbol")): float(item.get("quoteVolume") or 0)
            for item in tickers
            if isinstance(item, dict)
        }
        price_change_by_symbol = {
            str(item.get("symbol")): float(item.get("priceChangePercent") or 0)
            for item in tickers
            if isinstance(item, dict)
        }
        trades_by_symbol = {
            str(item.get("symbol")): int(item.get("count") or 0)
            for item in tickers
            if isinstance(item, dict)
        }
        result: list[SymbolInfo] = []
        for item in exchange_info.get("symbols", []):
            if item.get("contractType") not in {"PERPETUAL", "TRADIFI_PERPETUAL"}:
                continue
            if item.get("quoteAsset") != "USDT":
                continue
            if item.get("status") != "TRADING":
                continue
            symbol = str(item.get("symbol"))
            tick_size = 0.0
            for filter_item in item.get("filters", []):
                if filter_item.get("filterType") == "PRICE_FILTER":
                    tick_size = float(filter_item.get("tickSize") or 0)
                    break
            result.append(
                SymbolInfo(
                    symbol=symbol,
                    tick_size=tick_size or 0.00000001,
                    quote_volume=volume_by_symbol.get(symbol, 0.0),
                    price_change_percent=price_change_by_symbol.get(symbol),
                    trades_24h=trades_by_symbol.get(symbol),
                )
            )

        result.sort(key=lambda item: item.quote_volume, reverse=True)
        self._symbols_cache = (now + 15 * 60, result)
        filtered = [item for item in result if item.quote_volume >= min_quote_volume_24h]
        logger.info(
            "Loaded Binance Futures symbols: count=%s liquid_count=%s min_quote_volume_24h=%.0f",
            len(result),
            len(filtered),
            min_quote_volume_24h,
        )
        return filtered[:max_symbols] if max_symbols else filtered

    async def funding_rate_pct(self, symbol: str) -> float | None:
        raw = await self._request("/fapi/v1/premiumIndex", {"symbol": symbol})
        if not isinstance(raw, dict):
            return None
        value = raw.get("lastFundingRate")
        if value is None:
            return None
        return float(value) * 100

    async def klines(self, symbol: str, timeframe: str, limit: int) -> list[Candle]:
        raw = await self._request(
            "/fapi/v1/klines",
            {"symbol": symbol, "interval": timeframe, "limit": limit},
        )
        now_ms = int(time.time() * 1000)
        candles: list[Candle] = []
        for item in raw:
            open_time_ms = int(item[0])
            if open_time_ms > now_ms:
                continue
            close_time_ms = int(item[6])
            if close_time_ms > now_ms:
                continue
            candles.append(
                Candle(
                    open_time_ms=open_time_ms,
                    open=float(item[1]),
                    high=float(item[2]),
                    low=float(item[3]),
                    close=float(item[4]),
                    volume=float(item[5]),
                    close_time_ms=close_time_ms,
                    trades=int(item[8]),
                )
            )
        return candles
