from __future__ import annotations

from datetime import datetime, timezone

import pytest

from formation_bot.formations import detect_breakout, find_zones, format_price, format_signal_message, normalized_average_true_range
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


def resistance_breakout_fixture() -> list[Candle]:
    candles: list[Candle] = []
    for index in range(90):
        open_ = 99.0 + (0.08 if index % 2 else -0.08)
        high = 100.0 if index in {20, 45, 70} else 99.35
        low = 98.65
        close = 99.1 if index % 2 else 98.9
        candles.append(candle(index, open_, high, low, close))
    candles.append(candle(90, 99.1, 99.4, 98.9, 99.2))
    candles.append(candle(91, 99.2, 100.6, 99.15, 100.32, volume=1800))
    return candles


def test_detects_confirmed_zone_breakout_with_multiple_touches() -> None:
    signal = detect_breakout(
        "TESTUSDT",
        "1m",
        resistance_breakout_fixture(),
        lookback=90,
        min_touches=3,
        tolerance_pct=0.02,
        zone_atr_multiplier=0.0,
        breakout_distance_pct=0.5,
        min_breakout_body_ratio=0.45,
        min_volume_multiplier=1.2,
        level_min_spacing_candles=8,
        min_retreat_atr_multiplier=1.0,
        min_natr_pct=0.3,
    )

    assert signal is not None
    assert signal.signal_type == "breakout"
    assert signal.is_breakout_type
    assert signal.confidence == "confirmed"
    assert signal.touches == 3
    assert signal.pivot_points == ((20, 100.0), (45, 100.0), (70, 100.0))


def test_single_touch_breakout_is_rejected_by_min_touches() -> None:
    records: list[dict[str, object]] = []
    candles: list[Candle] = []
    for index in range(90):
        high = 100.0 if index == 40 else 99.35
        candles.append(candle(index, 99.0, high, 98.65, 99.0))
    candles.append(candle(90, 99.1, 99.4, 98.9, 99.2))
    candles.append(candle(91, 99.2, 100.6, 99.15, 100.32, volume=1800))

    signal = detect_breakout(
        "TESTUSDT",
        "1m",
        candles,
        lookback=90,
        min_touches=2,
        tolerance_pct=0.02,
        zone_atr_multiplier=0.0,
        breakout_distance_pct=0.5,
        min_breakout_body_ratio=0.45,
        min_volume_multiplier=1.2,
        level_min_spacing_candles=8,
        min_retreat_atr_multiplier=1.0,
        decision_logger=records.append,
    )

    assert signal is None
    assert any(record["rejection_reason"] == "min_touches_not_reached" for record in records)


def test_live_edge_adds_recent_touch_without_right_fractal_confirmation() -> None:
    candles: list[Candle] = []
    for index in range(90):
        high = 100.0 if index == 40 else 99.35
        low = 98.35 if 60 <= index <= 70 else 98.65
        if index == 88:
            high = 100.05
        close = 99.0
        candles.append(candle(index, 99.0, high, low, close))
    candles.append(candle(90, 99.2, 100.04, 99.0, 99.88, volume=1800))

    signal = detect_breakout(
        "OPGUSDT",
        "5m",
        candles,
        lookback=90,
        min_touches=2,
        tolerance_pct=0.02,
        zone_atr_multiplier=0.0,
        breakout_distance_pct=0.5,
        min_breakout_body_ratio=0.45,
        min_volume_multiplier=1.2,
        level_min_spacing_candles=8,
        fractal_n=4,
        live_window=10,
        min_retreat_atr_multiplier=1.0,
        level_probe_distance_pct=0.3,
    )

    assert signal is not None
    assert signal.timeframe == "5m"
    assert signal.signal_type == "test"
    assert signal.confidence == "confirmed"
    assert signal.touches == 2
    assert (88, 100.05) in signal.pivot_points


def test_impulse_threshold_changes_score_but_does_not_reject_zone() -> None:
    base_kwargs = dict(
        symbol="TESTUSDT",
        timeframe="1m",
        candles=resistance_breakout_fixture(),
        lookback=90,
        min_touches=3,
        tolerance_pct=0.02,
        zone_atr_multiplier=0.0,
        breakout_distance_pct=0.5,
        min_breakout_body_ratio=0.45,
        min_volume_multiplier=1.2,
        level_min_spacing_candles=8,
        min_retreat_atr_multiplier=1.0,
        min_natr_pct=0.3,
    )

    with_impulse_bonus = detect_breakout(**base_kwargs, impulse_threshold_atr=0.5)
    without_impulse_bonus = detect_breakout(**base_kwargs, impulse_threshold_atr=999.0)

    assert with_impulse_bonus is not None
    assert without_impulse_bonus is not None
    assert without_impulse_bonus.signal_type == "breakout"
    assert without_impulse_bonus.score < with_impulse_bonus.score


def test_find_zones_marks_confirmed_and_low_confidence_clusters() -> None:
    candles: list[Candle] = []
    for index in range(120):
        high = 100.0 if index in {30, 70} else 99.35
        low = 97.0 if index == 45 else 98.65
        candles.append(candle(index, 99.0, high, low, 99.0))

    zones = find_zones(
        candles,
        lookback=110,
        min_touches=2,
        tolerance_pct=0.02,
        zone_atr_multiplier=0.0,
        cluster_tolerance_natr_k=0.75,
        level_min_spacing_candles=8,
    )

    assert any(zone.side == "resistance" and zone.touches == 2 and zone.confidence == "confirmed" for zone in zones)
    assert any(zone.side == "support" and zone.touches == 1 and zone.confidence == "low_confidence" for zone in zones)


def test_zone_ttl_rejects_stale_zone() -> None:
    signal = detect_breakout(
        "TESTUSDT",
        "1m",
        resistance_breakout_fixture(),
        lookback=90,
        min_touches=3,
        tolerance_pct=0.02,
        zone_atr_multiplier=0.0,
        breakout_distance_pct=0.5,
        min_breakout_body_ratio=0.45,
        min_volume_multiplier=1.2,
        level_min_spacing_candles=8,
        zone_ttl_candles=10,
        min_retreat_atr_multiplier=1.0,
        live_window=0,
    )

    assert signal is None


def test_min_retreat_rejects_zone_before_price_moves_away() -> None:
    records: list[dict[str, object]] = []

    signal = detect_breakout(
        "TESTUSDT",
        "1m",
        resistance_breakout_fixture(),
        lookback=90,
        min_touches=3,
        tolerance_pct=0.02,
        zone_atr_multiplier=0.0,
        breakout_distance_pct=0.5,
        min_breakout_body_ratio=0.45,
        min_volume_multiplier=1.2,
        level_min_spacing_candles=8,
        min_retreat_atr_multiplier=100.0,
        decision_logger=records.append,
    )

    assert signal is None
    assert any(record["rejection_reason"] == "min_retreat_not_reached" for record in records)


def test_liquidity_filter_rejects_signal_and_logs_reason() -> None:
    records: list[dict[str, object]] = []

    signal = detect_breakout(
        "TESTUSDT",
        "1m",
        resistance_breakout_fixture(),
        lookback=90,
        min_touches=3,
        tolerance_pct=0.02,
        zone_atr_multiplier=0.0,
        breakout_distance_pct=0.5,
        min_breakout_body_ratio=0.45,
        min_volume_multiplier=1.2,
        level_min_spacing_candles=8,
        min_retreat_atr_multiplier=1.0,
        volume_24h_usd=1_000_000,
        min_24h_volume_usd=5_000_000,
        decision_logger=records.append,
    )

    assert signal is None
    assert any(record["rejection_reason"] == "liquidity_below_minimum" for record in records)


def test_debug_trace_is_emitted_for_published_candidate() -> None:
    records: list[dict[str, object]] = []

    signal = detect_breakout(
        "TESTUSDT",
        "1m",
        resistance_breakout_fixture(),
        lookback=90,
        min_touches=3,
        tolerance_pct=0.02,
        zone_atr_multiplier=0.0,
        breakout_distance_pct=0.5,
        min_breakout_body_ratio=0.45,
        min_volume_multiplier=1.2,
        level_min_spacing_candles=8,
        min_retreat_atr_multiplier=1.0,
        decision_logger=records.append,
    )

    assert signal is not None
    published = [record for record in records if str(record["final_decision"]).startswith("published")]
    assert published
    assert published[0]["candidate_zone"]["touches_count"] == 3  # type: ignore[index]
    assert published[0]["checks"]["min_touches"]["passed"] is True  # type: ignore[index]


def test_max_publish_distance_rejects_far_breakout_after_classification() -> None:
    records: list[dict[str, object]] = []

    signal = detect_breakout(
        "TESTUSDT",
        "1m",
        resistance_breakout_fixture(),
        lookback=90,
        min_touches=3,
        tolerance_pct=0.02,
        zone_atr_multiplier=0.0,
        breakout_distance_pct=0.5,
        min_breakout_body_ratio=0.45,
        min_volume_multiplier=1.2,
        level_min_spacing_candles=8,
        min_retreat_atr_multiplier=1.0,
        max_publish_distance_natr=0.1,
        decision_logger=records.append,
    )

    assert signal is None
    rejected = [record for record in records if record["rejection_reason"] == "max_publish_distance_exceeded"]
    assert rejected
    assert rejected[0]["checks"]["signal_type"]["value"] == "breakout"  # type: ignore[index]
    assert rejected[0]["checks"]["max_publish_distance"]["passed"] is False  # type: ignore[index]


def test_natr_uses_standard_atr_percent() -> None:
    candles = [candle(0, 100.0, 101.0, 99.0, 100.0)]
    for index in range(1, 15):
        candles.append(candle(index, 100.0, 101.0, 99.0, 100.0))

    assert normalized_average_true_range(candles, 14) == 2.0


def test_format_signal_message_includes_required_metadata() -> None:
    signal = BreakoutSignal(
        symbol="SOLUSDT",
        timeframe="15m",
        side="support",
        price=83.9,
        zone_lower=83.75,
        zone_upper=83.96,
        touches=2,
        score=77.4,
        detected_at=datetime.now(timezone.utc),
        candle_close_time_ms=1,
        is_breakout_type=False,
        natr_pct=0.8,
        funding_rate_pct=0.0123,
        price_change_24h_pct=-2.5,
        quote_volume_24h=93_200_000,
        trades_24h=12345,
        btc_correlation_1h=0.42,
        signal_type="test",
        confidence="confirmed",
    )

    message = format_signal_message(signal, 0.01)

    assert "SOLUSDT" in message
    assert "Signal: test" in message
    assert "Confidence: confirmed" in message
    assert "Touches: 2" in message
    assert "Funding:" in message
    assert "BTC corr 1ч: 0.42" in message


REFERENCE_SIGNAL_CASES = (
    ("YFIUSDT", "1m", "breakout", 2402.0, 2414.0),
    ("MSTRUSDT", "1m", "breakout", 102.32, 102.62),
    ("REUSDT", "1m", "breakout", 0.6958, 0.6970),
    ("SPCXUSDT", "1h", "breakout", 146.87, 148.17),
    ("KORUUSDT", "1m", "breakout", 565.77, 568.47),
    ("SOLUSDT", "15m", "test", 83.75, 83.96),
    ("OPGUSDT", "5m", "breakout", 0.1215, 0.1221),
    ("MUUSDT", "5m", "breakout", 947.75, 950.49),
)


def reference_zone_candles(lower: float, upper: float, signal_type: str) -> list[Candle]:
    mid = (lower + upper) / 2
    spread = max(upper - lower, mid * 0.003)
    candles: list[Candle] = []
    for index in range(180):
        open_ = mid - spread * 2.8
        high = mid - spread * 2.0
        low = mid - spread * 4.0
        close = mid - spread * 3.0
        if index == 45:
            high = upper
            close = mid - spread * 1.5
        elif index == 110:
            high = lower
            close = mid - spread * 1.4
        elif 130 <= index <= 165:
            open_ = mid - spread * 5.0
            high = mid - spread * 3.0
            low = mid - spread * 6.0
            close = mid - spread * 4.5
        elif 166 <= index <= 179:
            open_ = mid - spread * 2.2
            high = mid - spread * 1.2
            low = mid - spread * 3.0
            close = mid - spread * 1.8
        candles.append(candle(index, open_, high, low, close))

    if signal_type == "breakout":
        candles.append(candle(180, upper * 0.999, upper * 1.004, upper * 0.998, upper * 1.002, volume=2000))
    else:
        candles.append(candle(180, lower * 0.999, upper, lower * 0.999, mid, volume=2000))
    return candles


@pytest.mark.parametrize(("symbol", "timeframe", "expected_type", "lower", "upper"), REFERENCE_SIGNAL_CASES)
def test_section_9_reference_cases_are_representable_by_zone_pipeline(
    symbol: str,
    timeframe: str,
    expected_type: str,
    lower: float,
    upper: float,
) -> None:
    signal = detect_breakout(
        symbol,
        timeframe,
        reference_zone_candles(lower, upper, expected_type),
        lookback=180,
        min_touches=2,
        tolerance_pct=1.5,
        zone_atr_multiplier=0.0,
        breakout_distance_pct=1.0,
        min_breakout_body_ratio=0.0,
        min_volume_multiplier=1.0,
        level_min_spacing_candles=8,
        min_retreat_atr_multiplier=0.0,
        level_probe_distance_pct=1.0,
        fractal_n=2,
        live_window=0,
    )

    assert signal is not None
    assert signal.symbol == symbol
    assert signal.timeframe == timeframe
    assert signal.signal_type == expected_type
    assert signal.confidence == "confirmed"
    assert signal.touches == 2


@pytest.mark.parametrize("symbol", ("OPGUSDT", "XLMUSDT", "ADAUSDT", "TACUSDT"))
def test_section_9_old_single_touch_cases_are_rejected_by_min_touches(symbol: str) -> None:
    records: list[dict[str, object]] = []
    candles: list[Candle] = []
    for index in range(120):
        low = 0.19 if index == 50 else 0.20
        candles.append(candle(index, 0.205, 0.21, low, 0.205))
    candles.append(candle(120, 0.202, 0.203, 0.188, 0.189, volume=2000))

    signal = detect_breakout(
        symbol,
        "1m",
        candles,
        lookback=120,
        min_touches=2,
        tolerance_pct=0.5,
        zone_atr_multiplier=0.0,
        breakout_distance_pct=1.0,
        min_breakout_body_ratio=0.0,
        min_volume_multiplier=1.0,
        level_min_spacing_candles=8,
        min_retreat_atr_multiplier=0.0,
        level_probe_distance_pct=1.0,
        fractal_n=2,
        live_window=0,
        decision_logger=records.append,
    )

    assert signal is None
    assert any(record["rejection_reason"] == "min_touches_not_reached" for record in records)


def test_format_price_uses_tick_size() -> None:
    assert format_price(0.001199, 0.000001) == "0.001199"
    assert format_price(193.9100, 0.01) == "193.91"
