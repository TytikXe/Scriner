from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.types import ErrorEvent, Message

from .config import Settings
from .database import Database


logger = logging.getLogger(__name__)
router = Router()


@router.message(Command("start"))
async def start_command(message: Message, db: Database) -> None:
    if not message.chat:
        return
    await db.subscribe(message.chat.id)
    logger.info("Subscriber enabled: chat_id=%s", message.chat.id)
    await message.answer("Подписка включена. Буду присылать пробои уровней по Binance Futures.")


@router.message(Command("stop"))
async def stop_command(message: Message, db: Database) -> None:
    if not message.chat:
        return
    await db.unsubscribe(message.chat.id)
    logger.info("Subscriber disabled: chat_id=%s", message.chat.id)
    await message.answer("Подписка отключена.")


@router.message(Command("status"))
async def status_command(message: Message, db: Database, settings: Settings) -> None:
    if not message.chat:
        return
    subscribed = await db.is_subscribed(message.chat.id)
    status = "включена" if subscribed else "выключена"
    await message.answer(
        "Статус подписки: "
        f"{status}\n"
        f"Биржа: Binance Futures\n"
        f"Таймфреймы: {', '.join(settings.timeframes)}\n"
        f"Объём 24ч от: {settings.min_quote_volume_24h:,.0f} USDT\n"
        f"Монет в скане: {'все' if settings.max_symbols == 0 else settings.max_symbols}"
    )


@router.message(F.text)
async def text_message(message: Message) -> None:
    await message.answer("Команды: /start, /stop, /status")


@router.error()
async def errors_handler(event: ErrorEvent, bot: Bot) -> bool:
    exception = event.exception
    if isinstance(exception, TelegramAPIError):
        logger.exception("Telegram API error")
    else:
        logger.exception("Unexpected handler error")
    return True
