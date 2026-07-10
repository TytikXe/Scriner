from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

BOT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = BOT_ROOT.parents[1]
sys.path.insert(0, str(BOT_ROOT))

import backtest_recent_binance as bt
from formation_bot.config import load_settings


START = datetime(2026, 7, 2, 21, 0, 0, tzinfo=timezone.utc)
END = datetime(2026, 7, 9, 20, 59, 59, 999000, tzinfo=timezone.utc)
START_MS = int(START.timestamp() * 1000)
END_MS = int(END.timestamp() * 1000)


def signal_record(signal: object) -> dict[str, object]:
    return {
        "symbol": signal.symbol,
        "timeframe": signal.timeframe,
        "close_ms": signal.candle_close_time_ms,
        "type": signal.signal_type or ("breakout" if signal.is_breakout_type else "test"),
        "is_breakout_type": signal.is_breakout_type,
        "confidence": signal.confidence,
        "score": signal.score,
        "natr_pct": signal.natr_pct,
        "touches": signal.touches,
        "level_kind": signal.level_kind,
        "side": signal.side,
        "zone_low": signal.zone_lower,
        "zone_high": signal.zone_upper,
        "key": signal.key,
        "source": "fresh_20260703_20260709",
    }


async def run(args: argparse.Namespace) -> None:
    settings = load_settings()
    out_dir = args.out.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    series_dir = out_dir / "series"
    series_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = BOT_ROOT / "data" / "backtests" / "fresh_week_cache_20260703_20260709"
    candidates_path = out_dir / "fresh_detector_candidates_20260703_20260709.jsonl"
    summary_path = out_dir / "fresh_detector_run_summary.json"

    workers = args.workers or min(8, max(1, (os.cpu_count() or 2) - 1))
    decision_summary: dict[str, object] = {
        "candidate_decisions_total": 0,
        "debug_published_decisions_before_publication_rules": 0,
        "rejected_total": 0,
        "rejected_by_reason": Counter(),
    }

    async with bt.BinanceHistory(settings.binance_base_url, cache_dir, args.refresh_cache) as history:
        min_quote_volume_24h = (
            args.min_quote_volume_24h
            if args.min_quote_volume_24h is not None
            else settings.min_quote_volume_24h
        )
        symbols = await history.symbols(
            settings.max_symbols,
            min_quote_volume_24h,
            settings.signal_symbol_allowlist,
        )
        print(
            "fresh_week_run",
            f"period={START.isoformat()}..{END.isoformat()}",
            f"symbols={len(symbols)}",
            f"min_quote_volume_24h={min_quote_volume_24h}",
            f"timeframes={','.join(settings.timeframes)}",
            f"workers={workers}",
            flush=True,
        )
        semaphore = asyncio.Semaphore(settings.max_concurrent_kline_requests)
        loop = asyncio.get_running_loop()

        async def process(executor: ProcessPoolExecutor, symbol: object, timeframe: str) -> None:
            series_path = series_dir / f"{symbol.symbol}_{timeframe}.jsonl"
            summary_piece_path = series_dir / f"{symbol.symbol}_{timeframe}.summary.json"
            if series_path.exists() and summary_piece_path.exists() and not args.overwrite_series:
                return
            tf_ms = bt.timeframe_minutes(timeframe) * 60_000
            warmup_ms = (settings.kline_limit + 5) * tf_ms
            async with semaphore:
                candles = await history.klines(symbol.symbol, timeframe, START_MS - warmup_ms, END_MS)
            raw, partial = await loop.run_in_executor(
                executor,
                bt.run_backtest_for_series,
                settings,
                symbol,
                timeframe,
                candles,
                START_MS,
                END_MS,
            )
            with series_path.open("w", encoding="utf-8") as handle:
                for signal in sorted(raw, key=lambda item: (item.candle_close_time_ms, item.key)):
                    handle.write(json.dumps(signal_record(signal), ensure_ascii=False, separators=(",", ":")) + "\n")
            summary_piece_path.write_text(
                json.dumps(
                    {
                        "symbol": symbol.symbol,
                        "timeframe": timeframe,
                        "candles": len(candles),
                        "raw": len(raw),
                        "partial_summary": partial,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            print(
                f"done {symbol.symbol} {timeframe}: candles={len(candles)} raw={len(raw)} "
                f"decisions={partial['candidate_decisions_total']}",
                flush=True,
            )

        with ProcessPoolExecutor(max_workers=workers) as executor:
            tasks = [process(executor, symbol, timeframe) for symbol in symbols for timeframe in settings.timeframes]
            batch_size = max(workers, settings.max_concurrent_kline_requests)
            for index in range(0, len(tasks), batch_size):
                await asyncio.gather(*tasks[index : index + batch_size])
                completed = len(list(series_dir.glob("*.jsonl")))
                print(
                    f"batch_complete {min(index + batch_size, len(tasks))}/{len(tasks)} completed_series={completed}",
                    flush=True,
                )

    all_records: list[dict[str, object]] = []
    for series_path in sorted(series_dir.glob("*.jsonl")):
        with series_path.open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    all_records.append(json.loads(line))
    all_records.sort(key=lambda item: (int(item["close_ms"]), str(item["symbol"]), str(item["timeframe"]), str(item["key"])))
    with candidates_path.open("w", encoding="utf-8") as handle:
        for record in all_records:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")

    for summary_piece_path in sorted(series_dir.glob("*.summary.json")):
        piece = json.loads(summary_piece_path.read_text(encoding="utf-8"))
        bt.merge_decision_summary(decision_summary, piece["partial_summary"])
    by_day_utc = Counter(datetime.fromtimestamp(int(record["close_ms"]) / 1000, timezone.utc).date().isoformat() for record in all_records)
    decision_summary["rejected_by_reason"] = dict(decision_summary["rejected_by_reason"])
    summary = {
        "period_start_utc": START.isoformat(),
        "period_end_utc": END.isoformat(),
        "settings": {
            "timeframes": list(settings.timeframes),
            "min_quote_volume_24h": min_quote_volume_24h,
            "production_min_quote_volume_24h": settings.min_quote_volume_24h,
            "kline_limit": settings.kline_limit,
            "min_breakout_body_ratio": settings.min_breakout_body_ratio,
            "min_unconfirmed_signal_score": settings.min_unconfirmed_signal_score,
            "min_score_to_publish": settings.min_score_to_publish,
            "max_publish_distance_natr": settings.max_publish_distance_natr,
            "max_signals_per_scan": settings.max_signals_per_scan,
            "alert_cooldown_minutes": settings.alert_cooldown_minutes,
            "symbol_analysis_pause_minutes": settings.symbol_analysis_pause_minutes,
            "score_weights": settings.score_weights,
        },
        "series_completed": len(list(series_dir.glob("*.jsonl"))),
        "symbols_count": len({record["symbol"] for record in all_records}),
        "symbols_with_candidates": sorted({str(record["symbol"]) for record in all_records}),
        "raw_total": len(all_records),
        "raw_by_day_utc": dict(sorted(by_day_utc.items())),
        "decision_summary": decision_summary,
        "candidate_file": str(candidates_path),
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parent / "fresh_baseline",
    )
    parser.add_argument("--workers", type=int, default=0)
    parser.add_argument("--refresh-cache", action="store_true")
    parser.add_argument("--overwrite-series", action="store_true")
    parser.add_argument("--min-quote-volume-24h", type=float, default=None)
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
