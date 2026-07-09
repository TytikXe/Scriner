from __future__ import annotations

import argparse
import hashlib
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

from PIL import Image, ImageDraw, ImageFont

BOT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(BOT_ROOT))

from formation_bot.chart_renderer import render_signal_chart
from formation_bot.config import load_settings
from formation_bot.formations import detect_breakouts
from formation_bot.models import BreakoutSignal, Candle, SymbolInfo


CALIBRATION_BODY_RATIOS = (0.40, 0.50)
SAMPLE_SEED = 20260709
DISTANCE_EPSILON = 1e-9


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
        "p10": percentile(values, 10),
        "p25": percentile(values, 25),
        "median": percentile(values, 50),
        "p75": percentile(values, 75),
        "p90": percentile(values, 90),
        "p95": percentile(values, 95),
        "max": max(values) if values else None,
    }


def load_candles(path: Path) -> list[Candle]:
    raw = json.loads(path.read_text(encoding="utf-8"))
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


def detector_kwargs(settings: Any, timeframe: str, symbol: SymbolInfo) -> dict[str, Any]:
    return {
        "lookback": settings.level_lookback_candles,
        "min_touches": settings.zone_confirmation_touches,
        "tolerance_pct": settings.level_tolerance_pct,
        "zone_atr_multiplier": settings.zone_atr_multiplier,
        "cluster_tolerance_natr_k": settings.cluster_tolerance_natr_k,
        "breakout_distance_pct": settings.breakout_distance_pct,
        # Calibration-only relaxation. Production settings remain untouched.
        "min_breakout_body_ratio": 0.0,
        "max_breakout_wick_ratio": 1.0,
        "min_close_atr_multiplier": 0.0,
        "min_volume_multiplier": settings.min_volume_multiplier,
        "min_probe_volume_multiplier": settings.min_probe_volume_multiplier,
        "level_probe_distance_pct": settings.level_probe_distance_pct,
        "min_close_distance_pct": settings.min_close_distance_pct,
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
    }


def candle_metrics(signal: BreakoutSignal, candle: Candle) -> dict[str, float]:
    candle_range = max(0.0, candle.high - candle.low)
    body_ratio = abs(candle.close - candle.open) / candle_range if candle_range else 0.0
    if signal.side == "resistance":
        opposite_wick = max(0.0, min(candle.open, candle.close) - candle.low)
        edge = signal.zone_upper if signal.signal_type == "breakout" else signal.zone_lower
        close_penetration = max(0.0, candle.close - signal.zone_upper)
    else:
        opposite_wick = max(0.0, candle.high - max(candle.open, candle.close))
        edge = signal.zone_lower if signal.signal_type == "breakout" else signal.zone_upper
        close_penetration = max(0.0, signal.zone_lower - candle.close)
    opposite_wick_ratio = opposite_wick / candle_range if candle_range else 0.0
    natr_ratio = signal.natr_pct / 100
    atr = natr_ratio * candle.close
    close_atr = close_penetration / atr if atr > 0 else 0.0
    distance_ratio = abs(candle.close - edge) / edge if edge > 0 else 0.0
    distance_natr = distance_ratio / natr_ratio if natr_ratio > 0 else 0.0
    return {
        "body_ratio": body_ratio,
        "opposite_wick_ratio": opposite_wick_ratio,
        "close_atr": close_atr,
        "distance_natr": distance_natr,
    }


def signal_record(signal: BreakoutSignal, candle: Candle) -> dict[str, Any]:
    record = asdict(signal)
    record["detected_at"] = signal.detected_at.isoformat()
    record["signal_type"] = signal.signal_type or ("breakout" if signal.is_breakout_type else "test")
    record["key"] = signal.key
    record["metrics"] = candle_metrics(signal, candle)
    return record


def collect_one(
    args: tuple[Any, dict[str, Any], str, str, int, int, int],
) -> tuple[str, str, list[dict[str, Any]]]:
    settings, symbol_data, timeframe, cache_path, period_start_ms, period_end_ms, kline_limit = args
    symbol = SymbolInfo(**symbol_data)
    candles = load_candles(Path(cache_path))
    min_len = max(30, min(settings.level_lookback_candles, 60))
    result: list[dict[str, Any]] = []
    for end_index in range(min_len - 1, len(candles)):
        candle = candles[end_index]
        if candle.close_time_ms < period_start_ms:
            continue
        if candle.close_time_ms > period_end_ms:
            break
        window = candles[max(0, end_index + 1 - kline_limit) : end_index + 1]
        signals = detect_breakouts(
            symbol=symbol.symbol,
            timeframe=timeframe,
            candles=window,
            **detector_kwargs(settings, timeframe, symbol),
        )
        result.extend(signal_record(signal, candle) for signal in signals)
    return symbol.symbol, timeframe, result


def allowed(signal: dict[str, Any], settings: Any) -> bool:
    if signal["confidence"] == "confirmed":
        return True
    if not settings.send_unconfirmed_signals:
        return False
    if signal["score"] < settings.min_unconfirmed_signal_score:
        return False
    return signal["touches"] >= settings.required_unconfirmed_touches(signal["level_kind"])


def apply_publication_policy(
    signals: list[dict[str, Any]], settings: Any
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    by_time: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for signal in signals:
        by_time[int(signal["candle_close_time_ms"])].append(signal)
    sent_keys: dict[str, int] = {}
    paused_until: dict[str, int] = {}
    published: list[dict[str, Any]] = []
    drops: Counter[str] = Counter()
    allowed_count = 0
    cooldown_ms = settings.alert_cooldown_minutes * 60_000
    pause_ms = settings.symbol_analysis_pause_minutes * 60_000

    for close_ms in sorted(by_time):
        candidates: list[dict[str, Any]] = []
        for signal in by_time[close_ms]:
            key = signal["key"]
            if pause_ms > 0 and paused_until.get(key, 0) > close_ms:
                drops["signal_key_pause"] += 1
                continue
            if not allowed(signal, settings):
                drops["allowed_filter"] += 1
                continue
            candidates.append(signal)
            allowed_count += 1
        candidates.sort(key=lambda item: item["score"], reverse=True)
        kept = candidates
        if settings.max_signals_per_scan and len(candidates) > settings.max_signals_per_scan:
            kept = candidates[: settings.max_signals_per_scan]
            drops["batch_limit"] += len(candidates) - len(kept)
        sent_signal_keys: set[str] = set()
        for signal in kept:
            key = signal["key"]
            last_sent = sent_keys.get(key)
            if last_sent is not None and close_ms - last_sent < cooldown_ms:
                drops["cooldown"] += 1
                continue
            sent_keys[key] = close_ms
            published.append(signal)
            sent_signal_keys.add(key)
        if pause_ms > 0:
            for key in sent_signal_keys:
                paused_until[key] = close_ms + pause_ms

    return published, {
        "detector_after_distance_score_and_relaxed_candle_quality": len(signals),
        "allowed_before_pause_batch_and_cooldown": allowed_count,
        "published": len(published),
        "drops": dict(drops),
        "sort": "score_desc",
        "pause_scope": "signal_key",
    }


def threshold_funnel(breakouts: list[dict[str, Any]], body_threshold: float, wick: float, close: float) -> dict[str, Any]:
    close_pass = [item for item in breakouts if item["metrics"]["close_atr"] >= close]
    wick_pass = [item for item in close_pass if item["metrics"]["opposite_wick_ratio"] <= wick]
    body_pass = [item for item in wick_pass if item["metrics"]["body_ratio"] >= body_threshold]
    return {
        "published_breakouts": len(breakouts),
        f"close_atr_gte_{close:.2f}": len(close_pass),
        f"opposite_wick_ratio_lte_{wick:.2f}": len(wick_pass),
        f"body_ratio_gte_{body_threshold:.2f}": len(body_pass),
        "final_pass_rate_pct": 100 * len(body_pass) / len(breakouts) if breakouts else 0.0,
    }


def write_jsonl(path: Path, items: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for item in items:
            handle.write(json.dumps(item, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")


def font(size: int) -> ImageFont.ImageFont:
    candidates = (
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/segoeui.ttf"),
        Path("C:/Windows/Fonts/calibri.ttf"),
    )
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size)
    return ImageFont.load_default()


def record_to_signal(record: dict[str, Any]) -> BreakoutSignal:
    values = {key: value for key, value in record.items() if key not in {"metrics", "key"}}
    values["detected_at"] = datetime.fromisoformat(values["detected_at"])
    values["pivot_points"] = tuple(tuple(item) for item in values["pivot_points"])
    return BreakoutSignal(**values)


def cached_window(cache_file: Path, close_ms: int, max_candles: int) -> list[Candle]:
    candles = load_candles(cache_file)
    return [candle for candle in candles if candle.close_time_ms <= close_ms][-max_candles:]


def annotate_chart(png: bytes, label: str) -> Image.Image:
    from io import BytesIO

    source = Image.open(BytesIO(png)).convert("RGB")
    banner_height = 82
    result = Image.new("RGB", (source.width, source.height + banner_height), "#10151f")
    result.paste(source, (0, banner_height))
    draw = ImageDraw.Draw(result)
    draw.multiline_text((18, 8), label, fill="#f3f6fb", font=font(18), spacing=5)
    return result


def render_samples(
    published_breakouts: list[dict[str, Any]],
    cache_by_series: dict[tuple[str, str], Path],
    settings: Any,
    output_dir: Path,
) -> list[dict[str, Any]]:
    rng = random.Random(SAMPLE_SEED)
    boundary = [
        item
        for item in published_breakouts
        if 0.40 <= item["metrics"]["body_ratio"] < 0.50
        and item["metrics"]["opposite_wick_ratio"] <= settings.max_breakout_wick_ratio
        and item["metrics"]["close_atr"] >= settings.min_close_atr_multiplier
    ]
    below = [
        item
        for item in published_breakouts
        if item["metrics"]["body_ratio"] < 0.40
        and item["metrics"]["opposite_wick_ratio"] <= settings.max_breakout_wick_ratio
        and item["metrics"]["close_atr"] >= settings.min_close_atr_multiplier
    ]
    selected = [("pass_040_fail_050", item) for item in rng.sample(boundary, min(10, len(boundary)))]
    selected += [("fail_040", item) for item in rng.sample(below, min(5, len(below)))]
    manifest: list[dict[str, Any]] = []
    for index, (group, record) in enumerate(selected, 1):
        signal = record_to_signal(record)
        cache_file = cache_by_series[(signal.symbol, signal.timeframe)]
        window = cached_window(cache_file, signal.candle_close_time_ms, settings.kline_limit)
        chart = render_signal_chart(window, signal, 0.00000001)
        metrics = record["metrics"]
        label = (
            f"#{index:02d} {signal.symbol} {signal.timeframe} {signal.side} | {group}\n"
            f"body={metrics['body_ratio']:.3f} | wick={metrics['opposite_wick_ratio']:.3f} | "
            f"close={metrics['close_atr']:.3f} ATR | distance_natr={metrics['distance_natr']:.4f} "
            f"<= {settings.max_publish_distance_natr:.1f}"
        )
        image = annotate_chart(chart, label)
        filename = f"{index:02d}_{group}_{signal.symbol}_{signal.timeframe}_{signal.candle_close_time_ms}.png"
        path = output_dir / filename
        image.save(path, format="PNG", optimize=True)
        manifest.append(
            {
                "index": index,
                "group": group,
                "file": str(path.resolve()),
                "symbol": signal.symbol,
                "timeframe": signal.timeframe,
                "close_utc": datetime.fromtimestamp(signal.candle_close_time_ms / 1000, timezone.utc).isoformat(),
                **metrics,
            }
        )
    return manifest


def contact_sheet(samples: list[dict[str, Any]], path: Path) -> None:
    images = [Image.open(item["file"]).convert("RGB") for item in samples]
    if not images:
        return
    thumb_width = 760
    thumbs = []
    for image in images:
        ratio = thumb_width / image.width
        thumbs.append(image.resize((thumb_width, round(image.height * ratio)), Image.Resampling.LANCZOS))
    gap = 14
    cols = 2
    rows = math.ceil(len(thumbs) / cols)
    cell_height = max(image.height for image in thumbs)
    sheet = Image.new("RGB", (cols * thumb_width + (cols + 1) * gap, rows * cell_height + (rows + 1) * gap), "#0b0f17")
    for index, image in enumerate(thumbs):
        x = gap + (index % cols) * (thumb_width + gap)
        y = gap + (index // cols) * (cell_height + gap)
        sheet.paste(image, (x, y))
    sheet.save(path, format="JPEG", quality=88, optimize=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source-run",
        type=Path,
        default=BOT_ROOT / "data" / "backtests" / "recent-14d-20260708-023232",
    )
    parser.add_argument("--cache", type=Path, default=BOT_ROOT / "data" / "backtests" / "cache")
    parser.add_argument(
        "--out",
        type=Path,
        default=BOT_ROOT / "data" / "backtests" / "breakout-candle-calibration-corrected-20260709",
    )
    parser.add_argument("--workers", type=int, default=0)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    charts_dir = args.out / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)

    settings = load_settings()
    summary = json.loads((args.source_run / "summary.json").read_text(encoding="utf-8"))
    period_start_ms = int(datetime.fromisoformat(summary["run"]["period_start_utc"]).timestamp() * 1000)
    period_end_ms = int(datetime.fromisoformat(summary["run"]["period_end_utc"]).timestamp() * 1000)
    legacy_path = args.source_run / "published_signals.jsonl"
    if not legacy_path.exists():
        legacy_path = args.source_run / "DEPRECATED_pre_distance_published_signals_264677.jsonl"
    symbol_data: dict[str, dict[str, Any]] = {}
    with legacy_path.open(encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            symbol_data.setdefault(
                record["symbol"],
                {
                    "symbol": record["symbol"],
                    "tick_size": 0.00000001,
                    "quote_volume": float(record.get("quote_volume_24h") or 0),
                    "price_change_percent": record.get("price_change_24h_pct"),
                    "trades_24h": record.get("trades_24h"),
                },
            )
            if len(symbol_data) == len(summary["run"]["pairs"]):
                break
    (args.out / "symbol_metadata.json").write_text(
        json.dumps(symbol_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    cache_by_series: dict[tuple[str, str], Path] = {}
    tasks = []
    for symbol in summary["run"]["pairs"]:
        for timeframe in summary["run"]["timeframes"]:
            matches = sorted(
                args.cache.glob(f"{symbol}_{timeframe}_*.json"),
                key=lambda item: item.stat().st_mtime,
                reverse=True,
            )
            if not matches:
                raise FileNotFoundError(f"missing cache for {symbol} {timeframe}")
            cache_by_series[(symbol, timeframe)] = matches[0]
            tasks.append(
                (
                    settings,
                    symbol_data[symbol],
                    timeframe,
                    str(matches[0]),
                    period_start_ms,
                    period_end_ms,
                    settings.kline_limit,
                )
            )

    workers = args.workers or min(8, max(1, (os.cpu_count() or 2) - 1))
    signals: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(collect_one, task) for task in tasks]
        for future in as_completed(futures):
            symbol, timeframe, items = future.result()
            signals.extend(items)
            print(f"done {symbol} {timeframe}: signals={len(items)} total={len(signals)}", flush=True)

    published, policy_funnel = apply_publication_policy(signals, settings)
    breakouts = [item for item in published if item["signal_type"] == "breakout"]
    distances = [float(item["metrics"]["distance_natr"]) for item in published]
    violations = [
        item
        for item in published
        if item["metrics"]["distance_natr"] > settings.max_publish_distance_natr + DISTANCE_EPSILON
    ]
    if violations:
        raise AssertionError(
            f"distance_natr validation failed: {len(violations)} signals exceed {settings.max_publish_distance_natr}"
        )

    write_jsonl(args.out / "published_signals_corrected.jsonl", published)
    distribution = {
        "body_ratio": describe([float(item["metrics"]["body_ratio"]) for item in breakouts]),
        "opposite_wick_ratio": describe([float(item["metrics"]["opposite_wick_ratio"]) for item in breakouts]),
        "close_atr": describe([float(item["metrics"]["close_atr"]) for item in breakouts]),
        "distance_natr_all_published": describe(distances),
    }
    reference_tests = {
        "body_0_40_wick_0_25_close_0_12": threshold_funnel(
            breakouts, 0.40, settings.max_breakout_wick_ratio, settings.min_close_atr_multiplier
        ),
        "body_0_50_wick_0_25_close_0_12": threshold_funnel(
            breakouts, 0.50, settings.max_breakout_wick_ratio, settings.min_close_atr_multiplier
        ),
    }
    samples = render_samples(breakouts, cache_by_series, settings, charts_dir)
    contact_sheet_path = args.out / "calibration_samples_contact_sheet.jpg"
    contact_sheet(samples, contact_sheet_path)
    samples_for_report = [
        {**item, "file": str(Path("charts") / Path(item["file"]).name)}
        for item in samples
    ]
    config_path = BOT_ROOT / ".env"
    report = {
        "methodology": {
            "source": "fresh replay of all cached symbol/timeframe series",
            "series_count": len(tasks),
            "period_start_utc": summary["run"]["period_start_utc"],
            "period_end_utc": summary["run"]["period_end_utc"],
            "current_pipeline": [
                "MAX_PUBLISH_DISTANCE_NATR",
                "confidence-based confirmed fix",
                "score-desc sorting",
                "signal_key pause",
                "current per-level-kind touch policy",
            ],
            "calibration_only_relaxation": {
                "min_breakout_body_ratio": 0.0,
                "max_breakout_wick_ratio": 1.0,
                "min_close_atr_multiplier": 0.0,
            },
            "production_config_changed": False,
            "production_env_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
        },
        "production_thresholds_snapshot": {
            "min_breakout_body_ratio": settings.min_breakout_body_ratio,
            "max_breakout_wick_ratio": settings.max_breakout_wick_ratio,
            "min_close_atr_multiplier": settings.min_close_atr_multiplier,
            "max_publish_distance_natr": settings.max_publish_distance_natr,
        },
        "publication_funnel": policy_funnel,
        "published_by_type": dict(Counter(item["signal_type"] for item in published)),
        "published_by_confidence": dict(Counter(item["confidence"] for item in published)),
        "distance_validation": {
            "limit": settings.max_publish_distance_natr,
            "checked": len(published),
            "violations": len(violations),
            "all_pass": not violations,
            "max_observed": max(distances) if distances else None,
        },
        "distributions_published_breakouts": distribution,
        "reference_tests": reference_tests,
        "sample_seed": SAMPLE_SEED,
        "samples": samples_for_report,
        "contact_sheet": contact_sheet_path.name,
    }
    report_path = args.out / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(report_path.resolve()), **report}, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
