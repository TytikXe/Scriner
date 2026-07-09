from __future__ import annotations

import argparse
import asyncio
import logging
from logging import FileHandler
import sys
import time
from dataclasses import replace
from pathlib import Path

BOT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(BOT_ROOT))

from formation_bot.binance import BinanceClient
from formation_bot.config import ROOT_DIR, load_settings
from formation_bot.logging_setup import setup_logging
from formation_bot.scanner import FormationScanner


logger = logging.getLogger(__name__)


def configure_stdio_encoding() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8", errors="replace")


def add_utf8_log_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logging.getLogger().addHandler(handler)


def publish_distance_natr(signal) -> float:
    signal_type = signal.signal_type or ("breakout" if signal.is_breakout_type else "test")
    if signal_type == "breakout":
        edge = signal.zone_upper if signal.side == "resistance" else signal.zone_lower
    else:
        edge = signal.zone_lower if signal.side == "resistance" else signal.zone_upper
    if edge <= 0:
        return 0.0
    distance_ratio = abs(signal.price - edge) / edge
    return distance_ratio / max(signal.natr_pct / 100, 1e-12)


async def run(duration_minutes: float, sleep_seconds: float, once: bool, log_file: Path | None) -> int:
    settings = load_settings()
    settings = replace(settings, skip_initial_scan=False)
    setup_logging(settings.log_level, ROOT_DIR)
    if log_file:
        add_utf8_log_file(log_file)
    deadline = time.monotonic() + max(0.0, duration_minutes) * 60
    scans = 0
    signals = 0
    violations = 0
    logger.info(
        "Starting dry-run scanner: duration_minutes=%.2f sleep_seconds=%.1f max_publish_distance_natr=%.2f",
        duration_minutes,
        sleep_seconds,
        settings.max_publish_distance_natr,
    )
    async with BinanceClient(settings.binance_base_url) as client:
        scanner = FormationScanner(client, settings)
        while True:
            alerts = await scanner.scan_once()
            scans += 1
            signals += len(alerts)
            for alert in alerts:
                distance = publish_distance_natr(alert.signal)
                if distance > settings.max_publish_distance_natr:
                    violations += 1
                    logger.error(
                        "Dry-run publish distance violation: symbol=%s timeframe=%s distance_natr=%.4f limit=%.4f price=%.12g zone_low=%.12g zone_high=%.12g",
                        alert.signal.symbol,
                        alert.signal.timeframe,
                        distance,
                        settings.max_publish_distance_natr,
                        alert.signal.price,
                        alert.signal.zone_lower,
                        alert.signal.zone_upper,
                    )
            logger.info(
                "Dry-run scan completed: scan=%s signals=%s total_signals=%s violations=%s",
                scans,
                len(alerts),
                signals,
                violations,
            )
            if once or time.monotonic() >= deadline:
                break
            await asyncio.sleep(max(1.0, sleep_seconds))
    logger.info("Dry-run scanner finished: scans=%s signals=%s violations=%s", scans, signals, violations)
    return 1 if violations else 0


def main() -> None:
    configure_stdio_encoding()
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration-minutes", type=float, default=5.0)
    parser.add_argument("--sleep-seconds", type=float, default=60.0)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--log-file", type=Path, default=ROOT_DIR / "logs" / "dry-run-scanner.log")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args.duration_minutes, args.sleep_seconds, args.once, args.log_file)))


if __name__ == "__main__":
    main()
