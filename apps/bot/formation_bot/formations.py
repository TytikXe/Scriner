from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from math import log10
from statistics import mean

from .models import BreakoutSignal, Candle, LevelZone


logger = logging.getLogger(__name__)

LOW_CONFIDENCE = "low_confidence"
CONFIRMED = "confirmed"
LOW_CONFIDENCE_LEVEL_KIND = "early_single_touch"

TIMEFRAME_MINUTES = {
    "1m": 1,
    "3m": 3,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "2h": 120,
    "4h": 240,
}

DEFAULT_SCORE_WEIGHTS = {
    "w_touches": 0.25,
    "w_tightness": 0.20,
    "w_impulse": 0.15,
    "w_volume_touch": 0.15,
    "w_recency": 0.10,
    "w_liquidity": 0.15,
}


@dataclass(frozen=True)
class SwingPoint:
    side: str
    index: int
    price: float
    volume: float
    source: str
    prominence: float = 0.0


@dataclass(frozen=True)
class ImpulseResult:
    score: float
    bars_back: int | None


@dataclass(frozen=True)
class RetreatResult:
    passed: bool
    actual_retreat_natr: float


def timeframe_minutes(timeframe: str) -> int:
    return TIMEFRAME_MINUTES.get(timeframe, 1)


def price_decimals(tick_size: float) -> int:
    text = f"{tick_size:.12f}".rstrip("0")
    if "." not in text:
        return 0
    return min(8, len(text.split(".", 1)[1]))


def format_price(price: float, tick_size: float) -> str:
    decimals = price_decimals(tick_size)
    text = f"{price:.{decimals}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def average_true_range(candles: list[Candle], period: int = 14) -> float:
    if len(candles) < 2:
        return 0.0
    period = max(1, min(period, len(candles) - 1))
    values = []
    for prev, current in zip(candles[-period - 1 : -1], candles[-period:]):
        values.append(max(current.high - current.low, abs(current.high - prev.close), abs(current.low - prev.close)))
    return mean(values) if values else 0.0


def normalized_average_true_range(candles: list[Candle], period: int = 14) -> float:
    if not candles or candles[-1].close <= 0:
        return 0.0
    return average_true_range(candles, period) / candles[-1].close * 100


def _history(candles: list[Candle], lookback: int) -> tuple[list[Candle], int]:
    limit = max(1, min(len(candles), lookback))
    start = len(candles) - limit
    return candles[start:], start


def _tolerance_ratio(
    reference_price: float,
    atr: float,
    natr_ratio: float,
    tolerance_pct: float,
    zone_atr_multiplier: float,
    cluster_tolerance_natr_k: float,
) -> float:
    reference_price = max(abs(reference_price), 1e-12)
    candidates = [reference_price * max(0.0, tolerance_pct) / 100 / reference_price]
    if zone_atr_multiplier > 0:
        candidates.append(atr * zone_atr_multiplier / reference_price)
    if cluster_tolerance_natr_k > 0:
        candidates.append(cluster_tolerance_natr_k * natr_ratio)
    return max([value for value in candidates if value > 0] or [0.0005])


def _tolerance_price(
    reference_price: float,
    atr: float,
    natr_ratio: float,
    tolerance_pct: float,
    zone_atr_multiplier: float,
    cluster_tolerance_natr_k: float,
) -> float:
    return max(abs(reference_price), 1e-12) * _tolerance_ratio(
        reference_price,
        atr,
        natr_ratio,
        tolerance_pct,
        zone_atr_multiplier,
        cluster_tolerance_natr_k,
    )


def _confirmed_swings(
    candles: list[Candle],
    history_start_index: int,
    side: str,
    radius: int,
) -> list[SwingPoint]:
    if len(candles) < radius * 2 + 1:
        return []

    points: list[SwingPoint] = []
    for local_index in range(radius, len(candles) - radius):
        current = candles[local_index]
        left = candles[local_index - radius : local_index]
        right = candles[local_index + 1 : local_index + radius + 1]
        neighbours = left + right
        if side == "resistance":
            neighbour_high = max(candle.high for candle in neighbours)
            if current.high > neighbour_high:
                points.append(
                    SwingPoint(
                        side=side,
                        index=history_start_index + local_index,
                        price=current.high,
                        volume=current.volume,
                        source="confirmed",
                        prominence=current.high - neighbour_high,
                    )
                )
        else:
            neighbour_low = min(candle.low for candle in neighbours)
            if current.low < neighbour_low:
                points.append(
                    SwingPoint(
                        side=side,
                        index=history_start_index + local_index,
                        price=current.low,
                        volume=current.volume,
                        source="confirmed",
                        prominence=neighbour_low - current.low,
                    )
                )
    return points


def _live_edge_swings(candles: list[Candle], history_start_index: int, live_window: int) -> list[SwingPoint]:
    if not candles or live_window <= 0:
        return []
    window_start = max(0, len(candles) - max(2, live_window))
    window = candles[window_start:]
    high_local_offset, high_candle = max(enumerate(window), key=lambda item: item[1].high)
    low_local_offset, low_candle = min(enumerate(window), key=lambda item: item[1].low)
    high_local_index = window_start + high_local_offset
    low_local_index = window_start + low_local_offset
    return [
        SwingPoint(
            side="resistance",
            index=history_start_index + high_local_index,
            price=high_candle.high,
            volume=high_candle.volume,
            source="live",
        ),
        SwingPoint(
            side="support",
            index=history_start_index + low_local_index,
            price=low_candle.low,
            volume=low_candle.volume,
            source="live",
        ),
    ]


def _spaced_points(points: list[SwingPoint], min_spacing: int) -> list[SwingPoint]:
    if min_spacing <= 1:
        return sorted(points, key=lambda item: item.index)

    selected: list[SwingPoint] = []
    for point in sorted(points, key=lambda item: (item.prominence, item.source == "live"), reverse=True):
        if all(abs(point.index - existing.index) >= min_spacing for existing in selected):
            selected.append(point)
    return sorted(selected, key=lambda item: item.index)


def _zone_from_points(points: list[SwingPoint], min_touches: int) -> LevelZone | None:
    if not points:
        return None

    points = sorted(points, key=lambda item: item.index)
    lower = min(point.price for point in points)
    upper = max(point.price for point in points)
    if lower <= 0 or upper <= 0:
        return None

    touches = len(points)
    confidence = CONFIRMED if touches >= min_touches else LOW_CONFIDENCE
    has_live = any(point.source == "live" for point in points)
    level_kind = "standard"
    if confidence == LOW_CONFIDENCE:
        level_kind = "live_edge" if has_live else LOW_CONFIDENCE_LEVEL_KIND

    return LevelZone(
        side=points[0].side,
        lower=lower,
        upper=upper,
        touches=touches,
        score=0.0,
        first_touch_index=points[0].index,
        last_touch_index=points[-1].index,
        pivot_points=tuple((point.index, point.price) for point in points),
        level_kind=level_kind,
        confidence=confidence,
        avg_touch_volume=mean(point.volume for point in points),
    )


def _cluster_points(
    points: list[SwingPoint],
    atr: float,
    natr_ratio: float,
    min_touches: int,
    tolerance_pct: float,
    zone_atr_multiplier: float,
    cluster_tolerance_natr_k: float,
    min_spacing: int,
) -> list[LevelZone]:
    clusters: list[list[SwingPoint]] = []
    for point in sorted(points, key=lambda item: item.price):
        placed = False
        for cluster in clusters:
            midpoint = mean(item.price for item in cluster)
            tolerance = _tolerance_price(
                midpoint,
                atr,
                natr_ratio,
                tolerance_pct,
                zone_atr_multiplier,
                cluster_tolerance_natr_k,
            )
            if abs(point.price - midpoint) <= tolerance:
                cluster.append(point)
                placed = True
                break
        if not placed:
            clusters.append([point])

    zones: list[LevelZone] = []
    for cluster in clusters:
        spaced = _spaced_points(cluster, min_spacing)
        zone = _zone_from_points(spaced, min_touches)
        if zone:
            zones.append(zone)
    return _merge_nearby_zones(
        zones,
        atr,
        natr_ratio,
        min_touches,
        tolerance_pct,
        zone_atr_multiplier,
        cluster_tolerance_natr_k,
        min_spacing,
    )


def _merge_nearby_zones(
    zones: list[LevelZone],
    atr: float,
    natr_ratio: float,
    min_touches: int,
    tolerance_pct: float,
    zone_atr_multiplier: float,
    cluster_tolerance_natr_k: float,
    min_spacing: int,
) -> list[LevelZone]:
    merged: list[LevelZone] = []
    for zone in sorted(zones, key=lambda item: (item.side, item.lower, item.upper)):
        if not merged or merged[-1].side != zone.side:
            merged.append(zone)
            continue

        previous = merged[-1]
        reference_price = (previous.lower + previous.upper + zone.lower + zone.upper) / 4
        tolerance = _tolerance_price(
            reference_price,
            atr,
            natr_ratio,
            tolerance_pct,
            zone_atr_multiplier,
            cluster_tolerance_natr_k,
        )
        if zone.lower <= previous.upper + tolerance:
            points = [
                SwingPoint(previous.side, index, price, previous.avg_touch_volume, "confirmed")
                for index, price in previous.pivot_points
            ] + [
                SwingPoint(zone.side, index, price, zone.avg_touch_volume, "confirmed")
                for index, price in zone.pivot_points
            ]
            combined = _zone_from_points(_spaced_points(points, min_spacing), min_touches)
            if combined:
                merged[-1] = combined
        else:
            merged.append(zone)
    return merged


def _filter_zone_shape(
    zone: LevelZone,
    history_start_index: int,
    history_len: int,
    min_level_span_candles: int,
    min_level_age_candles: int,
) -> bool:
    if min_level_span_candles > 0 and zone.touches > 1:
        if zone.last_touch_index - zone.first_touch_index < min_level_span_candles:
            return False
    if min_level_age_candles > 0 and zone.level_kind != "live_edge":
        latest_index = history_start_index + history_len - 1
        if latest_index - zone.last_touch_index < min_level_age_candles:
            return False
    return True


def _zone_active(zone: LevelZone, latest_index: int, ttl_bars: int) -> bool:
    if ttl_bars <= 0:
        return True
    return latest_index - zone.last_touch_index <= ttl_bars


def _impulse_score(
    history: list[Candle],
    history_start_index: int,
    zone: LevelZone,
    atr: float,
    threshold_atr: float,
    search_window: int,
) -> ImpulseResult:
    if threshold_atr <= 0:
        return ImpulseResult(1.0, 0)
    if atr <= 0 or not history:
        return ImpulseResult(0.0, None)

    first_local = max(0, min(len(history) - 1, zone.first_touch_index - history_start_index))
    start = max(0, first_local - max(1, search_window))
    window = history[start : first_local + 1]
    if len(window) < 2:
        return ImpulseResult(0.0, None)

    required = atr * threshold_atr
    if zone.side == "support":
        extreme_offset, extreme = max(enumerate(window), key=lambda item: item[1].high)
        move = extreme.high - zone.lower
    else:
        extreme_offset, extreme = min(enumerate(window), key=lambda item: item[1].low)
        move = zone.upper - extreme.low
    if move <= 0:
        return ImpulseResult(0.0, None)
    return ImpulseResult(min(1.0, move / max(required, 1e-12)), first_local - (start + extreme_offset))


def _average_volume(candles: list[Candle], period: int = 30) -> float:
    window = candles[-period:] if len(candles) >= period else candles
    return mean(candle.volume for candle in window) if window else 0.0


def _liquidity_score(volume_24h_usd: float | None, min_24h_volume_usd: float) -> float:
    if volume_24h_usd is None or min_24h_volume_usd <= 0:
        return 1.0
    if volume_24h_usd <= 0:
        return 0.0
    if volume_24h_usd < min_24h_volume_usd:
        return max(0.0, volume_24h_usd / min_24h_volume_usd)
    return min(1.0, 0.65 + log10(volume_24h_usd / min_24h_volume_usd + 1.0) / 2.0)


def _score_zone(
    history: list[Candle],
    history_start_index: int,
    zone: LevelZone,
    atr: float,
    natr_ratio: float,
    min_touches: int,
    tolerance_pct: float,
    zone_atr_multiplier: float,
    cluster_tolerance_natr_k: float,
    ttl_bars: int,
    low_confidence_penalty: float,
    impulse_threshold_atr: float,
    impulse_search_window: int,
    volume_24h_usd: float | None,
    min_24h_volume_usd: float,
    score_weights: dict[str, float] | None,
) -> tuple[LevelZone, ImpulseResult]:
    latest_index = history_start_index + len(history) - 1
    reference_price = max((zone.lower + zone.upper) / 2, 1e-12)
    width_ratio = (zone.upper - zone.lower) / reference_price
    tolerance_ratio = _tolerance_ratio(
        reference_price,
        atr,
        natr_ratio,
        tolerance_pct,
        zone_atr_multiplier,
        cluster_tolerance_natr_k,
    )
    impulse = _impulse_score(history, history_start_index, zone, atr, impulse_threshold_atr, impulse_search_window)
    avg_volume = _average_volume(history[-31:-1] if len(history) > 31 else history)
    weights = dict(DEFAULT_SCORE_WEIGHTS)
    if score_weights:
        weights.update(score_weights)
    weight_sum = sum(weights.values()) or 1.0

    components = {
        "w_touches": min(1.0, zone.touches / max(1, min_touches)),
        "w_tightness": max(0.0, 1.0 - width_ratio / max(tolerance_ratio, 1e-12)),
        "w_impulse": impulse.score,
        "w_volume_touch": min(1.0, zone.avg_touch_volume / max(avg_volume * 1.5, 1e-12)) if avg_volume else 0.5,
        "w_recency": 1.0
        if ttl_bars <= 0
        else max(0.0, 1.0 - (latest_index - zone.last_touch_index) / max(ttl_bars, 1)),
        "w_liquidity": _liquidity_score(volume_24h_usd, min_24h_volume_usd),
    }
    score = 100.0 * sum(weights[key] * components[key] for key in weights) / weight_sum
    if zone.confidence == LOW_CONFIDENCE:
        score *= low_confidence_penalty
    scored = replace(zone, score=max(0.0, min(100.0, score)), impulse_score=impulse.score)
    return scored, impulse


def _retreat_result(
    history: list[Candle],
    history_start_index: int,
    zone: LevelZone,
    atr: float,
    min_retreat_m: float,
) -> RetreatResult:
    if min_retreat_m <= 0:
        return RetreatResult(True, 0.0)
    if atr <= 0:
        return RetreatResult(False, 0.0)

    last_touch_local = max(0, min(len(history) - 1, zone.last_touch_index - history_start_index))
    window = history[last_touch_local + 1 : -1]
    if not window and zone.level_kind == "live_edge":
        window = history[max(0, last_touch_local - 10) : last_touch_local]
    if not window:
        return RetreatResult(False, 0.0)

    if zone.side == "support":
        distance = max(candle.high for candle in window) - zone.upper
    else:
        distance = zone.lower - min(candle.low for candle in window)
    actual = max(0.0, distance / max(atr, 1e-12))
    return RetreatResult(actual >= min_retreat_m, actual)


def _classify_signal(latest: Candle, zone: LevelZone, approach_distance: float) -> str | None:
    if zone.side == "resistance":
        breakout = latest.close > zone.upper
        test = latest.high >= zone.lower - approach_distance
    else:
        breakout = latest.close < zone.lower
        test = latest.low <= zone.upper + approach_distance

    if breakout and zone.confidence == CONFIRMED:
        return "breakout"
    if test:
        return "test"
    return None


def _publish_distance_check(
    latest: Candle,
    zone: LevelZone,
    signal_type: str | None,
    natr_ratio: float,
    max_publish_distance_natr: float,
) -> dict[str, object]:
    edge = None
    if signal_type == "breakout":
        edge = zone.upper if zone.side == "resistance" else zone.lower
    elif signal_type == "test":
        edge = zone.lower if zone.side == "resistance" else zone.upper
    if edge is None or edge <= 0 or max_publish_distance_natr <= 0:
        distance_ratio = 0.0 if edge and edge > 0 else None
        max_distance_ratio = max_publish_distance_natr * natr_ratio
        return {
            "passed": True,
            "edge": edge,
            "distance_ratio": distance_ratio,
            "distance_natr": 0.0,
            "max_distance_natr": max_publish_distance_natr,
            "max_distance_ratio": max_distance_ratio,
        }

    distance_ratio = abs(latest.close - edge) / edge
    max_distance_ratio = max_publish_distance_natr * natr_ratio
    distance_natr = distance_ratio / max(natr_ratio, 1e-12)
    return {
        "passed": distance_ratio <= max_distance_ratio,
        "edge": edge,
        "distance_ratio": distance_ratio,
        "distance_natr": distance_natr,
        "max_distance_natr": max_publish_distance_natr,
        "max_distance_ratio": max_distance_ratio,
    }


def _decision_record(
    symbol: str,
    timeframe: str,
    latest: Candle,
    zone: LevelZone,
    checks: dict[str, object],
    final_decision: str,
    rejection_reason: str | None,
) -> dict[str, object]:
    return {
        "pair": symbol,
        "timeframe": timeframe,
        "timestamp": datetime.fromtimestamp(latest.close_time_ms / 1000, timezone.utc).isoformat(),
        "candidate_zone": {
            "side": zone.side,
            "zone_low": zone.lower,
            "zone_high": zone.upper,
            "touches_count": zone.touches,
            "confidence": zone.confidence,
        },
        "checks": checks,
        "final_decision": final_decision,
        "rejection_reason": rejection_reason,
        "score": round(zone.score, 2),
    }


def _emit_decision(record: dict[str, object], decision_logger: Callable[[dict[str, object]], None] | None) -> None:
    if decision_logger:
        decision_logger(record)
    logger.info("signal_candidate_decision=%s", json.dumps(record, ensure_ascii=False, separators=(",", ":")))


def _build_zones(
    candles: list[Candle],
    lookback: int,
    min_touches: int,
    tolerance_pct: float,
    zone_atr_multiplier: float,
    level_min_spacing_candles: int,
    min_level_span_candles: int,
    min_level_age_candles: int,
    cluster_tolerance_natr_k: float,
    zone_ttl_bars: int,
    impulse_threshold_atr: float,
    impulse_search_window: int,
    fractal_n: int,
    live_window: int,
    low_confidence_penalty: float,
    volume_24h_usd: float | None,
    min_24h_volume_usd: float,
    score_weights: dict[str, float] | None,
    natr_period: int,
    include_inactive: bool = False,
) -> tuple[list[LevelZone], list[Candle], int, float, float]:
    history, history_start_index = _history(candles, lookback)
    if len(history) < max(20, fractal_n * 2 + 2):
        return [], history, history_start_index, 0.0, 0.0

    atr = average_true_range(history, natr_period)
    natr_pct = normalized_average_true_range(history, natr_period)
    natr_ratio = natr_pct / 100
    swings = (
        _confirmed_swings(history, history_start_index, "resistance", fractal_n)
        + _confirmed_swings(history, history_start_index, "support", fractal_n)
        + _live_edge_swings(history, history_start_index, live_window)
    )
    zones: list[LevelZone] = []
    for side in ("resistance", "support"):
        zones.extend(
            _cluster_points(
                [point for point in swings if point.side == side],
                atr,
                natr_ratio,
                min_touches,
                tolerance_pct,
                zone_atr_multiplier,
                cluster_tolerance_natr_k,
                level_min_spacing_candles,
            )
        )

    latest_index = history_start_index + len(history) - 1
    scored_zones: list[LevelZone] = []
    for zone in zones:
        if not _filter_zone_shape(
            zone,
            history_start_index,
            len(history),
            min_level_span_candles,
            min_level_age_candles,
        ):
            continue
        scored, _ = _score_zone(
            history,
            history_start_index,
            zone,
            atr,
            natr_ratio,
            min_touches,
            tolerance_pct,
            zone_atr_multiplier,
            cluster_tolerance_natr_k,
            zone_ttl_bars,
            low_confidence_penalty,
            impulse_threshold_atr,
            impulse_search_window,
            volume_24h_usd,
            min_24h_volume_usd,
            score_weights,
        )
        if include_inactive or _zone_active(scored, latest_index, zone_ttl_bars):
            scored_zones.append(scored)

    return sorted(scored_zones, key=lambda item: (item.score, item.touches, item.last_touch_index), reverse=True), history, history_start_index, atr, natr_pct


def find_zones(
    candles: list[Candle],
    lookback: int,
    min_touches: int,
    tolerance_pct: float,
    zone_atr_multiplier: float,
    level_min_spacing_candles: int,
    min_level_span_candles: int = 0,
    min_level_age_candles: int = 0,
    cluster_tolerance_natr_k: float = 0.75,
    zone_ttl_candles: int = 0,
    impulse_threshold_atr: float = 2.0,
    impulse_lookback_candles: int = 200,
    *,
    fractal_n: int = 4,
    live_window: int = 10,
    low_confidence_penalty: float = 0.7,
    volume_24h_usd: float | None = None,
    min_24h_volume_usd: float = 5_000_000.0,
    score_weights: dict[str, float] | None = None,
    natr_period: int = 14,
) -> list[LevelZone]:
    zones, *_ = _build_zones(
        candles,
        lookback,
        min_touches,
        tolerance_pct,
        zone_atr_multiplier,
        level_min_spacing_candles,
        min_level_span_candles,
        min_level_age_candles,
        cluster_tolerance_natr_k,
        zone_ttl_candles,
        impulse_threshold_atr,
        impulse_lookback_candles,
        fractal_n,
        live_window,
        low_confidence_penalty,
        volume_24h_usd,
        min_24h_volume_usd,
        score_weights,
        natr_period,
        False,
    )
    return zones


def detect_breakouts(
    symbol: str,
    timeframe: str,
    candles: list[Candle],
    lookback: int,
    min_touches: int,
    tolerance_pct: float,
    zone_atr_multiplier: float,
    breakout_distance_pct: float,
    min_breakout_body_ratio: float,
    min_volume_multiplier: float,
    level_min_spacing_candles: int,
    cluster_tolerance_natr_k: float = 0.75,
    min_level_span_candles: int = 0,
    min_level_age_candles: int = 0,
    zone_ttl_candles: int = 0,
    min_retreat_atr_multiplier: float = 4.0,
    impulse_threshold_atr: float = 2.0,
    impulse_lookback_candles: int = 200,
    level_probe_distance_pct: float = 0.0,
    min_close_atr_multiplier: float = 0.04,
    min_close_distance_pct: float = 0.015,
    max_breakout_wick_ratio: float = 0.35,
    max_pre_breakout_range_pct: float = 0.0,
    min_probe_volume_multiplier: float | None = None,
    level_approach_distance_pct: float = 0.0,
    level_approach_max_width_pct: float = 0.85,
    level_approach_min_touches: int = 2,
    min_level_approach_gap_atr_multiplier: float = 0.75,
    min_natr_pct: float = 0.0,
    natr_period: int = 14,
    *,
    fractal_n: int = 4,
    live_window: int = 10,
    low_confidence_penalty: float = 0.7,
    approach_threshold_k: float = 1.0,
    cooldown_bars: int = 30,
    volume_24h_usd: float | None = None,
    min_24h_volume_usd: float = 5_000_000.0,
    min_score_to_publish: float = 0.0,
    max_publish_distance_natr: float = 1.5,
    score_weights: dict[str, float] | None = None,
    decision_logger: Callable[[dict[str, object]], None] | None = None,
) -> list[BreakoutSignal]:
    if len(candles) < max(30, min(lookback, 60)):
        return []

    latest = candles[-1]
    zones, history, history_start_index, atr, natr_pct = _build_zones(
        candles,
        lookback,
        min_touches,
        tolerance_pct,
        zone_atr_multiplier,
        level_min_spacing_candles,
        min_level_span_candles,
        min_level_age_candles,
        cluster_tolerance_natr_k,
        zone_ttl_candles,
        impulse_threshold_atr,
        impulse_lookback_candles,
        fractal_n,
        live_window,
        low_confidence_penalty,
        volume_24h_usd,
        min_24h_volume_usd,
        score_weights,
        natr_period,
        True,
    )
    latest_index = history_start_index + len(history) - 1
    natr_ratio = natr_pct / 100
    approach_distance = latest.close * max(
        approach_threshold_k * natr_ratio,
        max(level_probe_distance_pct, level_approach_distance_pct) / 100,
    )
    liquidity_passed = volume_24h_usd is None or volume_24h_usd >= min_24h_volume_usd
    avg_volume = _average_volume(history[-31:-1] if len(history) > 31 else history)
    candidates: list[tuple[int, int, float, int, BreakoutSignal]] = []

    for zone in zones:
        impulse = _impulse_score(history, history_start_index, zone, atr, impulse_threshold_atr, impulse_lookback_candles)
        retreat = _retreat_result(history, history_start_index, zone, atr, min_retreat_atr_multiplier)
        signal_type = _classify_signal(latest, zone, approach_distance)
        volume_multiplier = min_volume_multiplier if signal_type == "breakout" else (min_probe_volume_multiplier or min_volume_multiplier)
        volume_threshold = avg_volume * max(0.0, volume_multiplier)
        volume_passed = not avg_volume or latest.volume >= volume_threshold
        active = _zone_active(zone, latest_index, zone_ttl_candles)
        min_touches_passed = zone.touches >= min_touches
        max_publish_distance = _publish_distance_check(
            latest,
            zone,
            signal_type,
            natr_ratio,
            max_publish_distance_natr,
        )
        checks = {
            "min_touches": {"passed": min_touches_passed, "required": min_touches, "actual": zone.touches},
            "ttl": {"passed": active, "ttl_bars": zone_ttl_candles},
            "impulse_found": {
                "passed": impulse.score > 0,
                "impulse_score": round(impulse.score, 4),
                "bars_back": impulse.bars_back,
            },
            "min_retreat": {
                "passed": retreat.passed,
                "required_retreat_natr": min_retreat_atr_multiplier,
                "actual_retreat_natr": round(retreat.actual_retreat_natr, 4),
            },
            "cooldown": {"passed": True, "cooldown_bars": cooldown_bars},
            "liquidity": {"passed": liquidity_passed, "volume_24h_usd": volume_24h_usd},
            "volume": {
                "passed": volume_passed,
                "latest": latest.volume,
                "average": avg_volume,
                "multiplier": volume_multiplier,
                "threshold": volume_threshold,
            },
            "signal_type": {"passed": signal_type is not None, "value": signal_type},
            "max_publish_distance": {
                "passed": max_publish_distance["passed"],
                "edge": max_publish_distance["edge"],
                "distance_pct": round(float(max_publish_distance["distance_ratio"] or 0.0) * 100, 4),
                "distance_natr": round(float(max_publish_distance["distance_natr"]), 4),
                "max_distance_natr": max_publish_distance_natr,
                "max_distance_pct": round(float(max_publish_distance["max_distance_ratio"]) * 100, 4),
            },
        }
        rejection_reason = None
        if not min_touches_passed:
            rejection_reason = "min_touches_not_reached"
        elif not active:
            rejection_reason = "zone_ttl_expired"
        elif not liquidity_passed:
            rejection_reason = "liquidity_below_minimum"
        elif not retreat.passed:
            rejection_reason = "min_retreat_not_reached"
        elif signal_type is None:
            rejection_reason = "price_not_at_zone"
        elif not bool(max_publish_distance["passed"]):
            rejection_reason = "max_publish_distance_exceeded"
        elif zone.score < min_score_to_publish:
            rejection_reason = "score_below_minimum"

        if rejection_reason:
            _emit_decision(
                _decision_record(symbol, timeframe, latest, zone, checks, "rejected", rejection_reason),
                decision_logger,
            )
            continue

        final_decision = "published_as_breakout" if signal_type == "breakout" else "published_as_test"
        if zone.confidence == LOW_CONFIDENCE:
            final_decision += "_low_confidence"
        _emit_decision(
            _decision_record(symbol, timeframe, latest, zone, checks, final_decision, None),
            decision_logger,
        )
        is_breakout_type = signal_type == "breakout"
        signal = BreakoutSignal(
            symbol=symbol,
            timeframe=timeframe,
            side=zone.side,
            price=latest.close,
            zone_lower=zone.lower,
            zone_upper=zone.upper,
            touches=zone.touches,
            score=zone.score,
            detected_at=datetime.now(timezone.utc),
            candle_close_time_ms=latest.close_time_ms,
            is_breakout_type=is_breakout_type,
            natr_pct=natr_pct,
            pivot_points=zone.pivot_points,
            level_kind=zone.level_kind,
            signal_type=signal_type,
            confidence=zone.confidence,
        )
        candidates.append(
            (
                1 if signal_type == "breakout" else 0,
                1 if zone.confidence == CONFIRMED else 0,
                zone.score,
                zone.touches,
                signal,
            )
        )

    if not candidates:
        return []

    candidates.sort(key=lambda item: item[:4], reverse=True)
    return [item[4] for item in candidates]


def detect_breakout(
    symbol: str,
    timeframe: str,
    candles: list[Candle],
    lookback: int,
    min_touches: int,
    tolerance_pct: float,
    zone_atr_multiplier: float,
    breakout_distance_pct: float,
    min_breakout_body_ratio: float,
    min_volume_multiplier: float,
    level_min_spacing_candles: int,
    cluster_tolerance_natr_k: float = 0.75,
    min_level_span_candles: int = 0,
    min_level_age_candles: int = 0,
    zone_ttl_candles: int = 0,
    min_retreat_atr_multiplier: float = 4.0,
    impulse_threshold_atr: float = 2.0,
    impulse_lookback_candles: int = 200,
    level_probe_distance_pct: float = 0.0,
    min_close_atr_multiplier: float = 0.04,
    min_close_distance_pct: float = 0.015,
    max_breakout_wick_ratio: float = 0.35,
    max_pre_breakout_range_pct: float = 0.0,
    min_probe_volume_multiplier: float | None = None,
    level_approach_distance_pct: float = 0.0,
    level_approach_max_width_pct: float = 0.85,
    level_approach_min_touches: int = 2,
    min_level_approach_gap_atr_multiplier: float = 0.75,
    min_natr_pct: float = 0.0,
    natr_period: int = 14,
    *,
    fractal_n: int = 4,
    live_window: int = 10,
    low_confidence_penalty: float = 0.7,
    approach_threshold_k: float = 1.0,
    cooldown_bars: int = 30,
    volume_24h_usd: float | None = None,
    min_24h_volume_usd: float = 5_000_000.0,
    min_score_to_publish: float = 0.0,
    max_publish_distance_natr: float = 1.5,
    score_weights: dict[str, float] | None = None,
    decision_logger: Callable[[dict[str, object]], None] | None = None,
) -> BreakoutSignal | None:
    signals = detect_breakouts(
        symbol=symbol,
        timeframe=timeframe,
        candles=candles,
        lookback=lookback,
        min_touches=min_touches,
        tolerance_pct=tolerance_pct,
        zone_atr_multiplier=zone_atr_multiplier,
        breakout_distance_pct=breakout_distance_pct,
        min_breakout_body_ratio=min_breakout_body_ratio,
        min_volume_multiplier=min_volume_multiplier,
        level_min_spacing_candles=level_min_spacing_candles,
        cluster_tolerance_natr_k=cluster_tolerance_natr_k,
        min_level_span_candles=min_level_span_candles,
        min_level_age_candles=min_level_age_candles,
        zone_ttl_candles=zone_ttl_candles,
        min_retreat_atr_multiplier=min_retreat_atr_multiplier,
        impulse_threshold_atr=impulse_threshold_atr,
        impulse_lookback_candles=impulse_lookback_candles,
        level_probe_distance_pct=level_probe_distance_pct,
        min_close_atr_multiplier=min_close_atr_multiplier,
        min_close_distance_pct=min_close_distance_pct,
        max_breakout_wick_ratio=max_breakout_wick_ratio,
        max_pre_breakout_range_pct=max_pre_breakout_range_pct,
        min_probe_volume_multiplier=min_probe_volume_multiplier,
        level_approach_distance_pct=level_approach_distance_pct,
        level_approach_max_width_pct=level_approach_max_width_pct,
        level_approach_min_touches=level_approach_min_touches,
        min_level_approach_gap_atr_multiplier=min_level_approach_gap_atr_multiplier,
        min_natr_pct=min_natr_pct,
        natr_period=natr_period,
        fractal_n=fractal_n,
        live_window=live_window,
        low_confidence_penalty=low_confidence_penalty,
        approach_threshold_k=approach_threshold_k,
        cooldown_bars=cooldown_bars,
        volume_24h_usd=volume_24h_usd,
        min_24h_volume_usd=min_24h_volume_usd,
        min_score_to_publish=min_score_to_publish,
        max_publish_distance_natr=max_publish_distance_natr,
        score_weights=score_weights,
        decision_logger=decision_logger,
    )
    return signals[0] if signals else None


def _format_signed_pct(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "n/a"
    return f"{value:+.{digits}f}%"


def _format_plain_pct(value: float | None, digits: int = 4) -> str:
    if value is None:
        return "n/a"
    return f"{value:.{digits}f}%"


def _format_volume(value: float | None) -> str:
    if value is None:
        return "n/a"
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f}B USDT"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M USDT"
    if value >= 1_000:
        return f"{value / 1_000:.1f}K USDT"
    return f"{value:.0f} USDT"


def _format_trades(value: int | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:,}".replace(",", " ")


def _format_correlation(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.2f}"


def format_signal_message(signal: BreakoutSignal, tick_size: float) -> str:
    if abs(signal.zone_upper - signal.zone_lower) <= max(tick_size / 2, 1e-12):
        zone_text = f"{format_price(signal.zone_upper, tick_size)}$"
        level_name = "уровня"
    else:
        zone_text = f"{format_price(signal.zone_lower, tick_size)}$, {format_price(signal.zone_upper, tick_size)}$"
        level_name = "уровней"

    signal_type = signal.signal_type or ("breakout" if signal.is_breakout_type else "test")
    if signal_type == "breakout":
        signal_name = "Пробой"
    elif signal.confidence == LOW_CONFIDENCE:
        signal_name = "Ранний тест"
    else:
        signal_name = "Тест"

    lines = [
        f"Binance Futures - {signal.symbol}",
        f"{signal_name} {level_name} {zone_text} на таймфрейме {signal.timeframe}",
        f"Цена закрытия: {format_price(signal.price, tick_size)}$",
        (
            f"Signal: {signal_type} | Confidence: {signal.confidence} | "
            f"Touches: {signal.touches} | NATR: {signal.natr_pct:.2f}% | Score: {signal.score:.0f}"
        ),
        (
            f"24ч: {_format_signed_pct(signal.price_change_24h_pct)} | "
            f"Объём: {_format_volume(signal.quote_volume_24h)} | "
            f"Сделки: {_format_trades(signal.trades_24h)}"
        ),
        (
            f"Funding: {_format_plain_pct(signal.funding_rate_pct)} | "
            f"BTC corr 1ч: {_format_correlation(signal.btc_correlation_1h)}"
        ),
    ]
    if signal.confidence == LOW_CONFIDENCE:
        lines.append("Тип: early low-confidence зона, 1 касание")
    return "\n".join(lines)
