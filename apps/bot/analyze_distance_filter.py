from __future__ import annotations

import argparse
import heapq
import json
import math
import os
import random
import sys
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BOT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(BOT_ROOT))

from formation_bot.chart_renderer import render_signal_chart
from formation_bot.config import load_settings
from formation_bot.formations import detect_breakouts
from formation_bot.models import BreakoutSignal, Candle, SymbolInfo


def utc_iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat()


def load_candles(cache_file: Path) -> list[Candle]:
    raw = json.loads(cache_file.read_text(encoding="utf-8"))
    return [
        Candle(
            open_time_ms=int(item[0]),
            open=float(item[1]),
            high=float(item[2]),
            low=float(item[3]),
            close=float(item[4]),
            volume=float(item[5]),
            close_time_ms=int(item[6]),
            trades=int(item[8]),
        )
        for item in raw
    ]


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
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def describe(values: list[float]) -> dict[str, float | int | None]:
    return {
        "count": len(values),
        "min": min(values) if values else None,
        "max": max(values) if values else None,
        "median": percentile(values, 50),
        "p05": percentile(values, 5),
        "p10": percentile(values, 10),
        "p25": percentile(values, 25),
        "p75": percentile(values, 75),
        "p90": percentile(values, 90),
        "p95": percentile(values, 95),
        "p99": percentile(values, 99),
    }


def signal_to_record(signal: BreakoutSignal, random_key: float) -> dict[str, Any]:
    record = asdict(signal)
    record["detected_at"] = signal.detected_at.isoformat()
    record["candle_close_utc"] = utc_iso(signal.candle_close_time_ms)
    record["type"] = signal.signal_type or ("breakout" if signal.is_breakout_type else "test")
    record["_random_key"] = random_key
    return record


def signal_from_record(record: dict[str, Any]) -> BreakoutSignal:
    data = {key: value for key, value in record.items() if not key.startswith("_") and key not in {"type", "chart_path", "candle_close_utc"}}
    data["detected_at"] = datetime.fromisoformat(data["detected_at"])
    data["pivot_points"] = tuple(tuple(item) for item in data.get("pivot_points", ()))
    return BreakoutSignal(**data)


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


def bin_name(distance_natr: float) -> str:
    if distance_natr < 2:
        return "1.5-2x"
    if distance_natr < 3:
        return "2-3x"
    if distance_natr < 5:
        return "3-5x"
    return ">5x"


def analyze_one(args: tuple[Any, dict[str, Any], str, str, int, int, int, int, int]) -> dict[str, Any]:
    settings, symbol_data, timeframe, cache_path, period_start_ms, period_end_ms, sample_size, seed, kline_limit = args
    symbol = SymbolInfo(**symbol_data)
    candles = load_candles(Path(cache_path))
    min_len = max(30, min(settings.level_lookback_candles, 60))
    rejected_distances: list[float] = []
    rejected_bins = Counter()
    rejected_by_type = Counter()
    rejected_by_timeframe = Counter()
    after_count = 0
    sample_heap: list[tuple[float, dict[str, Any]]] = []

    for end_index in range(min_len - 1, len(candles)):
        close_ms = candles[end_index].close_time_ms
        if close_ms < period_start_ms:
            continue
        if close_ms > period_end_ms:
            break
        window = candles[max(0, end_index + 1 - kline_limit) : end_index + 1]
        records: list[dict[str, Any]] = []
        signals = detect_breakouts(
            symbol=symbol.symbol,
            timeframe=timeframe,
            candles=window,
            **detector_kwargs(settings, timeframe, symbol, records),
        )
        for record in records:
            if record.get("rejection_reason") == "max_publish_distance_exceeded":
                check = record["checks"]["max_publish_distance"]
                distance_natr = float(check["distance_natr"])
                rejected_distances.append(distance_natr)
                rejected_bins[bin_name(distance_natr)] += 1
                rejected_by_timeframe[timeframe] += 1
                rejected_by_type[str(record.get("checks", {}).get("signal_type", {}).get("value") or "unknown")] += 1
        for signal in signals:
            after_count += 1
            key_rng = random.Random(f"{seed}:{symbol.symbol}:{timeframe}:{signal.candle_close_time_ms}:{signal.key}")
            random_key = key_rng.random()
            item = (random_key, signal_to_record(signal, random_key))
            if len(sample_heap) < sample_size:
                heapq.heappush(sample_heap, item)
            elif random_key > sample_heap[0][0]:
                heapq.heapreplace(sample_heap, item)

    return {
        "symbol": symbol.symbol,
        "timeframe": timeframe,
        "after_count": after_count,
        "rejected_distances": rejected_distances,
        "rejected_bins": dict(rejected_bins),
        "rejected_by_type": dict(rejected_by_type),
        "rejected_by_timeframe": dict(rejected_by_timeframe),
        "sample": [record for _, record in sample_heap],
    }


def load_window_for_signal(cache_dir: Path, signal: BreakoutSignal, kline_limit: int) -> list[Candle]:
    files = sorted(cache_dir.glob(f"{signal.symbol}_{signal.timeframe}_*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not files:
        raise FileNotFoundError(f"no cache for {signal.symbol} {signal.timeframe}")
    candles = load_candles(files[0])
    return [candle for candle in candles if candle.close_time_ms <= signal.candle_close_time_ms][-kline_limit:]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, default=BOT_ROOT / "data" / "backtests" / "recent-14d-20260708-023232")
    parser.add_argument("--cache", type=Path, default=BOT_ROOT / "data" / "backtests" / "cache")
    parser.add_argument("--workers", type=int, default=0)
    parser.add_argument("--sample-size", type=int, default=15)
    parser.add_argument("--seed", type=int, default=20260708)
    args = parser.parse_args()

    settings = load_settings()
    summary = json.loads((args.run / "summary.json").read_text(encoding="utf-8"))
    period_start_ms = int(datetime.fromisoformat(summary["run"]["period_start_utc"]).timestamp() * 1000)
    period_end_ms = int(datetime.fromisoformat(summary["run"]["period_end_utc"]).timestamp() * 1000)

    by_symbol: dict[str, dict[str, Any]] = {}
    for line in (args.run / "published_signals.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        by_symbol.setdefault(
            record["symbol"],
            {
                "symbol": record["symbol"],
                "tick_size": 0.00000001,
                "quote_volume": float(record.get("quote_volume_24h") or 0),
                "price_change_percent": record.get("price_change_24h_pct"),
                "trades_24h": record.get("trades_24h"),
            },
        )

    tasks = []
    for symbol in summary["run"]["pairs"]:
        for timeframe in summary["run"]["timeframes"]:
            files = sorted(args.cache.glob(f"{symbol}_{timeframe}_*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
            if files and symbol in by_symbol:
                tasks.append((settings, by_symbol[symbol], timeframe, str(files[0]), period_start_ms, period_end_ms, args.sample_size, args.seed, settings.kline_limit))

    workers = args.workers or min(8, max(1, (os.cpu_count() or 2) - 1))
    all_distances: list[float] = []
    bins = Counter()
    by_type = Counter()
    rejected_by_timeframe = Counter()
    after_by_timeframe = Counter()
    sample_heap: list[tuple[float, dict[str, Any]]] = []

    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(analyze_one, task) for task in tasks]
        for future in as_completed(futures):
            result = future.result()
            all_distances.extend(result["rejected_distances"])
            bins.update(result["rejected_bins"])
            by_type.update(result["rejected_by_type"])
            rejected_by_timeframe.update(result["rejected_by_timeframe"])
            after_by_timeframe[result["timeframe"]] += result["after_count"]
            for record in result["sample"]:
                item = (float(record["_random_key"]), record)
                if len(sample_heap) < args.sample_size:
                    heapq.heappush(sample_heap, item)
                elif item[0] > sample_heap[0][0]:
                    heapq.heapreplace(sample_heap, item)
            print(
                f"done {result['symbol']} {result['timeframe']} rejected={len(result['rejected_distances'])} after={result['after_count']}",
                flush=True,
            )

    sample = [record for _, record in sorted(sample_heap, reverse=True)]
    out_dir = args.run / "distance_filter_after_sample"
    charts_dir = out_dir / "sample_charts"
    charts_dir.mkdir(parents=True, exist_ok=True)

    for index, record in enumerate(sample, 1):
        signal = signal_from_record(record)
        window = load_window_for_signal(args.cache, signal, settings.kline_limit)
        png = render_signal_chart(window, signal, 0.00000001)
        chart_path = charts_dir / f"{index:02d}_{signal.symbol}_{signal.timeframe}_{signal.candle_close_time_ms}.png"
        chart_path.write_bytes(png)
        record["chart_path"] = str(chart_path)
        check_edge = signal.zone_upper if signal.signal_type == "breakout" and signal.side == "resistance" else signal.zone_lower
        if signal.signal_type == "test":
            check_edge = signal.zone_lower if signal.side == "resistance" else signal.zone_upper
        distance_ratio = abs(signal.price - check_edge) / check_edge
        record["distance_natr"] = distance_ratio / max(signal.natr_pct / 100, 1e-12)
        record["distance_pct"] = distance_ratio * 100
        record["max_distance_pct"] = settings.max_publish_distance_natr * signal.natr_pct

    report = {
        "definition": "candidates rejected by max_publish_distance_exceeded after passing earlier hard checks",
        "max_publish_distance_natr": settings.max_publish_distance_natr,
        "rejected_total": len(all_distances),
        "distance_natr": describe(all_distances),
        "bins": dict(bins),
        "bins_pct": {key: (count / len(all_distances) * 100 if all_distances else 0) for key, count in bins.items()},
        "by_type": dict(by_type),
        "rejected_by_timeframe": dict(rejected_by_timeframe),
        "after_candidate_count_by_timeframe": dict(after_by_timeframe),
        "sample": sample,
    }
    out = out_dir / "distance_filter_report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"out": str(out), **report}, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
