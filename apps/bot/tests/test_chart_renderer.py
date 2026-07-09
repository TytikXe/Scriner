from __future__ import annotations

import time
from datetime import datetime, timezone

from formation_bot.chart_renderer import render_signal_chart
from formation_bot.models import BreakoutSignal, Candle


def candle(index: int, open_: float, high: float, low: float, close: float, volume: float = 1000) -> Candle:
    return Candle(
        open_time_ms=index * 60_000,
        close_time_ms=(index + 1) * 60_000 - 1,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
        trades=100,
    )


def test_render_signal_chart_returns_png() -> None:
    candles = [
        candle(index, 99 + index * 0.02, 100 + index * 0.02, 98.8 + index * 0.02, 99.2 + index * 0.02)
        for index in range(80)
    ]
    signal = BreakoutSignal(
        symbol="TESTUSDT",
        timeframe="1m",
        side="resistance",
        price=100.8,
        zone_lower=100.6,
        zone_upper=100.6,
        touches=1,
        score=100.0,
        detected_at=datetime.now(timezone.utc),
        candle_close_time_ms=int(time.time() * 1000),
        is_breakout_type=False,
        natr_pct=0.72,
    )

    image = render_signal_chart(candles, signal, tick_size=0.01)

    assert image.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(image) > 10_000


def test_render_signal_chart_handles_many_candles() -> None:
    candles = [
        candle(index, 99 + index * 0.003, 100 + index * 0.003, 98.8 + index * 0.003, 99.2 + index * 0.003)
        for index in range(360)
    ]
    signal = BreakoutSignal(
        symbol="TESTUSDT",
        timeframe="1m",
        side="resistance",
        price=100.8,
        zone_lower=100.6,
        zone_upper=100.6,
        touches=1,
        score=100.0,
        detected_at=datetime.now(timezone.utc),
        candle_close_time_ms=int(time.time() * 1000),
        is_breakout_type=False,
        natr_pct=0.72,
        pivot_points=((310, 100.6),),
    )

    image = render_signal_chart(candles, signal, tick_size=0.01)

    assert image.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(image) > 10_000
