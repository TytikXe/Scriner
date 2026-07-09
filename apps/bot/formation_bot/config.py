from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[1]
load_dotenv(ROOT_DIR / ".env", encoding="utf-8-sig")


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _timeframes_env() -> tuple[str, ...]:
    raw = os.getenv("SCAN_TIMEFRAMES", "1m,5m,15m,1h")
    values = tuple(item.strip() for item in raw.split(",") if item.strip())
    if not values:
        raise ValueError("SCAN_TIMEFRAMES must contain at least one timeframe")
    return values


def _symbols_env(name: str) -> tuple[str, ...]:
    raw = os.getenv(name, "")
    return tuple(dict.fromkeys(item.strip().upper() for item in raw.split(",") if item.strip()))


def _bars_by_timeframe_env(name: str, default: dict[str, int]) -> dict[str, int]:
    raw = os.getenv(name, "")
    if not raw.strip():
        return dict(default)
    result = dict(default)
    for item in raw.split(","):
        if not item.strip():
            continue
        if ":" not in item:
            raise ValueError(f"{name} items must use timeframe:bars format")
        timeframe, value = (part.strip() for part in item.split(":", 1))
        if not timeframe:
            raise ValueError(f"{name} contains an empty timeframe")
        try:
            result[timeframe] = max(0, int(value))
        except ValueError as exc:
            raise ValueError(f"{name} bars for {timeframe} must be an integer") from exc
    return result


def _score_weights_env() -> dict[str, float]:
    defaults = {
        "w_touches": 0.25,
        "w_tightness": 0.20,
        "w_impulse": 0.15,
        "w_volume_touch": 0.15,
        "w_recency": 0.10,
        "w_liquidity": 0.15,
    }
    raw = os.getenv("SCORE_WEIGHTS", "")
    if not raw.strip():
        return defaults
    result = dict(defaults)
    for item in raw.split(","):
        if not item.strip():
            continue
        if ":" not in item:
            raise ValueError("SCORE_WEIGHTS items must use name:value format")
        key, value = (part.strip() for part in item.split(":", 1))
        if key not in result:
            raise ValueError(f"Unknown SCORE_WEIGHTS key: {key}")
        try:
            result[key] = max(0.0, float(value))
        except ValueError as exc:
            raise ValueError(f"SCORE_WEIGHTS value for {key} must be a number") from exc
    return result


def _unconfirmed_touches_by_level_kind_env() -> dict[str, int]:
    defaults = {
        "early_single_touch": 1,
        "live_edge": 1,
        "global_extreme": 2,
        "compression": 3,
        "impulse_approach": 2,
    }
    raw = os.getenv("UNCONFIRMED_TOUCHES_BY_LEVEL_KIND", "")
    if not raw.strip():
        return defaults
    result = dict(defaults)
    for item in raw.split(","):
        if not item.strip():
            continue
        if ":" not in item:
            raise ValueError("UNCONFIRMED_TOUCHES_BY_LEVEL_KIND items must use level_kind:touches format")
        level_kind, value = (part.strip() for part in item.split(":", 1))
        if not level_kind:
            raise ValueError("UNCONFIRMED_TOUCHES_BY_LEVEL_KIND contains an empty level kind")
        try:
            result[level_kind] = max(1, int(value))
        except ValueError as exc:
            raise ValueError(f"UNCONFIRMED_TOUCHES_BY_LEVEL_KIND value for {level_kind} must be an integer") from exc
    return result


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    db_path: Path
    log_level: int
    binance_base_url: str
    scan_interval_seconds: int
    timeframes: tuple[str, ...]
    signal_symbol_allowlist: tuple[str, ...]
    max_symbols: int
    min_quote_volume_24h: float
    kline_limit: int
    max_concurrent_kline_requests: int
    level_lookback_candles: int
    zone_confirmation_touches: int
    level_tolerance_pct: float
    cluster_tolerance_natr_k: float
    zone_atr_multiplier: float
    zone_ttl_candles: int
    min_retreat_atr_multiplier: float
    impulse_threshold_atr: float
    impulse_lookback_candles: int
    breakout_distance_pct: float
    min_breakout_body_ratio: float
    min_volume_multiplier: float
    min_probe_volume_multiplier: float
    level_probe_distance_pct: float
    min_close_atr_multiplier: float
    min_close_distance_pct: float
    max_breakout_wick_ratio: float
    max_pre_breakout_range_pct: float
    level_approach_distance_pct: float
    level_approach_max_width_pct: float
    min_level_approach_gap_atr_multiplier: float
    level_min_spacing_candles: int
    min_level_span_candles: int
    min_level_age_candles: int
    min_natr_pct: float
    natr_period: int
    min_unconfirmed_signal_score: float
    unconfirmed_default_touches: int
    unconfirmed_touches_by_level_kind: dict[str, int]
    max_signals_per_scan: int
    max_signal_age_minutes: int
    symbol_analysis_pause_minutes: int
    send_unconfirmed_signals: bool
    skip_initial_scan: bool
    alert_cooldown_minutes: int
    fractal_n: int = 4
    live_window: int = 10
    lookback_candles: int = 300
    low_confidence_penalty: float = 0.7
    impulse_search_window: int = 200
    zone_ttl_bars: dict[str, int] = field(default_factory=lambda: {"1m": 400, "5m": 300, "15m": 200, "1h": 300})
    min_retreat_m: float = 4.0
    approach_threshold_k: float = 1.0
    cooldown_bars: int = 30
    min_24h_volume_usd: float = 5_000_000.0
    min_score_to_publish: float = 50.0
    max_publish_distance_natr: float = 1.5
    score_weights: dict[str, float] = field(default_factory=_score_weights_env)

    def required_unconfirmed_touches(self, level_kind: str) -> int:
        return self.unconfirmed_touches_by_level_kind.get(level_kind, self.unconfirmed_default_touches)


def load_settings() -> Settings:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN is required")

    db_path = Path(os.getenv("BOT_DB_PATH", str(ROOT_DIR / "data" / "bot.sqlite3")))
    if not db_path.is_absolute():
        db_path = ROOT_DIR.parents[1] / db_path

    log_level_name = os.getenv("BOT_LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)

    return Settings(
        telegram_bot_token=token,
        db_path=db_path,
        log_level=log_level,
        binance_base_url=os.getenv("BINANCE_FUTURES_BASE_URL", "https://fapi.binance.com").rstrip("/"),
        scan_interval_seconds=max(15, _int_env("SCAN_INTERVAL_SECONDS", 60)),
        timeframes=_timeframes_env(),
        signal_symbol_allowlist=_symbols_env("SIGNAL_SYMBOL_ALLOWLIST"),
        max_symbols=max(0, _int_env("SCAN_MAX_SYMBOLS", 0)),
        min_quote_volume_24h=max(0.0, _float_env("MIN_QUOTE_VOLUME_24H", 60_000_000.0)),
        kline_limit=max(80, _int_env("KLINE_LIMIT", 520)),
        max_concurrent_kline_requests=max(1, _int_env("MAX_CONCURRENT_KLINE_REQUESTS", 4)),
        level_lookback_candles=max(40, _int_env("LEVEL_LOOKBACK_CANDLES", _int_env("LOOKBACK_CANDLES", 300))),
        zone_confirmation_touches=max(1, _int_env("ZONE_CONFIRMATION_TOUCHES", 2)),
        level_tolerance_pct=max(0.01, _float_env("LEVEL_TOLERANCE_PCT", 0.18)),
        cluster_tolerance_natr_k=max(0.0, _float_env("CLUSTER_TOLERANCE_NATR_K", 0.75)),
        zone_atr_multiplier=max(0.0, _float_env("ZONE_ATR_MULTIPLIER", 0.20)),
        zone_ttl_candles=max(0, _int_env("ZONE_TTL_CANDLES", 360)),
        min_retreat_atr_multiplier=max(0.0, _float_env("MIN_RETREAT_ATR_MULTIPLIER", _float_env("MIN_RETREAT_M", 4.0))),
        impulse_threshold_atr=max(0.0, _float_env("IMPULSE_THRESHOLD_ATR", 2.0)),
        impulse_lookback_candles=max(1, _int_env("IMPULSE_LOOKBACK_CANDLES", _int_env("IMPULSE_SEARCH_WINDOW", 200))),
        breakout_distance_pct=max(0.01, _float_env("BREAKOUT_DISTANCE_PCT", 0.35)),
        min_breakout_body_ratio=max(0.0, min(1.0, _float_env("MIN_BREAKOUT_BODY_RATIO", 0.55))),
        min_volume_multiplier=max(1.0, _float_env("MIN_VOLUME_MULTIPLIER", 1.8)),
        min_probe_volume_multiplier=max(1.0, _float_env("MIN_PROBE_VOLUME_MULTIPLIER", 1.4)),
        level_probe_distance_pct=max(0.0, _float_env("LEVEL_PROBE_DISTANCE_PCT", 0.25)),
        min_close_atr_multiplier=max(0.0, _float_env("MIN_CLOSE_ATR_MULTIPLIER", 0.12)),
        min_close_distance_pct=max(0.0, _float_env("MIN_CLOSE_DISTANCE_PCT", 0.04)),
        max_breakout_wick_ratio=max(0.0, min(1.0, _float_env("MAX_BREAKOUT_WICK_RATIO", 0.25))),
        max_pre_breakout_range_pct=max(0.0, _float_env("MAX_PRE_BREAKOUT_RANGE_PCT", 1.2)),
        level_approach_distance_pct=max(0.0, _float_env("LEVEL_APPROACH_DISTANCE_PCT", 2.0)),
        level_approach_max_width_pct=max(0.05, _float_env("LEVEL_APPROACH_MAX_WIDTH_PCT", 0.85)),
        min_level_approach_gap_atr_multiplier=max(0.0, _float_env("MIN_LEVEL_APPROACH_GAP_ATR_MULTIPLIER", 0.5)),
        level_min_spacing_candles=max(1, _int_env("LEVEL_MIN_SPACING_CANDLES", 10)),
        min_level_span_candles=max(0, _int_env("MIN_LEVEL_SPAN_CANDLES", 30)),
        min_level_age_candles=max(0, _int_env("MIN_LEVEL_AGE_CANDLES", 12)),
        min_natr_pct=max(0.0, _float_env("MIN_NATR_PCT", 0.0)),
        natr_period=max(1, _int_env("NATR_PERIOD", 14)),
        min_unconfirmed_signal_score=max(0.0, _float_env("MIN_UNCONFIRMED_SIGNAL_SCORE", 60.0)),
        unconfirmed_default_touches=max(1, _int_env("UNCONFIRMED_DEFAULT_TOUCHES", 2)),
        unconfirmed_touches_by_level_kind=_unconfirmed_touches_by_level_kind_env(),
        max_signals_per_scan=max(0, _int_env("MAX_SIGNALS_PER_SCAN", 20)),
        max_signal_age_minutes=max(1, _int_env("MAX_SIGNAL_AGE_MINUTES", 5)),
        symbol_analysis_pause_minutes=max(0, _int_env("SYMBOL_ANALYSIS_PAUSE_MINUTES", 5)),
        send_unconfirmed_signals=_bool_env("SEND_UNCONFIRMED_SIGNALS", True),
        skip_initial_scan=_bool_env("SKIP_INITIAL_SCAN", True),
        alert_cooldown_minutes=max(1, _int_env("ALERT_COOLDOWN_MINUTES", 5)),
        fractal_n=max(1, _int_env("FRACTAL_N", 4)),
        live_window=max(2, _int_env("LIVE_WINDOW", 10)),
        lookback_candles=max(40, _int_env("LOOKBACK_CANDLES", _int_env("LEVEL_LOOKBACK_CANDLES", 300))),
        low_confidence_penalty=max(0.0, min(1.0, _float_env("LOW_CONFIDENCE_PENALTY", 0.7))),
        impulse_search_window=max(1, _int_env("IMPULSE_SEARCH_WINDOW", _int_env("IMPULSE_LOOKBACK_CANDLES", 200))),
        zone_ttl_bars=_bars_by_timeframe_env("ZONE_TTL_BARS", {"1m": 400, "5m": 300, "15m": 200, "1h": 300}),
        min_retreat_m=max(0.0, _float_env("MIN_RETREAT_M", _float_env("MIN_RETREAT_ATR_MULTIPLIER", 4.0))),
        approach_threshold_k=max(0.0, _float_env("APPROACH_THRESHOLD_K", 1.0)),
        cooldown_bars=max(0, _int_env("COOLDOWN_BARS", 30)),
        min_24h_volume_usd=max(0.0, _float_env("MIN_24H_VOLUME_USD", 5_000_000.0)),
        min_score_to_publish=max(0.0, _float_env("MIN_SCORE_TO_PUBLISH", 50.0)),
        max_publish_distance_natr=max(0.0, _float_env("MAX_PUBLISH_DISTANCE_NATR", 1.5)),
        score_weights=_score_weights_env(),
    )
