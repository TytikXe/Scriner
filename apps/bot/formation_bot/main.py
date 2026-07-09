from __future__ import annotations

import asyncio
import logging
import signal

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramAPIError, TelegramNetworkError
from aiogram.types import BufferedInputFile

from .binance import BinanceClient
from .config import ROOT_DIR, Settings, load_settings
from .database import Database
from .handlers import router
from .logging_setup import setup_logging
from .models import SignalAlert
from .scanner import FormationScanner
from .telegram_client import build_bot


logger = logging.getLogger(__name__)


async def wait_for_bot_info(bot: Bot, stop_event: asyncio.Event):
    attempt = 0
    while not stop_event.is_set():
        try:
            return await bot.get_me()
        except TelegramAPIError as exc:
            attempt += 1
            delay = min(60, 5 * attempt)
            logger.warning("Telegram authorization check failed: %s; retry_seconds=%s", exc, delay)
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass
    raise asyncio.CancelledError


async def send_signal_alert(bot: Bot, chat_id: int, alert: SignalAlert) -> None:
    if alert.chart_png:
        photo = BufferedInputFile(
            alert.chart_png,
            filename=f"{alert.signal.symbol}_{alert.signal.timeframe}.png",
        )
        for attempt in range(1, 4):
            try:
                await bot.send_photo(chat_id, photo, caption=alert.message)
                return
            except TelegramNetworkError:
                if attempt >= 3:
                    logger.exception(
                        "Failed to send chart photo after retries: chat_id=%s symbol=%s timeframe=%s",
                        chat_id,
                        alert.signal.symbol,
                        alert.signal.timeframe,
                    )
                    raise
                delay = attempt * 2
                logger.warning(
                    "Telegram photo send failed, retrying: chat_id=%s symbol=%s timeframe=%s attempt=%s retry_seconds=%s",
                    chat_id,
                    alert.signal.symbol,
                    alert.signal.timeframe,
                    attempt,
                    delay,
                )
                await asyncio.sleep(delay)
            except TelegramAPIError:
                logger.exception(
                    "Failed to send chart photo, falling back to text: chat_id=%s symbol=%s timeframe=%s",
                    chat_id,
                    alert.signal.symbol,
                    alert.signal.timeframe,
                )
                break

    await bot.send_message(chat_id, alert.message)


async def scanner_worker(bot: Bot, db: Database, scanner: FormationScanner, settings: Settings) -> None:
    while True:
        try:
            subscribers = await db.active_subscribers()
            if not subscribers:
                await asyncio.sleep(settings.scan_interval_seconds)
                continue

            results = await scanner.scan_once()
            for alert in results:
                signal = alert.signal
                if not await db.should_send_signal(signal.key, settings.alert_cooldown_minutes):
                    continue

                sent = 0
                for chat_id in subscribers:
                    try:
                        await send_signal_alert(bot, chat_id, alert)
                        sent += 1
                    except TelegramAPIError:
                        logger.exception("Failed to send Telegram alert: chat_id=%s", chat_id)
                if sent:
                    await db.mark_signal_sent(signal.key)
                    logger.info("Alert sent: symbol=%s timeframe=%s recipients=%s", signal.symbol, signal.timeframe, sent)
        except asyncio.CancelledError:
            logger.info("Scanner worker stopped")
            raise
        except Exception:
            logger.exception("Unexpected scanner error")

        await asyncio.sleep(settings.scan_interval_seconds)


async def main() -> None:
    settings = load_settings()
    setup_logging(settings.log_level, ROOT_DIR)
    logger.info("Starting formation Telegram bot")

    db = Database(settings.db_path)
    await db.init()

    bot = build_bot(settings.telegram_bot_token)
    dp = Dispatcher(db=db, settings=settings)
    dp.include_router(router)

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass

    async with BinanceClient(settings.binance_base_url) as client:
        scanner = FormationScanner(client, settings)
        worker: asyncio.Task | None = None
        try:
            bot_info = await wait_for_bot_info(bot, stop_event)
            logger.info("Telegram bot authorized: username=%s", bot_info.username)
            polling = asyncio.create_task(dp.start_polling(bot))
            await asyncio.sleep(0)
            worker = asyncio.create_task(scanner_worker(bot, db, scanner, settings))
            stop_waiter = asyncio.create_task(stop_event.wait())
            done, pending = await asyncio.wait(
                {polling, stop_waiter},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            for task in done:
                task.result()
        finally:
            if worker:
                worker.cancel()
                await asyncio.gather(worker, return_exceptions=True)
            await bot.session.close()
            logger.info("Formation Telegram bot stopped")


if __name__ == "__main__":
    asyncio.run(main())
