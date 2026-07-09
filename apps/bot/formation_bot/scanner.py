from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import replace

from .binance import BinanceClient
from .chart_renderer import render_signal_chart
from .config import Settings
from .formations import detect_breakouts, format_signal_message, timeframe_minutes
from .models import BreakoutSignal, Candle, SignalAlert, SymbolInfo


logger = logging.getLogger(__name__)


class FormationScanner:
    def __init__(self, client: BinanceClient, settings: Settings) -> None:
        self.client = client
        self.settings = settings
        self._last_slots: dict[str, int] = {}
        self._semaphore = asyncio.Semaphore(settings.max_concurrent_kline_requests)
        self._tick_sizes: dict[str, float] = {}
        self._signal_key_paused_until: dict[str, float] = {}
        if settings.skip_initial_scan:
            self._last_slots = {
                timeframe: int(time.time() // self._timeframe_scan_seconds(timeframe))
                for timeframe in settings.timeframes
            }

    def _timeframe_scan_seconds(self, timeframe: str) -> int:
        cadence_minutes = min(timeframe_minutes(timeframe), self.settings.max_signal_age_minutes)
        return max(1, cadence_minutes) * 60

    def _timeframe_due(self, timeframe: str) -> bool:
        slot_seconds = self._timeframe_scan_seconds(timeframe)
        slot = int(time.time() // slot_seconds)
        if self._last_slots.get(timeframe) == slot:
            return False
        self._last_slots[timeframe] = slot
        return True

    def _filter_paused_signals(self, results: list[SignalAlert]) -> list[SignalAlert]:
        if self.settings.symbol_analysis_pause_minutes <= 0 or not self._signal_key_paused_until:
            return results

        now = time.time()
        expired = [signal_key for signal_key, paused_until in self._signal_key_paused_until.items() if paused_until <= now]
        for signal_key in expired:
            self._signal_key_paused_until.pop(signal_key, None)

        active_signals = [alert for alert in results if self._signal_key_paused_until.get(alert.signal.key, 0) <= now]
        skipped = len(results) - len(active_signals)
        if skipped:
            skipped_keys = {alert.signal.key for alert in results if self._signal_key_paused_until.get(alert.signal.key, 0) > now}
            logger.info("Paused signal keys skipped: count=%s unique_keys=%s", skipped, len(skipped_keys))
        return active_signals

    def _filter_allowed_symbols(self, symbols: list[SymbolInfo]) -> list[SymbolInfo]:
        if not self.settings.signal_symbol_allowlist:
            return symbols

        allowed = set(self.settings.signal_symbol_allowlist)
        active_symbols = [symbol for symbol in symbols if symbol.symbol.upper() in allowed]
        skipped = len(symbols) - len(active_symbols)
        missing = sorted(allowed - {symbol.symbol.upper() for symbol in active_symbols})
        logger.info(
            "Signal allowlist applied: active=%s skipped=%s missing_or_illiquid=%s",
            len(active_symbols),
            skipped,
            ",".join(missing) if missing else "-",
        )
        return active_symbols

    def _pause_signal_keys(self, results: list[SignalAlert]) -> None:
        if self.settings.symbol_analysis_pause_minutes <= 0 or not results:
            return

        paused_until = time.time() + self.settings.symbol_analysis_pause_minutes * 60
        signal_keys = {alert.signal.key for alert in results}
        for signal_key in signal_keys:
            self._signal_key_paused_until[signal_key] = paused_until
        logger.info(
            "Signal keys paused after signals: count=%s pause_minutes=%s",
            len(signal_keys),
            self.settings.symbol_analysis_pause_minutes,
        )

    def _filter_allowed_signals(self, results: list[SignalAlert]) -> list[SignalAlert]:
        if self.settings.send_unconfirmed_signals:
            filtered = [
                alert
                for alert in results
                if alert.signal.confidence == "confirmed"
                or (
                    alert.signal.confidence == "low_confidence"
                    and alert.signal.score >= self.settings.min_unconfirmed_signal_score
                    and alert.signal.touches >= self.settings.required_unconfirmed_touches(alert.signal.level_kind)
                )
            ]
            skipped = len(results) - len(filtered)
            if skipped:
                logger.info("Weak unconfirmed signals skipped: count=%s", skipped)
            return filtered

        confirmed_confidence = [alert for alert in results if alert.signal.confidence == "confirmed"]
        skipped = len(results) - len(confirmed_confidence)
        if skipped:
            logger.info("Unconfirmed signals skipped: count=%s", skipped)
        return confirmed_confidence

    def _sort_signals_for_batch(self, results: list[SignalAlert]) -> list[SignalAlert]:
        return sorted(results, key=lambda alert: alert.signal.score, reverse=True)

    @staticmethod
    def _close_return_correlation(first: list[Candle], second: list[Candle]) -> float | None:
        limit = min(len(first), len(second))
        if limit < 4:
            return None
        first_returns = [
            (first[index].close - first[index - 1].close) / first[index - 1].close
            for index in range(len(first) - limit + 1, len(first))
            if first[index - 1].close > 0
        ]
        second_returns = [
            (second[index].close - second[index - 1].close) / second[index - 1].close
            for index in range(len(second) - limit + 1, len(second))
            if second[index - 1].close > 0
        ]
        limit = min(len(first_returns), len(second_returns))
        if limit < 3:
            return None
        first_returns = first_returns[-limit:]
        second_returns = second_returns[-limit:]
        first_mean = sum(first_returns) / limit
        second_mean = sum(second_returns) / limit
        covariance = sum((left - first_mean) * (right - second_mean) for left, right in zip(first_returns, second_returns))
        first_var = sum((value - first_mean) ** 2 for value in first_returns)
        second_var = sum((value - second_mean) ** 2 for value in second_returns)
        denominator = math.sqrt(first_var * second_var)
        if denominator <= 0:
            return None
        return max(-1.0, min(1.0, covariance / denominator))

    async def _enrich_signal(
        self,
        signal: BreakoutSignal,
        symbol: SymbolInfo,
        candles: list[Candle],
        timeframe: str,
    ) -> BreakoutSignal:
        funding_rate_pct: float | None = None
        btc_correlation_1h: float | None = None
        try:
            async with self._semaphore:
                funding_task = asyncio.create_task(self.client.funding_rate_pct(symbol.symbol))
                if symbol.symbol == "BTCUSDT":
                    symbol_1h_task = None
                elif timeframe == "1h":
                    symbol_1h_task = None
                else:
                    symbol_1h_task = asyncio.create_task(self.client.klines(symbol.symbol, "1h", 80))
                btc_task = None if symbol.symbol == "BTCUSDT" else asyncio.create_task(self.client.klines("BTCUSDT", "1h", 80))

                tasks = [funding_task]
                if symbol_1h_task:
                    tasks.append(symbol_1h_task)
                if btc_task:
                    tasks.append(btc_task)
                results = await asyncio.gather(*tasks, return_exceptions=True)

            funding_result = results[0]
            if not isinstance(funding_result, Exception):
                funding_rate_pct = funding_result

            if symbol.symbol == "BTCUSDT":
                btc_correlation_1h = 1.0
            elif btc_task:
                offset = 1
                if symbol_1h_task:
                    symbol_1h_result = results[offset]
                    offset += 1
                    symbol_1h = symbol_1h_result if not isinstance(symbol_1h_result, Exception) else []
                else:
                    symbol_1h = candles[-80:]
                btc_result = results[offset]
                btc_1h = btc_result if not isinstance(btc_result, Exception) else []
                if isinstance(symbol_1h, list) and isinstance(btc_1h, list):
                    btc_correlation_1h = self._close_return_correlation(symbol_1h, btc_1h)
        except Exception:
            logger.warning("Failed to enrich signal metadata: symbol=%s timeframe=%s", symbol.symbol, timeframe, exc_info=True)

        return replace(
            signal,
            funding_rate_pct=funding_rate_pct,
            price_change_24h_pct=symbol.price_change_percent,
            quote_volume_24h=symbol.quote_volume,
            trades_24h=symbol.trades_24h,
            btc_correlation_1h=btc_correlation_1h,
        )

    async def scan_once(self) -> list[SignalAlert]:
        symbols = await self.client.futures_symbols(self.settings.max_symbols, self.settings.min_quote_volume_24h)
        self._tick_sizes.update({item.symbol: item.tick_size for item in symbols})
        symbols = self._filter_allowed_symbols(symbols)

        due_timeframes = [timeframe for timeframe in self.settings.timeframes if self._timeframe_due(timeframe)]
        if not due_timeframes:
            return []

        logger.info(
            "Starting formation scan: symbols=%s min_quote_volume_24h=%.0f timeframes=%s",
            len(symbols),
            self.settings.min_quote_volume_24h,
            ",".join(due_timeframes),
        )

        tasks = [
            self._scan_symbol_timeframe(symbol, timeframe)
            for timeframe in due_timeframes
            for symbol in symbols
        ]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        results: list[SignalAlert] = []
        errors = 0
        for item in raw_results:
            if isinstance(item, Exception):
                errors += 1
                continue
            if item:
                results.extend(item)

        if errors:
            logger.warning("Formation scan completed with request errors: errors=%s", errors)
        results = self._filter_paused_signals(results)
        results = self._filter_allowed_signals(results)
        results = self._sort_signals_for_batch(results)
        if self.settings.max_signals_per_scan and len(results) > self.settings.max_signals_per_scan:
            logger.warning(
                "Signal batch limited: detected=%s sent_candidates=%s",
                len(results),
                self.settings.max_signals_per_scan,
            )
            results = results[: self.settings.max_signals_per_scan]
        self._pause_signal_keys(results)
        logger.info("Formation scan completed: signals=%s", len(results))
        return results

    def _zone_ttl_bars(self, timeframe: str) -> int:
        return self.settings.zone_ttl_bars.get(timeframe, self.settings.zone_ttl_candles)

    async def _scan_symbol_timeframe(self, symbol: SymbolInfo, timeframe: str) -> list[SignalAlert]:
        async with self._semaphore:
            try:
                candles = await self.client.klines(symbol.symbol, timeframe, self.settings.kline_limit)
            except Exception as exc:
                logger.warning("Failed to fetch candles: symbol=%s timeframe=%s error=%s", symbol.symbol, timeframe, exc)
                return []

        if not candles:
            logger.warning("Empty candle response: symbol=%s timeframe=%s", symbol.symbol, timeframe)
            return []

        signals = detect_breakouts(
            symbol=symbol.symbol,
            timeframe=timeframe,
            candles=candles,
            lookback=self.settings.level_lookback_candles,
            min_touches=self.settings.zone_confirmation_touches,
            tolerance_pct=self.settings.level_tolerance_pct,
            zone_atr_multiplier=self.settings.zone_atr_multiplier,
            cluster_tolerance_natr_k=self.settings.cluster_tolerance_natr_k,
            breakout_distance_pct=self.settings.breakout_distance_pct,
            min_breakout_body_ratio=self.settings.min_breakout_body_ratio,
            min_volume_multiplier=self.settings.min_volume_multiplier,
            min_probe_volume_multiplier=self.settings.min_probe_volume_multiplier,
            level_probe_distance_pct=self.settings.level_probe_distance_pct,
            min_close_atr_multiplier=self.settings.min_close_atr_multiplier,
            min_close_distance_pct=self.settings.min_close_distance_pct,
            max_breakout_wick_ratio=self.settings.max_breakout_wick_ratio,
            max_pre_breakout_range_pct=self.settings.max_pre_breakout_range_pct,
            level_approach_distance_pct=self.settings.level_approach_distance_pct,
            level_approach_max_width_pct=self.settings.level_approach_max_width_pct,
            min_level_approach_gap_atr_multiplier=self.settings.min_level_approach_gap_atr_multiplier,
            level_min_spacing_candles=self.settings.level_min_spacing_candles,
            min_level_span_candles=self.settings.min_level_span_candles,
            min_level_age_candles=self.settings.min_level_age_candles,
            zone_ttl_candles=self._zone_ttl_bars(timeframe),
            min_retreat_atr_multiplier=self.settings.min_retreat_atr_multiplier,
            impulse_threshold_atr=self.settings.impulse_threshold_atr,
            impulse_lookback_candles=self.settings.impulse_search_window,
            min_natr_pct=self.settings.min_natr_pct,
            natr_period=self.settings.natr_period,
            fractal_n=self.settings.fractal_n,
            live_window=self.settings.live_window,
            low_confidence_penalty=self.settings.low_confidence_penalty,
            approach_threshold_k=self.settings.approach_threshold_k,
            cooldown_bars=self.settings.cooldown_bars,
            volume_24h_usd=symbol.quote_volume,
            min_24h_volume_usd=self.settings.min_24h_volume_usd,
            min_score_to_publish=self.settings.min_score_to_publish,
            max_publish_distance_natr=self.settings.max_publish_distance_natr,
            score_weights=self.settings.score_weights,
        )
        if not signals:
            return []

        alerts: list[SignalAlert] = []
        max_signal_age_ms = self.settings.max_signal_age_minutes * 60_000
        for signal in signals:
            signal_age_ms = int(time.time() * 1000) - signal.candle_close_time_ms
            if signal_age_ms > max_signal_age_ms:
                logger.info(
                    "Stale signal skipped: symbol=%s timeframe=%s age_minutes=%.1f max_age_minutes=%s",
                    signal.symbol,
                    signal.timeframe,
                    signal_age_ms / 60_000,
                    self.settings.max_signal_age_minutes,
                )
                continue

            signal = await self._enrich_signal(signal, symbol, candles, timeframe)
            swing_price = signal.zone_upper if signal.side == "resistance" else signal.zone_lower
            logger.info(
                "Swing signal detected: symbol=%s timeframe=%s side=%s signal_type=%s confidence=%s swing_price=%.12g touches=%s score=%.1f natr=%.2f kind=%s",
                signal.symbol,
                signal.timeframe,
                signal.side,
                signal.signal_type,
                signal.confidence,
                swing_price,
                signal.touches,
                signal.score,
                signal.natr_pct,
                signal.level_kind,
            )
            chart_png: bytes | None = None
            try:
                chart_png = render_signal_chart(candles, signal, symbol.tick_size)
            except Exception:
                logger.exception("Failed to render signal chart: symbol=%s timeframe=%s", signal.symbol, signal.timeframe)
            alerts.append(SignalAlert(signal=signal, message=format_signal_message(signal, symbol.tick_size), chart_png=chart_png))
        return alerts
