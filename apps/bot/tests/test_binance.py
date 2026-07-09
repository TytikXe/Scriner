from __future__ import annotations

import asyncio
import time
from typing import Any

from formation_bot.binance import BinanceClient


class DummyBinanceClient(BinanceClient):
    def __init__(self, raw: list[list[Any]]) -> None:
        super().__init__("https://example.com")
        self.raw = raw

    async def _request(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return self.raw


def test_klines_skip_unclosed_current_candle() -> None:
    now_ms = int(time.time() * 1000)
    closed_close_time = now_ms - 60_000
    live_open_time = now_ms - 10_000
    live_close_time = now_ms + 50_000
    client = DummyBinanceClient(
        [
            [closed_close_time - 59_999, "10", "11", "9", "10.5", "100", closed_close_time, "0", 10],
            [live_open_time, "10.5", "12", "10", "11.8", "300", live_close_time, "0", 20],
        ]
    )

    candles = asyncio.run(client.klines("TESTUSDT", "1m", 2))

    assert len(candles) == 1
    assert candles[0].close == 10.5
    assert candles[0].close_time_ms == closed_close_time
