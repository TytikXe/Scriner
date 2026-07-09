from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BOT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(BOT_ROOT))

from formation_bot.config import load_settings
from formation_bot.formations import detect_breakouts
from formation_bot.models import Candle, SymbolInfo


TARGET_SYMBOLS = {"OPGUSDT", "MUUSDT", "KORUUSDT"}


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


def signal_record(signal) -> dict[str, Any]:
    signal_type = signal.signal_type or ("breakout" if signal.is_breakout_type else "test")
    return {
        "symbol": signal.symbol,
        "timeframe": signal.timeframe,
        "close_ms": signal.candle_close_time_ms,
        "type": signal_type,
        "is_breakout_type": signal.is_breakout_type,
        "confidence": signal.confidence,
        "score": signal.score,
        "natr_pct": signal.natr_pct,
        "touches": signal.touches,
        "level_kind": signal.level_kind,
        "key": signal.key,
    }


def collect_one(args: tuple[Any, dict[str, Any], str, str, int, int, int]) -> list[dict[str, Any]]:
    settings, symbol_data, timeframe, cache_path, period_start_ms, period_end_ms, kline_limit = args
    symbol = SymbolInfo(**symbol_data)
    candles = load_candles(Path(cache_path))
    min_len = max(30, min(settings.level_lookback_candles, 60))
    result: list[dict[str, Any]] = []
    for end_index in range(min_len - 1, len(candles)):
        close_ms = candles[end_index].close_time_ms
        if close_ms < period_start_ms:
            continue
        if close_ms > period_end_ms:
            break
        window = candles[max(0, end_index + 1 - kline_limit) : end_index + 1]
        decisions: list[dict[str, Any]] = []
        signals = detect_breakouts(
            symbol=symbol.symbol,
            timeframe=timeframe,
            candles=window,
            **detector_kwargs(settings, timeframe, symbol, decisions),
        )
        result.extend(signal_record(signal) for signal in signals)
    return result


def load_signal_cache(path: Path) -> list[dict[str, Any]]:
    signals: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                signals.append(json.loads(line))
    return signals


def write_signal_cache(path: Path, signals: list[dict[str, Any]]) -> None:
    path.write_text(
        "\n".join(json.dumps(signal, ensure_ascii=False, separators=(",", ":")) for signal in signals),
        encoding="utf-8",
    )


def allowed_old(signal: dict[str, Any], settings: Any) -> bool:
    if signal["is_breakout_type"]:
        return True
    if not settings.send_unconfirmed_signals:
        return False
    if signal["score"] < settings.min_unconfirmed_signal_score:
        return False
    return signal["touches"] >= settings.required_unconfirmed_touches(signal["level_kind"])


def allowed_new(signal: dict[str, Any], settings: Any) -> bool:
    if signal["confidence"] == "confirmed":
        return True
    if not settings.send_unconfirmed_signals:
        return False
    if signal["score"] < settings.min_unconfirmed_signal_score:
        return False
    return signal["touches"] >= settings.required_unconfirmed_touches(signal["level_kind"])


def pause_key(signal: dict[str, Any], pause_scope: str) -> str:
    if pause_scope == "signal_key":
        return signal["key"]
    return signal["symbol"]


def sort_candidates(candidates: list[dict[str, Any]], sort_mode: str) -> None:
    if sort_mode == "legacy":
        candidates.sort(key=lambda item: (item["is_breakout_type"], item["natr_pct"], item["score"]), reverse=True)
        return
    candidates.sort(key=lambda item: item["score"], reverse=True)


def apply_policy(
    signals: list[dict[str, Any]],
    settings: Any,
    mode: str,
    *,
    sort_mode: str = "score",
    pause_scope: str = "symbol",
) -> dict[str, Any]:
    allow = allowed_old if mode == "old" else allowed_new
    by_time: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for signal in signals:
        by_time[signal["close_ms"]].append(signal)

    cooldown_ms = settings.alert_cooldown_minutes * 60_000
    pause_ms = settings.symbol_analysis_pause_minutes * 60_000
    paused_until: dict[str, int] = {}
    sent_keys: dict[str, int] = {}
    published: list[dict[str, Any]] = []
    statuses: dict[int, str] = {}
    allowed_count = 0
    batch_dropped = 0
    cooldown_dropped = 0
    pause_dropped = 0
    allowed_filter_dropped = 0
    paused_signal_keys: set[str] = set()
    paused_symbols: set[str] = set()

    for close_ms in sorted(by_time):
        candidates: list[dict[str, Any]] = []
        for signal in by_time[close_ms]:
            if pause_ms > 0 and paused_until.get(pause_key(signal, pause_scope), 0) > close_ms:
                statuses[signal["id"]] = f"{pause_scope}_pause"
                pause_dropped += 1
                paused_signal_keys.add(signal["key"])
                paused_symbols.add(signal["symbol"])
                continue
            if not allow(signal, settings):
                statuses[signal["id"]] = "allowed_filter"
                allowed_filter_dropped += 1
                continue
            candidates.append(signal)
            allowed_count += 1

        sort_candidates(candidates, sort_mode)
        kept = candidates
        if settings.max_signals_per_scan and len(candidates) > settings.max_signals_per_scan:
            kept = candidates[: settings.max_signals_per_scan]
            for signal in candidates[settings.max_signals_per_scan :]:
                statuses[signal["id"]] = "batch_limit"
                batch_dropped += 1

        sent_pause_keys: set[str] = set()
        for signal in kept:
            last_sent = sent_keys.get(signal["key"])
            if last_sent is not None and close_ms - last_sent < cooldown_ms:
                statuses[signal["id"]] = "cooldown"
                cooldown_dropped += 1
                continue
            sent_keys[signal["key"]] = close_ms
            statuses[signal["id"]] = "published"
            published.append(signal)
            sent_pause_keys.add(pause_key(signal, pause_scope))
        if pause_ms > 0:
            for key in sent_pause_keys:
                paused_until[key] = close_ms + pause_ms

    return {
        "sort_mode": sort_mode,
        "pause_scope": pause_scope,
        "allowed_count": allowed_count,
        "published_count": len(published),
        "published_by_type": dict(Counter(signal["type"] for signal in published)),
        "allowed_by_type": dict(Counter(signal["type"] for signal in signals if allow(signal, settings))),
        "drop_counts": {
            "allowed_filter": allowed_filter_dropped,
            f"{pause_scope}_pause": pause_dropped,
            "batch_limit": batch_dropped,
            "cooldown": cooldown_dropped,
        },
        "pause_drop_unique_signal_keys": len(paused_signal_keys),
        "pause_drop_unique_symbols": len(paused_symbols),
        "statuses": statuses,
    }


def summarize_targets(signals: list[dict[str, Any]], statuses: dict[int, str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for symbol in sorted(TARGET_SYMBOLS):
        items = [signal for signal in signals if signal["symbol"] == symbol]
        result[symbol] = {
            "detector_candidates": len(items),
            "by_type": dict(Counter(signal["type"] for signal in items)),
            "status_counts": dict(Counter(statuses.get(signal["id"], "unknown") for signal in items)),
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, default=BOT_ROOT / "data" / "backtests" / "recent-14d-20260708-023232")
    parser.add_argument("--cache", type=Path, default=BOT_ROOT / "data" / "backtests" / "cache")
    parser.add_argument("--signals-cache", type=Path, default=None)
    parser.add_argument("--workers", type=int, default=0)
    args = parser.parse_args()

    settings = load_settings()
    signal_cache = args.signals_cache or args.run / "detector_candidates_after_distance_score.jsonl"
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
                tasks.append((settings, by_symbol[symbol], timeframe, str(files[0]), period_start_ms, period_end_ms, settings.kline_limit))

    if signal_cache.exists():
        signals = load_signal_cache(signal_cache)
        print(f"loaded signal_cache={signal_cache} total={len(signals)}", flush=True)
    else:
        workers = args.workers or min(8, max(1, (os.cpu_count() or 2) - 1))
        signals = []
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(collect_one, task) for task in tasks]
            for future in as_completed(futures):
                items = future.result()
                signals.extend(items)
                print(f"collected batch={len(items)} total={len(signals)}", flush=True)
        write_signal_cache(signal_cache, signals)
        print(f"wrote signal_cache={signal_cache} total={len(signals)}", flush=True)

    for index, signal in enumerate(signals):
        signal["id"] = index

    old_policy = apply_policy(signals, settings, "old", sort_mode="legacy", pause_scope="symbol")
    new_policy_legacy_sort = apply_policy(signals, settings, "new", sort_mode="legacy", pause_scope="symbol")
    new_policy_score_sort = apply_policy(signals, settings, "new", sort_mode="score", pause_scope="symbol")
    new_policy_score_sort_signal_key_pause = apply_policy(
        signals,
        settings,
        "new",
        sort_mode="score",
        pause_scope="signal_key",
    )
    report = {
        "detector_after_distance_and_score": {
            "total": len(signals),
            "by_type": dict(Counter(signal["type"] for signal in signals)),
            "by_confidence": dict(Counter(signal["confidence"] for signal in signals)),
        },
        "old_policy": {key: value for key, value in old_policy.items() if key != "statuses"},
        "new_policy_legacy_sort_symbol_pause": {
            key: value for key, value in new_policy_legacy_sort.items() if key != "statuses"
        },
        "new_policy_score_sort_symbol_pause": {
            key: value for key, value in new_policy_score_sort.items() if key != "statuses"
        },
        "new_policy_score_sort_signal_key_pause": {
            key: value for key, value in new_policy_score_sort_signal_key_pause.items() if key != "statuses"
        },
        "target_symbols": {
            "old_policy": summarize_targets(signals, old_policy["statuses"]),
            "new_policy_legacy_sort_symbol_pause": summarize_targets(signals, new_policy_legacy_sort["statuses"]),
            "new_policy_score_sort_symbol_pause": summarize_targets(signals, new_policy_score_sort["statuses"]),
            "new_policy_score_sort_signal_key_pause": summarize_targets(
                signals,
                new_policy_score_sort_signal_key_pause["statuses"],
            ),
        },
        "live_sorting_key": ["score"],
    }
    out = args.run / "publication_funnel_score_sort.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"out": str(out), **report}, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
