from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import replace
from pathlib import Path
from statistics import median
from typing import Any

BOT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(BOT_ROOT))

from formation_bot.config import load_settings
from formation_bot.formations import detect_breakouts, timeframe_minutes
from formation_bot.models import Candle, SymbolInfo


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
        "median": median(values) if values else None,
        "p01": percentile(values, 1),
        "p05": percentile(values, 5),
        "p10": percentile(values, 10),
        "p25": percentile(values, 25),
        "p50": percentile(values, 50),
        "p75": percentile(values, 75),
        "p90": percentile(values, 90),
        "p95": percentile(values, 95),
        "p99": percentile(values, 99),
    }


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


def detector_kwargs(settings: Any, timeframe: str, symbol: SymbolInfo, records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "lookback": settings.level_lookback_candles,
        "min_touches": settings.zone_confirmation_touches,
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


def analyze_one(args: tuple[Any, dict[str, Any], str, str, str, int, int]) -> dict[str, Any]:
    settings, symbol_data, timeframe, cache_path, period_start_ms, period_end_ms, kline_limit = args
    symbol = SymbolInfo(**symbol_data)
    candles = load_candles(Path(cache_path))
    min_len = max(30, min(settings.level_lookback_candles, 60))
    scores: list[float] = []
    by_type: dict[str, list[float]] = defaultdict(list)
    score_rejected = 0
    debug_published = 0
    for end_index in range(min_len - 1, len(candles)):
        close_ms = candles[end_index].close_time_ms
        if close_ms < period_start_ms:
            continue
        if close_ms > period_end_ms:
            break
        window = candles[max(0, end_index + 1 - kline_limit) : end_index + 1]
        records: list[dict[str, Any]] = []
        detect_breakouts(
            symbol=symbol.symbol,
            timeframe=timeframe,
            candles=window,
            **detector_kwargs(settings, timeframe, symbol, records),
        )
        for record in records:
            decision = str(record.get("final_decision", ""))
            reason = record.get("rejection_reason")
            if decision.startswith("published") or reason == "score_below_minimum":
                score = float(record["score"])
                scores.append(score)
                signal_type = "breakout" if "breakout" in decision else "test"
                if reason == "score_below_minimum":
                    signal_type = str(record.get("checks", {}).get("signal_type", {}).get("value") or "unknown")
                    score_rejected += 1
                else:
                    debug_published += 1
                by_type[signal_type].append(score)
    return {
        "symbol": symbol.symbol,
        "timeframe": timeframe,
        "scores": scores,
        "by_type": dict(by_type),
        "score_rejected": score_rejected,
        "debug_published": debug_published,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, default=BOT_ROOT / "data" / "backtests" / "recent-14d-20260708-023232")
    parser.add_argument("--cache", type=Path, default=BOT_ROOT / "data" / "backtests" / "cache")
    parser.add_argument("--workers", type=int, default=0)
    args = parser.parse_args()

    settings = load_settings()
    summary = json.loads((args.run / "summary.json").read_text(encoding="utf-8"))
    period_start_ms = int(__import__("datetime").datetime.fromisoformat(summary["run"]["period_start_utc"]).timestamp() * 1000)
    period_end_ms = int(__import__("datetime").datetime.fromisoformat(summary["run"]["period_end_utc"]).timestamp() * 1000)
    # Published records carry the same current metadata used by the original run.
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
                tasks.append((settings, by_symbol[symbol], timeframe, str(files[0]), period_start_ms, period_end_ms, settings.kline_limit))

    workers = args.workers or min(8, max(1, (os.cpu_count() or 2) - 1))
    all_scores: list[float] = []
    by_timeframe: dict[str, list[float]] = defaultdict(list)
    by_type: dict[str, list[float]] = defaultdict(list)
    counters = Counter()
    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(analyze_one, task) for task in tasks]
        for future in as_completed(futures):
            result = future.result()
            all_scores.extend(result["scores"])
            by_timeframe[result["timeframe"]].extend(result["scores"])
            counters["score_rejected"] += result["score_rejected"]
            counters["debug_published"] += result["debug_published"]
            for signal_type, scores in result["by_type"].items():
                by_type[signal_type].extend(scores)
            print(
                f"done {result['symbol']} {result['timeframe']} count={len(result['scores'])}",
                flush=True,
            )

    report = {
        "definition": "scores among detector candidates that passed min_touches/ttl/liquidity/min_retreat/price_at_zone, before MIN_SCORE_TO_PUBLISH cutoff",
        "count": len(all_scores),
        "debug_published": counters["debug_published"],
        "score_below_minimum": counters["score_rejected"],
        "overall": describe(all_scores),
        "by_timeframe": {key: describe(values) for key, values in sorted(by_timeframe.items())},
        "by_type": {key: describe(values) for key, values in sorted(by_type.items())},
        "counts_below_threshold": {
            str(threshold): sum(1 for value in all_scores if value < threshold)
            for threshold in [50, 55, 60, 65, 70, 75, 80, 85, 90, 95]
        },
    }
    out = args.run / "score_precutoff_distribution.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"out": str(out), **report}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
