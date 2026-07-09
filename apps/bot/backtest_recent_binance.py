from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import random
import socket
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

import aiohttp

ROOT = Path(__file__).resolve().parents[2]
BOT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(BOT_ROOT))

from formation_bot.chart_renderer import render_signal_chart
from formation_bot.config import load_settings
from formation_bot.formations import detect_breakouts, timeframe_minutes
from formation_bot.models import BreakoutSignal, Candle, SymbolInfo


BINANCE_LIMIT = 1500
WANTED_REASONS = {
    "min_touches_not_reached": "min_touches",
    "zone_ttl_expired": "ttl",
    "min_retreat_not_reached": "min_retreat",
    "liquidity_below_minimum": "liquidity",
    "price_not_at_zone": "price_not_at_zone",
    "natr_below_minimum": "min_natr_pct",
    "breakout_body_ratio_below_minimum": "min_breakout_body_ratio",
    "breakout_opposite_wick_ratio_exceeded": "max_breakout_wick_ratio",
    "breakout_close_atr_below_minimum": "min_close_atr_multiplier",
    "max_publish_distance_exceeded": "max_publish_distance",
    "score_below_minimum": "score",
}


def utc_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat()


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * pct / 100
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[int(position)]
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def signal_to_record(signal: BreakoutSignal) -> dict[str, Any]:
    record = asdict(signal)
    record["detected_at"] = signal.detected_at.isoformat()
    record["candle_close_utc"] = utc_iso(signal.candle_close_time_ms)
    record["type"] = signal.signal_type or ("breakout" if signal.is_breakout_type else "test")
    return record


class BinanceHistory:
    def __init__(self, base_url: str, cache_dir: Path, refresh: bool = False) -> None:
        self.base_url = base_url.rstrip("/")
        self.cache_dir = cache_dir
        self.refresh = refresh
        self.session: aiohttp.ClientSession | None = None

    async def __aenter__(self) -> "BinanceHistory":
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        timeout = aiohttp.ClientTimeout(total=40)
        connector = aiohttp.TCPConnector(
            family=socket.AF_INET,
            resolver=aiohttp.ThreadedResolver(),
        )
        self.session = aiohttp.ClientSession(timeout=timeout, connector=connector)
        return self

    async def __aexit__(self, *_: object) -> None:
        if self.session:
            await self.session.close()

    async def request(self, path: str, params: dict[str, Any] | None = None) -> Any:
        if not self.session:
            raise RuntimeError("session is not initialized")
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                async with self.session.get(f"{self.base_url}{path}", params=params) as response:
                    if response.status in {418, 429}:
                        await asyncio.sleep(min(10, int(response.headers.get("Retry-After", "2"))))
                        continue
                    if response.status >= 400:
                        body = await response.text()
                        raise RuntimeError(f"HTTP {response.status}: {body[:200]}")
                    return await response.json()
            except (aiohttp.ClientError, asyncio.TimeoutError, RuntimeError) as exc:
                last_error = exc
                await asyncio.sleep(0.8 * (attempt + 1))
        raise last_error or RuntimeError("Binance request failed")

    async def server_time_ms(self) -> int:
        raw = await self.request("/fapi/v1/time")
        return int(raw["serverTime"])

    async def symbols(self, max_symbols: int, min_quote_volume_24h: float, allowlist: tuple[str, ...]) -> list[SymbolInfo]:
        exchange_info, tickers = await asyncio.gather(
            self.request("/fapi/v1/exchangeInfo"),
            self.request("/fapi/v1/ticker/24hr"),
        )
        ticker_by_symbol = {str(item.get("symbol")): item for item in tickers if isinstance(item, dict)}
        allow = set(allowlist)
        result: list[SymbolInfo] = []
        for item in exchange_info.get("symbols", []):
            if item.get("contractType") not in {"PERPETUAL", "TRADIFI_PERPETUAL"}:
                continue
            if item.get("quoteAsset") != "USDT" or item.get("status") != "TRADING":
                continue
            symbol = str(item.get("symbol"))
            ticker = ticker_by_symbol.get(symbol, {})
            quote_volume = float(ticker.get("quoteVolume") or 0)
            if quote_volume < min_quote_volume_24h:
                continue
            if allow and symbol not in allow:
                continue
            tick_size = 0.00000001
            for filter_item in item.get("filters", []):
                if filter_item.get("filterType") == "PRICE_FILTER":
                    tick_size = float(filter_item.get("tickSize") or tick_size)
                    break
            result.append(
                SymbolInfo(
                    symbol=symbol,
                    tick_size=tick_size,
                    quote_volume=quote_volume,
                    price_change_percent=float(ticker.get("priceChangePercent") or 0),
                    trades_24h=int(ticker.get("count") or 0),
                )
            )
        result.sort(key=lambda symbol: symbol.quote_volume, reverse=True)
        return result[:max_symbols] if max_symbols else result

    async def klines(self, symbol: str, timeframe: str, start_ms: int, end_ms: int) -> list[Candle]:
        cache_file = self.cache_dir / f"{symbol}_{timeframe}_{start_ms}_{end_ms}.json"
        if cache_file.exists() and not self.refresh:
            raw = json.loads(cache_file.read_text(encoding="utf-8"))
        else:
            raw = []
            cursor = start_ms
            while cursor <= end_ms:
                chunk = await self.request(
                    "/fapi/v1/klines",
                    {
                        "symbol": symbol,
                        "interval": timeframe,
                        "startTime": cursor,
                        "endTime": end_ms,
                        "limit": BINANCE_LIMIT,
                    },
                )
                if not chunk:
                    break
                raw.extend(chunk)
                next_cursor = int(chunk[-1][6]) + 1
                if next_cursor <= cursor:
                    break
                cursor = next_cursor
                await asyncio.sleep(0.03)
            cache_file.write_text(json.dumps(raw, separators=(",", ":")), encoding="utf-8")

        candles: list[Candle] = []
        for item in raw:
            close_ms = int(item[6])
            if close_ms > end_ms:
                continue
            candles.append(
                Candle(
                    open_time_ms=int(item[0]),
                    open=float(item[1]),
                    high=float(item[2]),
                    low=float(item[3]),
                    close=float(item[4]),
                    volume=float(item[5]),
                    close_time_ms=close_ms,
                    trades=int(item[8]),
                )
            )
        return candles


def detector_kwargs(settings: Any, timeframe: str, symbol: SymbolInfo, records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "lookback": settings.level_lookback_candles,
        "min_touches": settings.min_level_touches,
        "tolerance_pct": settings.level_tolerance_pct,
        "zone_atr_multiplier": settings.zone_atr_multiplier,
        "cluster_tolerance_natr_k": settings.cluster_tolerance_natr_k,
        "breakout_distance_pct": settings.breakout_distance_pct,
        "min_breakout_body_ratio": settings.min_breakout_body_ratio,
        "min_volume_multiplier": settings.min_volume_multiplier,
        "min_probe_volume_multiplier": settings.min_probe_volume_multiplier,
        "level_probe_distance_pct": settings.level_probe_distance_pct,
        "min_close_atr_multiplier": settings.min_close_atr_multiplier,
        "min_close_distance_pct": settings.min_close_distance_pct,
        "max_breakout_wick_ratio": settings.max_breakout_wick_ratio,
        "max_pre_breakout_range_pct": settings.max_pre_breakout_range_pct,
        "level_approach_distance_pct": settings.level_approach_distance_pct,
        "level_approach_max_width_pct": settings.level_approach_max_width_pct,
        "level_approach_min_touches": settings.level_approach_min_touches,
        "min_level_approach_gap_atr_multiplier": settings.min_level_approach_gap_atr_multiplier,
        "level_min_spacing_candles": settings.level_min_spacing_candles,
        "min_level_span_candles": settings.min_level_span_candles,
        "min_level_age_candles": settings.min_level_age_candles,
        "zone_ttl_candles": settings.zone_ttl_bars.get(timeframe, settings.zone_ttl_candles),
        "min_retreat_atr_multiplier": settings.min_retreat_atr_multiplier,
        "impulse_threshold_atr": settings.impulse_threshold_atr,
        "impulse_lookback_candles": settings.impulse_search_window,
        "min_natr_pct": settings.min_natr_pct,
        "natr_period": settings.natr_period,
        "fractal_n": settings.fractal_n,
        "live_window": settings.live_window,
        "low_confidence_penalty": settings.low_confidence_penalty,
        "approach_threshold_k": settings.approach_threshold_k,
        "cooldown_bars": settings.cooldown_bars,
        "volume_24h_usd": symbol.quote_volume,
        "min_24h_volume_usd": settings.min_24h_volume_usd,
        "min_score_to_publish": settings.min_score_to_publish,
        "max_publish_distance_natr": settings.max_publish_distance_natr,
        "score_weights": settings.score_weights,
        "decision_logger": records.append,
    }


def allowed_by_publish_filter(signal: BreakoutSignal, settings: Any) -> bool:
    if signal.confidence == "confirmed":
        return True
    signal_type = signal.signal_type or ("breakout" if signal.is_breakout_type else "test")
    if (
        signal_type == "test"
        and signal.confidence == "low_confidence"
        and signal.score >= settings.min_unconfirmed_signal_score
    ):
        return True
    return (
        signal.score >= settings.min_unconfirmed_signal_score
        and (
            signal.touches >= settings.min_unconfirmed_signal_touches
            or (signal.level_kind == "global_extreme" and signal.touches >= 2)
            or (signal.level_kind == "compression" and signal.touches >= 3)
            or (signal.level_kind == "impulse_approach" and signal.touches >= 2)
        )
    )


def run_backtest_for_series(
    settings: Any,
    symbol: SymbolInfo,
    timeframe: str,
    candles: list[Candle],
    period_start_ms: int,
    period_end_ms: int,
) -> tuple[list[BreakoutSignal], dict[str, Any]]:
    emitted: list[BreakoutSignal] = []
    rejected_by_reason: Counter[str] = Counter()
    decisions_total = 0
    rejected_total = 0
    debug_published = 0
    min_len = max(30, min(settings.level_lookback_candles, 60))
    for end_index in range(min_len - 1, len(candles)):
        close_ms = candles[end_index].close_time_ms
        if close_ms < period_start_ms:
            continue
        if close_ms > period_end_ms:
            break
        window_start = max(0, end_index + 1 - settings.kline_limit)
        window = candles[window_start : end_index + 1]
        raw_records: list[dict[str, Any]] = []
        signals = detect_breakouts(
            symbol=symbol.symbol,
            timeframe=timeframe,
            candles=window,
            **detector_kwargs(settings, timeframe, symbol, raw_records),
        )
        for record in raw_records:
            decisions_total += 1
            if record.get("final_decision") == "rejected":
                rejected_total += 1
                rejected_by_reason[WANTED_REASONS.get(str(record.get("rejection_reason")), str(record.get("rejection_reason")))] += 1
            elif str(record.get("final_decision", "")).startswith("published"):
                debug_published += 1
        for signal in signals:
            emitted.append(
                replace(
                    signal,
                    detected_at=datetime.fromtimestamp(signal.candle_close_time_ms / 1000, timezone.utc),
                    price_change_24h_pct=symbol.price_change_percent,
                    quote_volume_24h=symbol.quote_volume,
                    trades_24h=symbol.trades_24h,
                )
            )
    return emitted, {
        "candidate_decisions_total": decisions_total,
        "debug_published_decisions_before_publication_rules": debug_published,
        "rejected_total": rejected_total,
        "rejected_by_reason": dict(rejected_by_reason),
    }


def apply_publication_rules(
    settings: Any,
    raw: list[BreakoutSignal],
) -> list[BreakoutSignal]:
    by_time: dict[int, list[BreakoutSignal]] = defaultdict(list)
    for signal in raw:
        by_time[signal.candle_close_time_ms].append(signal)

    sent_keys: dict[str, int] = {}
    paused_until: dict[str, int] = {}
    published: list[BreakoutSignal] = []
    cooldown_ms = settings.alert_cooldown_minutes * 60_000
    pause_ms = settings.symbol_analysis_pause_minutes * 60_000

    for close_ms in sorted(by_time):
        candidates = [
            signal
            for signal in by_time[close_ms]
            if paused_until.get(signal.key, 0) <= close_ms and allowed_by_publish_filter(signal, settings)
        ]
        candidates.sort(key=lambda signal: signal.score, reverse=True)
        if settings.max_signals_per_scan and len(candidates) > settings.max_signals_per_scan:
            candidates = candidates[: settings.max_signals_per_scan]
        sent_signal_keys: set[str] = set()
        for signal in candidates:
            last_sent = sent_keys.get(signal.key)
            if last_sent is not None and close_ms - last_sent < cooldown_ms:
                continue
            sent_keys[signal.key] = close_ms
            published.append(signal)
            sent_signal_keys.add(signal.key)
        if pause_ms > 0:
            for signal_key in sent_signal_keys:
                paused_until[signal_key] = close_ms + pause_ms
    return published


def summarize(
    settings: Any,
    symbols: list[SymbolInfo],
    period_start_ms: int,
    period_end_ms: int,
    raw_signals: list[BreakoutSignal],
    published: list[BreakoutSignal],
    decision_summary: dict[str, Any],
) -> dict[str, Any]:
    signals = published
    raw_signal_items = raw_signals
    scores = [signal.score for signal in signals]
    duration_days = (period_end_ms - period_start_ms + 1) / 86_400_000
    duration_hours = duration_days * 24
    pair_count = max(1, len(symbols))
    by_pair = Counter(signal.symbol for signal in signals)
    return {
        "run": {
            "period_start_utc": utc_iso(period_start_ms),
            "period_end_utc": utc_iso(period_end_ms),
            "days": duration_days,
            "pairs_count": len(symbols),
            "pairs": [symbol.symbol for symbol in symbols],
            "timeframes": list(settings.timeframes),
            "min_score_to_publish": settings.min_score_to_publish,
            "publication_rules": {
                "min_unconfirmed_signal_score": settings.min_unconfirmed_signal_score,
                "min_unconfirmed_signal_touches": settings.min_unconfirmed_signal_touches,
                "max_signals_per_scan": settings.max_signals_per_scan,
                "alert_cooldown_minutes": settings.alert_cooldown_minutes,
                "symbol_analysis_pause_minutes": settings.symbol_analysis_pause_minutes,
            },
        },
        "published": {
            "total": len(signals),
            "raw_detector_signals_before_publication_rules": len(raw_signal_items),
            "by_type": dict(Counter(signal.signal_type or ("breakout" if signal.is_breakout_type else "test") for signal in signals)),
            "by_confidence": dict(Counter(signal.confidence for signal in signals)),
            "by_timeframe": dict(Counter(signal.timeframe for signal in signals)),
            "by_timeframe_type": {
                f"{timeframe}:{signal_type}": count
                for (timeframe, signal_type), count in Counter(
                    (signal.timeframe, signal.signal_type or ("breakout" if signal.is_breakout_type else "test")) for signal in signals
                ).items()
            },
            "signals_per_pair_per_day_avg": len(signals) / pair_count / duration_days,
            "signals_per_pair_per_hour_avg": len(signals) / pair_count / duration_hours,
            "signals_per_pair_per_day_distribution": {
                "min": min(by_pair.values()) / duration_days if by_pair else 0,
                "max": max(by_pair.values()) / duration_days if by_pair else 0,
                "median": median([by_pair.get(symbol.symbol, 0) / duration_days for symbol in symbols]) if symbols else 0,
            },
        },
        "score_distribution": {
            "min": min(scores) if scores else None,
            "max": max(scores) if scores else None,
            "median": median(scores) if scores else None,
            "p10": percentile(scores, 10),
            "p25": percentile(scores, 25),
            "p75": percentile(scores, 75),
            "p90": percentile(scores, 90),
            "p95": percentile(scores, 95),
            "p99": percentile(scores, 99),
        },
        "filtering": {
            "candidate_decisions_total": decision_summary["candidate_decisions_total"],
            "debug_published_decisions_before_publication_rules": decision_summary["debug_published_decisions_before_publication_rules"],
            "rejected_total": decision_summary["rejected_total"],
            "rejected_by_reason": decision_summary["rejected_by_reason"],
        },
    }


def load_cached_window(cache_dir: Path, signal: BreakoutSignal, max_candles: int) -> list[Candle]:
    pattern = f"{signal.symbol}_{signal.timeframe}_*.json"
    matches = sorted(cache_dir.glob(pattern), key=lambda path: path.stat().st_mtime, reverse=True)
    if not matches:
        raise FileNotFoundError(f"no cached klines for {signal.symbol} {signal.timeframe}")
    raw = json.loads(matches[0].read_text(encoding="utf-8"))
    candles: list[Candle] = []
    for item in raw:
        close_ms = int(item[6])
        if close_ms <= signal.candle_close_time_ms:
            candles.append(
                Candle(
                    open_time_ms=int(item[0]),
                    open=float(item[1]),
                    high=float(item[2]),
                    low=float(item[3]),
                    close=float(item[4]),
                    volume=float(item[5]),
                    close_time_ms=close_ms,
                    trades=int(item[8]),
                )
            )
    return candles[-max_candles:]


def merge_decision_summary(target: dict[str, Any], incoming: dict[str, Any]) -> None:
    target["candidate_decisions_total"] += incoming["candidate_decisions_total"]
    target["debug_published_decisions_before_publication_rules"] += incoming[
        "debug_published_decisions_before_publication_rules"
    ]
    target["rejected_total"] += incoming["rejected_total"]
    for reason, count in incoming["rejected_by_reason"].items():
        target["rejected_by_reason"][reason] += count


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=14)
    parser.add_argument("--sample-size", type=int, default=15)
    parser.add_argument("--seed", type=int, default=20260708)
    parser.add_argument("--workers", type=int, default=0)
    parser.add_argument("--refresh-cache", action="store_true")
    parser.add_argument("--out", type=Path, default=BOT_ROOT / "data" / "backtests")
    args = parser.parse_args()

    settings = load_settings()
    cpu_workers = args.workers or min(8, max(1, (os.cpu_count() or 2) - 1))
    args.out.mkdir(parents=True, exist_ok=True)
    cache_dir = args.out / "cache"
    async with BinanceHistory(settings.binance_base_url, cache_dir, args.refresh_cache) as history:
        server_ms = await history.server_time_ms()
        period_end_ms = server_ms - 60_000
        period_start_ms = period_end_ms - args.days * 86_400_000 + 1
        symbols = await history.symbols(settings.max_symbols, settings.min_quote_volume_24h, settings.signal_symbol_allowlist)
        print(
            f"period={utc_iso(period_start_ms)}..{utc_iso(period_end_ms)} "
            f"symbols={len(symbols)} timeframes={','.join(settings.timeframes)} workers={cpu_workers}",
            flush=True,
        )

        semaphore = asyncio.Semaphore(settings.max_concurrent_kline_requests)
        all_raw_signals: list[BreakoutSignal] = []
        decision_summary: dict[str, Any] = {
            "candidate_decisions_total": 0,
            "debug_published_decisions_before_publication_rules": 0,
            "rejected_total": 0,
            "rejected_by_reason": Counter(),
        }
        loop = asyncio.get_running_loop()

        async def process(executor: ProcessPoolExecutor, symbol: SymbolInfo, timeframe: str) -> None:
            tf_ms = timeframe_minutes(timeframe) * 60_000
            warmup_ms = (settings.kline_limit + 5) * tf_ms
            async with semaphore:
                candles = await history.klines(symbol.symbol, timeframe, period_start_ms - warmup_ms, period_end_ms)
            raw, partial_summary = await loop.run_in_executor(
                executor,
                run_backtest_for_series,
                settings,
                symbol,
                timeframe,
                candles,
                period_start_ms,
                period_end_ms,
            )
            all_raw_signals.extend(raw)
            merge_decision_summary(decision_summary, partial_summary)
            print(
                f"done {symbol.symbol} {timeframe}: candles={len(candles)} "
                f"raw_signals={len(raw)} decisions={partial_summary['candidate_decisions_total']}",
                flush=True,
            )

        with ProcessPoolExecutor(max_workers=cpu_workers) as executor:
            tasks = [process(executor, symbol, timeframe) for symbol in symbols for timeframe in settings.timeframes]
            batch_size = max(cpu_workers, settings.max_concurrent_kline_requests)
            for index in range(0, len(tasks), batch_size):
                await asyncio.gather(*tasks[index : index + batch_size])

    published = apply_publication_rules(settings, all_raw_signals)
    decision_summary["rejected_by_reason"] = dict(decision_summary["rejected_by_reason"])
    report = summarize(settings, symbols, period_start_ms, period_end_ms, all_raw_signals, published, decision_summary)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    run_dir = args.out / f"recent-{args.days}d-{stamp}"
    charts_dir = run_dir / "sample_charts"
    charts_dir.mkdir(parents=True, exist_ok=True)

    random.seed(args.seed)
    sample = random.sample(published, min(args.sample_size, len(published)))
    sample_records = []
    symbol_by_name = {symbol.symbol: symbol for symbol in symbols}
    for index, signal in enumerate(sample, 1):
        tick_size = symbol_by_name.get(signal.symbol, SymbolInfo(signal.symbol, 0.00000001, 0)).tick_size
        window = load_cached_window(cache_dir, signal, settings.kline_limit)
        png = render_signal_chart(window, signal, tick_size)
        chart_path = charts_dir / f"{index:02d}_{signal.symbol}_{signal.timeframe}_{signal.candle_close_time_ms}.png"
        chart_path.write_bytes(png)
        record = signal_to_record(signal)
        record["chart_path"] = str(chart_path)
        sample_records.append(record)

    report["sample"] = sample_records
    (run_dir / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (run_dir / "published_signals.jsonl").write_text(
        "\n".join(json.dumps(signal_to_record(signal), ensure_ascii=False) for signal in published),
        encoding="utf-8",
    )
    print(json.dumps({"run_dir": str(run_dir), **report}, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
