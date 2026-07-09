from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

import pytest

from formation_bot.config import load_settings
from formation_bot.formations import detect_breakout
from formation_bot.models import Candle


REFERENCE_SIGNALS = (
    ("AAVEUSDT", "12:01", 0.50),
    ("UBUSDT", "14:46", 1.50),
    ("LITUSDT", "16:23", 0.70),
    ("REUSDT", "17:07", 0.78),
    ("GLWUSDT", "22:53", 0.54),
)


def _ms(value: datetime) -> int:
    return int(value.timestamp() * 1000)


def _get_json(base_url: str, path: str, params: dict[str, object]):
    url = f"{base_url}{path}?{urllib.parse.urlencode(params)}"
    last_error: Exception | None = None
    for _ in range(4):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "formation-bot-reference-test/1.0"})
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            last_error = exc
            time.sleep(1)
    raise last_error or RuntimeError("Binance request failed")


def _to_candle(item: list[object]) -> Candle:
    return Candle(
        open_time_ms=int(item[0]),
        close_time_ms=int(item[6]),
        open=float(item[1]),
        high=float(item[2]),
        low=float(item[3]),
        close=float(item[4]),
        volume=float(item[5]),
        trades=int(item[8]),
    )


def _fetch_reference_candles(symbol: str, target: datetime) -> list[Candle]:
    settings = load_settings()
    start = target - timedelta(minutes=settings.kline_limit + 20)
    end = target + timedelta(minutes=15)
    raw = _get_json(
        settings.binance_base_url,
        "/fapi/v1/klines",
        {
            "symbol": symbol,
            "interval": "1m",
            "startTime": _ms(start.astimezone(timezone.utc)),
            "endTime": _ms(end.astimezone(timezone.utc)),
            "limit": 1500,
        },
    )
    return [_to_candle(item) for item in raw]


def _detect_reference_hits(symbol: str, target: datetime) -> list[tuple[str, float]]:
    settings = load_settings()
    candles = _fetch_reference_candles(symbol, target)
    indexes = {candle.open_time_ms: index for index, candle in enumerate(candles)}
    hits: list[tuple[str, float]] = []
    current = target - timedelta(minutes=15)
    while current <= target + timedelta(minutes=15):
        latest_open = current.replace(second=0, microsecond=0) - timedelta(minutes=1)
        candle_index = indexes.get(_ms(latest_open.astimezone(timezone.utc)))
        if candle_index is not None:
            signal = detect_breakout(
                symbol=symbol,
                timeframe="1m",
                candles=candles[: candle_index + 1],
                lookback=settings.level_lookback_candles,
                min_touches=settings.zone_confirmation_touches,
                tolerance_pct=settings.level_tolerance_pct,
                zone_atr_multiplier=settings.zone_atr_multiplier,
                cluster_tolerance_natr_k=settings.cluster_tolerance_natr_k,
                breakout_distance_pct=settings.breakout_distance_pct,
                min_breakout_body_ratio=settings.min_breakout_body_ratio,
                min_volume_multiplier=settings.min_volume_multiplier,
                min_probe_volume_multiplier=settings.min_probe_volume_multiplier,
                level_probe_distance_pct=settings.level_probe_distance_pct,
                min_close_atr_multiplier=settings.min_close_atr_multiplier,
                min_close_distance_pct=settings.min_close_distance_pct,
                max_breakout_wick_ratio=settings.max_breakout_wick_ratio,
                max_pre_breakout_range_pct=settings.max_pre_breakout_range_pct,
                level_approach_distance_pct=settings.level_approach_distance_pct,
                level_approach_max_width_pct=settings.level_approach_max_width_pct,
                min_level_approach_gap_atr_multiplier=settings.min_level_approach_gap_atr_multiplier,
                level_min_spacing_candles=settings.level_min_spacing_candles,
                min_level_span_candles=settings.min_level_span_candles,
                min_level_age_candles=settings.min_level_age_candles,
                zone_ttl_candles=settings.zone_ttl_candles,
                min_retreat_atr_multiplier=settings.min_retreat_atr_multiplier,
                impulse_threshold_atr=settings.impulse_threshold_atr,
                impulse_lookback_candles=settings.impulse_lookback_candles,
                min_natr_pct=settings.min_natr_pct,
                natr_period=settings.natr_period,
            )
            if signal:
                hits.append((current.strftime("%H:%M"), signal.natr_pct))
        current += timedelta(minutes=1)
    return hits


@pytest.mark.skipif(
    os.getenv("RUN_BINANCE_REFERENCE_TESTS") != "1",
    reason="Set RUN_BINANCE_REFERENCE_TESTS=1 to run live Binance reference signal checks.",
)
@pytest.mark.parametrize(("symbol", "local_time", "expected_natr"), REFERENCE_SIGNALS)
def test_reference_signal_matches_other_screener_within_fifteen_minutes(
    symbol: str,
    local_time: str,
    expected_natr: float,
) -> None:
    local_tz = timezone(timedelta(hours=3))
    target = datetime.fromisoformat(f"2026-07-01T{local_time}:00").replace(tzinfo=local_tz)

    hits = _detect_reference_hits(symbol, target)

    assert hits
    assert any(abs(natr_pct - expected_natr) <= 0.15 for _, natr_pct in hits), hits
