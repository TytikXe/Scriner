from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import sqrt
from statistics import mean, pstdev
from typing import Iterable

from .schemas import (
    AiFormationAnalysis,
    AiFormationInput,
    Candle,
    DensitySignal,
    FormationSignal,
    FormationType,
    Level,
    MarketSymbol,
    OrderBookSnapshot,
    ScreenerFilters,
    ScreenerRow,
)


TIMEFRAME_MINUTES = {
    "1m": 1,
    "3m": 3,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "2h": 120,
    "4h": 240,
    "6h": 360,
    "12h": 720,
    "24h": 1440,
}


def timeframe_to_minutes(timeframe: str) -> int:
    return TIMEFRAME_MINUTES.get(timeframe, 5)


def _window_candles(candles: list[Candle], minutes: int, timeframe: str) -> list[Candle]:
    if not candles:
        return []
    per_candle = max(timeframe_to_minutes(timeframe), 1)
    count = max(1, int(minutes / per_candle))
    return candles[-count:]


def price_change(candles: list[Candle], minutes: int, timeframe: str = "5m") -> float:
    window = _window_candles(candles, minutes, timeframe)
    if len(window) < 2:
        return 0.0
    start = window[0].close
    end = window[-1].close
    if not start:
        return 0.0
    return (end - start) / start * 100


def volume_sum(candles: list[Candle], minutes: int, timeframe: str = "5m") -> float:
    return float(sum(c.volume for c in _window_candles(candles, minutes, timeframe)))


def trades_sum(candles: list[Candle], minutes: int, timeframe: str = "5m") -> float:
    window = _window_candles(candles, minutes, timeframe)
    total = 0.0
    for candle in window:
        if candle.trades is not None:
            total += candle.trades
        elif candle.volume and candle.close:
            total += candle.volume / candle.close
    return total


def true_range(current: Candle, prev_close: float) -> float:
    return max(current.high - current.low, abs(current.high - prev_close), abs(current.low - prev_close))


def natr(candles: list[Candle], atr_period: int = 14, smooth_period: int = 5) -> float:
    if len(candles) < atr_period + 1:
        return 0.0
    trs = []
    prev_close = candles[0].close
    for candle in candles[1:]:
        trs.append(true_range(candle, prev_close))
        prev_close = candle.close
    atrs = []
    if len(trs) < atr_period:
        return 0.0
    for i in range(atr_period - 1, len(trs)):
        atrs.append(sum(trs[i - atr_period + 1 : i + 1]) / atr_period)
    natr_values = []
    for idx, atr in enumerate(atrs, start=atr_period):
        close = candles[idx].close if idx < len(candles) else candles[-1].close
        if close:
            natr_values.append(atr / close * 200)
    if not natr_values:
        return 0.0
    tail = natr_values[-smooth_period:] if len(natr_values) >= smooth_period else natr_values
    return sum(tail) / len(tail)


def volatility(candles: list[Candle], minutes: int = 60, timeframe: str = "5m") -> float:
    window = _window_candles(candles, minutes, timeframe)
    if len(window) < 3:
        return 0.0
    returns = []
    for prev, cur in zip(window, window[1:]):
        if prev.close:
            returns.append((cur.close - prev.close) / prev.close)
    if len(returns) < 2:
        return 0.0
    return pstdev(returns) * sqrt(len(returns))


def btc_correlation(asset_candles: list[Candle], btc_candles: list[Candle], minutes: int = 24 * 60, timeframe: str = "5m") -> float:
    left = _window_candles(asset_candles, minutes, timeframe)
    right = _window_candles(btc_candles, minutes, timeframe)
    n = min(len(left), len(right))
    if n < 3:
        return 0.0
    left_returns = []
    right_returns = []
    left_slice = left[-n:]
    right_slice = right[-n:]
    for prev_left, cur_left, prev_right, cur_right in zip(left_slice, left_slice[1:], right_slice, right_slice[1:]):
        if prev_left.close and prev_right.close:
            left_returns.append((cur_left.close - prev_left.close) / prev_left.close)
            right_returns.append((cur_right.close - prev_right.close) / prev_right.close)
    if len(left_returns) < 3 or len(right_returns) < 3:
        return 0.0
    mean_left = mean(left_returns)
    mean_right = mean(right_returns)
    cov = sum((a - mean_left) * (b - mean_right) for a, b in zip(left_returns, right_returns))
    var_left = sum((a - mean_left) ** 2 for a in left_returns)
    var_right = sum((b - mean_right) ** 2 for b in right_returns)
    if not var_left or not var_right:
        return 0.0
    return cov / sqrt(var_left * var_right)


def round_price(price: float, precision: int = 2) -> float:
    return round(price, precision)


def detect_density_signals(
    snapshot: OrderBookSnapshot,
    current_price: float,
    limit_order_filter: float,
    limit_order_distance: float,
    limit_order_life: float,
    limit_order_corrosion_time: float,
    round_density: bool = True,
) -> list[DensitySignal]:
    detected: list[DensitySignal] = []
    now = datetime.now(timezone.utc)
    for side_name, levels in (("bid", snapshot.bids), ("ask", snapshot.asks)):
        for level in levels:
            if level.size_usd is not None and level.size_usd < limit_order_filter:
                continue
            level_price = round_price(level.price, 2) if round_density else level.price
            distance_pct = abs(level_price - current_price) / current_price * 100 if current_price else 0
            if distance_pct > limit_order_distance:
                continue
            lifetime = max(limit_order_life, 0)
            corrosion = max(limit_order_corrosion_time, 0)
            score = min(
                100.0,
                40
                + min(40, (level.size_usd or 0) / max(limit_order_filter, 1) * 10)
                + max(0, 20 - distance_pct * 4)
                + min(10, lifetime / 2)
                - min(10, corrosion / 3),
            )
            detected.append(
                DensitySignal(
                    symbol=snapshot.symbol,
                    market=snapshot.market,
                    exchange=snapshot.exchange,
                    price=current_price,
                    levelPrice=level_price,
                    side=side_name,
                    sizeUsd=level.size_usd or level.size * level.price,
                    distancePct=distance_pct,
                    lifeMinutes=lifetime,
                    corrosionMinutes=corrosion,
                    score=score,
                    detectedAt=now,
                )
            )
    return sorted(detected, key=lambda item: item.score, reverse=True)


def detect_horizontal_levels(
    candles: list[Candle],
    symbol: str,
    market: str,
    exchange: str,
    timeframe: str,
    period: int,
    touches: int,
    touches_threshold: float,
) -> list[Level]:
    window = candles[-period:] if len(candles) > period else candles
    if len(window) < touches:
        return []
    buckets: dict[float, list[Candle]] = defaultdict(list)
    for candle in window:
        for candidate in (candle.high, candle.low, candle.close):
            bucket = round(candidate / max(touches_threshold, 0.01)) * max(touches_threshold, 0.01)
            buckets[bucket].append(candle)
    levels: list[Level] = []
    now = datetime.now(timezone.utc)
    for price, touch_list in buckets.items():
        if len(touch_list) < touches:
            continue
        score = min(100.0, 50 + len(touch_list) * 8)
        direction = "neutral"
        levels.append(
            Level(
                symbol=symbol,
                market=market,
                exchange=exchange,
                type="horizontal",
                price=price,
                timeframe=timeframe,
                touches=len(touch_list),
                score=score,
                direction=direction,
                detectedAt=now,
            )
        )
    return sorted(levels, key=lambda level: level.score, reverse=True)


def detect_trend_levels(
    candles: list[Candle],
    symbol: str,
    market: str,
    exchange: str,
    timeframe: str,
    period: int,
    source: str = "high/low",
) -> list[Level]:
    window = candles[-period:] if len(candles) > period else candles
    if len(window) < 10:
        return []
    xs = list(range(len(window)))
    if source == "close":
        ys = [c.close for c in window]
    else:
        ys = [(c.high + c.low) / 2 for c in window]
    x_mean = mean(xs)
    y_mean = mean(ys)
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    denominator = sum((x - x_mean) ** 2 for x in xs)
    if not denominator:
        return []
    slope = numerator / denominator
    intercept = y_mean - slope * x_mean
    fitted = [slope * x + intercept for x in xs]
    residuals = [abs(y - f) for y, f in zip(ys, fitted)]
    avg_residual = mean(residuals)
    current_price = window[-1].close
    direction = "up" if slope > 0 else "down" if slope < 0 else "neutral"
    score = max(0.0, min(100.0, 70 - avg_residual / max(current_price, 1) * 1000 + abs(slope) * 100))
    return [
        Level(
            symbol=symbol,
            market=market,
            exchange=exchange,
            type="trend",
            price=fitted[-1],
            timeframe=timeframe,
            touches=max(2, len(window) // 20),
            score=score,
            direction=direction,
            detectedAt=datetime.now(timezone.utc),
        )
    ]


def nearest_level_distance_pct(price: float, levels: Iterable[Level]) -> tuple[float, Level | None]:
    nearest: Level | None = None
    nearest_distance = 999.0
    for level in levels:
        distance = abs(level.price - price) / price * 100 if price else 999.0
        if distance < nearest_distance:
            nearest_distance = distance
            nearest = level
    return nearest_distance, nearest


def scan_formation(
    symbol: str,
    market: str,
    exchange: str,
    timeframe: str,
    price: float,
    candles: list[Candle],
    densities: list[DensitySignal],
    horizontal_levels: list[Level],
    trend_levels: list[Level],
    formation: FormationType,
    active_threshold_volume: float = 50000,
    active_threshold_trades: float = 250,
    density_distance_limit: float = 1.5,
    limit_order_level_distance: float = 0.5,
) -> FormationSignal | None:
    now = datetime.now(timezone.utc)
    if formation == FormationType.None_:
        return None

    if formation == FormationType.ActiveCoins:
        vol = volume_sum(candles, 15, timeframe)
        tr = trades_sum(candles, 15, timeframe)
        if vol >= active_threshold_volume or tr >= active_threshold_trades:
            return FormationSignal(
                type=formation,
                symbol=symbol,
                market=market,
                timeframe=timeframe,
                direction="neutral",
                score=min(100.0, 40 + vol / max(active_threshold_volume, 1) * 20 + tr / max(active_threshold_trades, 1) * 20),
                distancePct=0.0,
                price=price,
                reason="Цена и поток сделок соответствуют порогам активности.",
                detectedAt=now,
            )
        return None

    if formation == FormationType.CoinsWithDensity:
        nearest_density = min(densities, key=lambda item: item.distancePct, default=None)
        if nearest_density and nearest_density.distancePct <= density_distance_limit:
            return FormationSignal(
                type=formation,
                symbol=symbol,
                market=market,
                timeframe=timeframe,
                direction="down" if nearest_density.side == "ask" else "up",
                score=min(100.0, 60 + (density_distance_limit - nearest_density.distancePct) * 15 + nearest_density.score * 0.2),
                distancePct=nearest_density.distancePct,
                price=price,
                densityPrice=nearest_density.levelPrice,
                densitySizeUsd=nearest_density.sizeUsd,
                reason="В стакане есть значимая плотность рядом с ценой.",
                detectedAt=now,
            )
        return None

    if formation == FormationType.HorizontalLevels:
        distance, level = nearest_level_distance_pct(price, horizontal_levels)
        if level and distance <= limit_order_level_distance:
            return FormationSignal(
                type=formation,
                symbol=symbol,
                market=market,
                timeframe=timeframe,
                direction=level.direction,
                score=min(100.0, level.score + 20 - distance * 10),
                distancePct=distance,
                price=price,
                levelPrice=level.price,
                reason="Цена находится рядом с горизонтальным уровнем.",
                detectedAt=now,
            )
        return None

    if formation == FormationType.TrendLevels:
        distance, level = nearest_level_distance_pct(price, trend_levels)
        if level and distance <= max(limit_order_level_distance * 2, 0.75):
            return FormationSignal(
                type=formation,
                symbol=symbol,
                market=market,
                timeframe=timeframe,
                direction=level.direction,
                score=min(100.0, level.score + 15 - distance * 8),
                distancePct=distance,
                price=price,
                levelPrice=level.price,
                reason="Цена соприкасается с трендовой линией.",
                detectedAt=now,
            )
        return None

    if formation == FormationType.HorizontalLevelWithLimitOrder:
        density_nearest = min(densities, key=lambda item: item.distancePct, default=None)
        level_distance, level = nearest_level_distance_pct(price, horizontal_levels)
        if density_nearest and level and abs(density_nearest.levelPrice - level.price) / max(price, 1) * 100 <= limit_order_level_distance:
            return FormationSignal(
                type=formation,
                symbol=symbol,
                market=market,
                timeframe=timeframe,
                direction=level.direction if level else "neutral",
                score=min(100.0, 70 + density_nearest.score * 0.15 + level.score * 0.15),
                distancePct=min(level_distance, density_nearest.distancePct),
                price=price,
                levelPrice=level.price if level else None,
                densityPrice=density_nearest.levelPrice,
                densitySizeUsd=density_nearest.sizeUsd,
                reason="Горизонтальный уровень совпадает с плотностью стакана.",
                detectedAt=now,
            )
        return None

    return None


def apply_filters(rows: list[ScreenerRow], filters: ScreenerFilters) -> list[ScreenerRow]:
    def within(value: float, lower: float | None, upper: float | None) -> bool:
        if lower is not None and value < lower:
            return False
        if upper is not None and value > upper:
            return False
        return True

    result = []
    for row in rows:
        if filters.onlyActive and not row.active:
            continue
        if filters.onlyWatchlist and not row.inWatchlist:
            continue
        if filters.onlyAlerts and not row.hasAlert:
            continue
        if filters.onlyFormations and not row.formation:
            continue
        if row.symbol in filters.blacklist:
            continue
        if row.market in filters.excludedMarkets:
            continue
        if not within(row.volumeSum24h, filters.volumeFrom, filters.volumeTo):
            continue
        if not within(row.priceChange24h, filters.priceChangeFrom, filters.priceChangeTo):
            continue
        if not within(row.tradesSum24h, filters.tradesFrom, filters.tradesTo):
            continue
        if not within(row.natr5_14, filters.natrFrom, filters.natrTo):
            continue
        if not within(row.btcCorrelation, filters.btcCorrelationFrom, filters.btcCorrelationTo):
            continue
        result.append(row)
    return result


def sort_rows(rows: list[ScreenerRow], sort_type: str) -> list[ScreenerRow]:
    if sort_type == "top_losers":
        return sorted(rows, key=lambda row: row.priceChange24h)
    if sort_type == "volume":
        return sorted(rows, key=lambda row: row.volumeSum24h, reverse=True)
    if sort_type == "trades":
        return sorted(rows, key=lambda row: row.tradesSum24h, reverse=True)
    if sort_type == "volatility":
        return sorted(rows, key=lambda row: row.volatility, reverse=True)
    if sort_type == "natr":
        return sorted(rows, key=lambda row: row.natr5_14, reverse=True)
    if sort_type == "btc_correlation":
        return sorted(rows, key=lambda row: row.btcCorrelation, reverse=True)
    if sort_type == "alerts_first":
        return sorted(rows, key=lambda row: (row.hasAlert, row.volumeSum24h), reverse=True)
    if sort_type == "watchlist_first":
        return sorted(rows, key=lambda row: (row.inWatchlist, row.volumeSum24h), reverse=True)
    if sort_type == "formations_first":
        return sorted(rows, key=lambda row: (row.formation is not None, row.formation.score if row.formation else 0), reverse=True)
    return sorted(rows, key=lambda row: row.priceChange24h, reverse=True)


def build_screener_row(
    symbol: str,
    market: str,
    exchange: str,
    candles: list[Candle],
    btc_candles: list[Candle],
    formation: FormationSignal | None = None,
    has_alert: bool = False,
    in_watchlist: bool = False,
    active: bool = True,
    funding_rate: float | None = None,
    open_interest: float | None = None,
) -> ScreenerRow:
    return ScreenerRow(
        symbol=symbol,
        market=market,
        exchange=exchange,
        price=candles[-1].close if candles else 0.0,
        priceChange1m=price_change(candles, 1),
        priceChange3m=price_change(candles, 3),
        priceChange5m=price_change(candles, 5),
        priceChange15m=price_change(candles, 15),
        priceChange30m=price_change(candles, 30),
        priceChange1h=price_change(candles, 60),
        priceChange2h=price_change(candles, 120),
        priceChange6h=price_change(candles, 360),
        priceChange12h=price_change(candles, 720),
        priceChange24h=price_change(candles, 1440),
        volumeSum1m=volume_sum(candles, 1),
        volumeSum5m=volume_sum(candles, 5),
        volumeSum1h=volume_sum(candles, 60),
        volumeSum24h=volume_sum(candles, 1440),
        tradesSum1m=trades_sum(candles, 1),
        tradesSum5m=trades_sum(candles, 5),
        tradesSum1h=trades_sum(candles, 60),
        tradesSum24h=trades_sum(candles, 1440),
        natr5_14=natr(candles),
        volatility=volatility(candles),
        btcCorrelation=btc_correlation(candles, btc_candles),
        fundingRate=funding_rate,
        openInterest=open_interest,
        hasAlert=has_alert,
        inWatchlist=in_watchlist,
        active=active,
        formation=formation,
    )


def ai_local_analysis(payload: AiFormationInput) -> AiFormationAnalysis:
    formation = payload.formation
    summary = f"Формация {formation.type.value} на {payload.symbol} в {payload.timeframe} выглядит рабочей по тем данным, которые переданы."
    why = [formation.reason]
    if formation.levelPrice is not None:
        why.append(f"Уровень рядом с ценой: {formation.levelPrice:.6f}")
    if formation.densityPrice is not None:
        why.append(f"Плотность рядом с ценой: {formation.densityPrice:.6f}")
    bullish = "Если цена закрепляется выше ближайшего уровня и объем растет, сценарий выглядит конструктивно."
    bearish = "Если цена теряет ближайший уровень или плотность быстро исчезает, формация ослабевает."
    risk = [
        "Локальная волатильность может пробить уровень без продолжения.",
        "Плотности в стакане могут быстро сниматься.",
        "Без свежих свечей и стакана оценка остается вероятностной.",
    ]
    invalidation = "Сценарий теряет смысл при уходе цены за ближайший уровень или при исчезновении плотности."
    watch = [
        f"Цена: {payload.currentPrice:.6f}",
        f"Score формации: {formation.score:.1f}",
        f"Distance: {formation.distancePct:.2f}%",
    ]
    confidence = max(-1.0, min(1.0, (formation.score - 50) / 50))
    return AiFormationAnalysis(
        summary=summary,
        whyDetected=why,
        bullishScenario=bullish,
        bearishScenario=bearish,
        riskFactors=risk,
        invalidation=invalidation,
        watchPoints=watch,
        confidenceAdjustment=confidence,
    )
