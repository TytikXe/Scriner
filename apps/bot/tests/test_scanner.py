from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path

from formation_bot.config import Settings
from formation_bot.models import BreakoutSignal, SignalAlert, SymbolInfo
from formation_bot.scanner import FormationScanner


class DummyClient:
    pass


def make_settings(symbol_pause_minutes: int) -> Settings:
    return Settings(
        telegram_bot_token="token",
        db_path=Path("bot.sqlite3"),
        log_level=20,
        binance_base_url="https://example.com",
        scan_interval_seconds=60,
        timeframes=("1m",),
        signal_symbol_allowlist=(),
        max_symbols=0,
        min_quote_volume_24h=0.0,
        kline_limit=260,
        max_concurrent_kline_requests=4,
        level_lookback_candles=220,
        min_level_touches=4,
        level_tolerance_pct=0.14,
        cluster_tolerance_natr_k=0.5,
        zone_atr_multiplier=0.2,
        zone_ttl_candles=360,
        min_retreat_atr_multiplier=3.0,
        impulse_threshold_atr=2.0,
        impulse_lookback_candles=3,
        breakout_distance_pct=0.35,
        min_breakout_body_ratio=0.55,
        min_volume_multiplier=1.8,
        min_probe_volume_multiplier=1.4,
        level_probe_distance_pct=0.25,
        min_close_atr_multiplier=0.12,
        min_close_distance_pct=0.04,
        max_breakout_wick_ratio=0.25,
        max_pre_breakout_range_pct=1.2,
        level_approach_distance_pct=1.5,
        level_approach_max_width_pct=0.85,
        level_approach_min_touches=2,
        min_level_approach_gap_atr_multiplier=0.75,
        level_min_spacing_candles=10,
        min_level_span_candles=50,
        min_level_age_candles=8,
        min_natr_pct=0.3,
        natr_period=14,
        min_unconfirmed_signal_score=100.0,
        min_unconfirmed_signal_touches=4,
        max_signals_per_scan=3,
        max_signal_age_minutes=5,
        symbol_analysis_pause_minutes=symbol_pause_minutes,
        send_unconfirmed_signals=False,
        skip_initial_scan=False,
        alert_cooldown_minutes=240,
    )


def make_signal(
    symbol: str,
    is_breakout_type: bool = False,
    score: float = 90,
    natr_pct: float = 0.0,
    touches: int = 4,
    level_kind: str = "standard",
    signal_type: str | None = None,
    confidence: str = "confirmed",
) -> BreakoutSignal:
    return BreakoutSignal(
        symbol=symbol,
        timeframe="1m",
        side="resistance",
        price=1.0,
        zone_lower=0.99,
        zone_upper=1.0,
        touches=touches,
        score=score,
        detected_at=datetime.now(timezone.utc),
        candle_close_time_ms=int(time.time() * 1000),
        is_breakout_type=is_breakout_type,
        natr_pct=natr_pct,
        level_kind=level_kind,
        signal_type=signal_type or ("breakout" if is_breakout_type else "test"),
        confidence=confidence,
    )


def make_alert(
    symbol: str,
    is_breakout_type: bool = False,
    score: float = 90,
    natr_pct: float = 0.0,
    touches: int = 4,
    level_kind: str = "standard",
    signal_type: str | None = None,
    confidence: str = "confirmed",
) -> SignalAlert:
    signal = make_signal(
        symbol,
        is_breakout_type=is_breakout_type,
        score=score,
        natr_pct=natr_pct,
        touches=touches,
        level_kind=level_kind,
        signal_type=signal_type,
        confidence=confidence,
    )
    return SignalAlert(signal=signal, message="message")


def test_signal_key_is_paused_from_future_scans() -> None:
    scanner = FormationScanner(DummyClient(), make_settings(symbol_pause_minutes=15))  # type: ignore[arg-type]
    paused = make_alert("AAAUSDT", is_breakout_type=False)
    same_key = make_alert("AAAUSDT", is_breakout_type=False)
    same_symbol_other_key = make_alert("AAAUSDT", is_breakout_type=True)

    scanner._pause_signal_keys([paused])

    assert scanner._filter_paused_signals([same_key, same_symbol_other_key]) == [same_symbol_other_key]


def test_expired_signal_key_pause_is_removed() -> None:
    scanner = FormationScanner(DummyClient(), make_settings(symbol_pause_minutes=15))  # type: ignore[arg-type]
    alert = make_alert("AAAUSDT")
    scanner._signal_key_paused_until[alert.signal.key] = time.time() - 1

    assert scanner._filter_paused_signals([alert]) == [alert]
    assert alert.signal.key not in scanner._signal_key_paused_until


def test_signal_symbol_allowlist_filters_symbols_after_volume_filter() -> None:
    settings = make_settings(symbol_pause_minutes=15)
    settings = Settings(**{**settings.__dict__, "signal_symbol_allowlist": ("AAAUSDT", "CCCUSDT")})
    scanner = FormationScanner(DummyClient(), settings)  # type: ignore[arg-type]
    symbols = [SymbolInfo("AAAUSDT", 0.01, 100), SymbolInfo("BBBUSDT", 0.01, 100)]

    assert scanner._filter_allowed_symbols(symbols) == [symbols[0]]


def test_higher_timeframes_are_scanned_within_signal_age_window() -> None:
    settings = make_settings(symbol_pause_minutes=15)
    settings = Settings(**{**settings.__dict__, "timeframes": ("1h",), "max_signal_age_minutes": 5})
    scanner = FormationScanner(DummyClient(), settings)  # type: ignore[arg-type]

    assert scanner._timeframe_scan_seconds("1h") == 5 * 60


def test_low_confidence_signals_are_skipped_by_default() -> None:
    scanner = FormationScanner(DummyClient(), make_settings(symbol_pause_minutes=15))  # type: ignore[arg-type]
    confirmed_confidence = make_alert("AAAUSDT", is_breakout_type=True, confidence="confirmed")
    low_confidence = make_alert("BBBUSDT", is_breakout_type=False, confidence="low_confidence")

    assert scanner._filter_allowed_signals([confirmed_confidence, low_confidence]) == [confirmed_confidence]


def test_confirmed_confidence_tests_do_not_require_unconfirmed_score() -> None:
    settings = make_settings(symbol_pause_minutes=15)
    settings = Settings(**{**settings.__dict__, "send_unconfirmed_signals": True})
    scanner = FormationScanner(DummyClient(), settings)  # type: ignore[arg-type]
    confirmed_test = make_alert(
        "BBBUSDT",
        is_breakout_type=False,
        score=50,
        touches=2,
        signal_type="test",
        confidence="confirmed",
    )

    assert scanner._filter_allowed_signals([confirmed_test]) == [confirmed_test]


def test_low_confidence_signals_are_skipped_when_enabled_below_threshold() -> None:
    settings = make_settings(symbol_pause_minutes=15)
    settings = Settings(**{**settings.__dict__, "send_unconfirmed_signals": True})
    scanner = FormationScanner(DummyClient(), settings)  # type: ignore[arg-type]
    low_touch = make_alert("BBBUSDT", is_breakout_type=False, score=99, touches=1, confidence="low_confidence")

    assert scanner._filter_allowed_signals([low_touch]) == []


def test_low_confidence_tests_can_be_sent_when_enabled() -> None:
    settings = make_settings(symbol_pause_minutes=15)
    settings = Settings(**{**settings.__dict__, "send_unconfirmed_signals": True, "min_unconfirmed_signal_score": 60.0})
    scanner = FormationScanner(DummyClient(), settings)  # type: ignore[arg-type]
    early = make_alert(
        "BBBUSDT",
        is_breakout_type=False,
        score=62,
        touches=1,
        signal_type="test",
        confidence="low_confidence",
    )

    assert scanner._filter_allowed_signals([early]) == [early]


def test_global_extreme_unconfirmed_signals_can_use_two_touches() -> None:
    settings = make_settings(symbol_pause_minutes=15)
    settings = Settings(**{**settings.__dict__, "send_unconfirmed_signals": True})
    scanner = FormationScanner(DummyClient(), settings)  # type: ignore[arg-type]
    signal = make_alert(
        "BBBUSDT",
        is_breakout_type=False,
        score=100,
        touches=2,
        level_kind="global_extreme",
        confidence="low_confidence",
    )

    assert scanner._filter_allowed_signals([signal]) == [signal]


def test_compression_unconfirmed_signals_can_use_three_touches() -> None:
    settings = make_settings(symbol_pause_minutes=15)
    settings = Settings(**{**settings.__dict__, "send_unconfirmed_signals": True})
    scanner = FormationScanner(DummyClient(), settings)  # type: ignore[arg-type]
    signal = make_alert(
        "BBBUSDT",
        is_breakout_type=False,
        score=100,
        touches=3,
        level_kind="compression",
        confidence="low_confidence",
    )

    assert scanner._filter_allowed_signals([signal]) == [signal]


def test_impulse_approach_unconfirmed_signals_can_use_two_touches() -> None:
    settings = make_settings(symbol_pause_minutes=15)
    settings = Settings(**{**settings.__dict__, "send_unconfirmed_signals": True})
    scanner = FormationScanner(DummyClient(), settings)  # type: ignore[arg-type]
    signal = make_alert(
        "BBBUSDT",
        is_breakout_type=False,
        score=100,
        touches=2,
        level_kind="impulse_approach",
        confidence="low_confidence",
    )

    assert scanner._filter_allowed_signals([signal]) == [signal]


def test_weak_unconfirmed_signals_are_skipped_when_enabled() -> None:
    settings = make_settings(symbol_pause_minutes=15)
    settings = Settings(**{**settings.__dict__, "send_unconfirmed_signals": True})
    scanner = FormationScanner(DummyClient(), settings)  # type: ignore[arg-type]
    weak = make_alert("BBBUSDT", is_breakout_type=False, score=99, touches=4, confidence="low_confidence")
    strong = make_alert("CCCUSDT", is_breakout_type=False, score=100, touches=4, confidence="low_confidence")

    assert scanner._filter_allowed_signals([weak, strong]) == [strong]


def test_batch_sort_uses_score_without_breakout_or_natr_priority() -> None:
    scanner = FormationScanner(DummyClient(), make_settings(symbol_pause_minutes=15))  # type: ignore[arg-type]
    lower_score_breakout = make_alert("AAAUSDT", is_breakout_type=True, score=70, natr_pct=5.0)
    higher_score_test = make_alert("BBBUSDT", is_breakout_type=False, score=90, natr_pct=1.0)

    assert scanner._sort_signals_for_batch([lower_score_breakout, higher_score_test]) == [
        higher_score_test,
        lower_score_breakout,
    ]


def test_alert_cooldown_key_includes_zone_timeframe_side_and_state() -> None:
    assert make_signal("AAAUSDT").key == "AAAUSDT:1m:resistance:0.99-1:test:confirmed"
    assert make_signal("AAAUSDT", is_breakout_type=True).key == "AAAUSDT:1m:resistance:0.99-1:breakout:confirmed"
