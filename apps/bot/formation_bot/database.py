from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite


logger = logging.getLogger(__name__)


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    async def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            async with aiosqlite.connect(self.path) as db:
                await db.execute(
                    """
                    CREATE TABLE IF NOT EXISTS subscribers (
                        chat_id INTEGER PRIMARY KEY,
                        active INTEGER NOT NULL DEFAULT 1,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                await db.execute(
                    """
                    CREATE TABLE IF NOT EXISTS sent_signals (
                        signal_key TEXT PRIMARY KEY,
                        sent_at TEXT NOT NULL
                    )
                    """
                )
                await db.commit()
        except aiosqlite.Error:
            logger.exception("Database initialization failed")
            raise

    async def subscribe(self, chat_id: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        try:
            async with aiosqlite.connect(self.path) as db:
                await db.execute(
                    """
                    INSERT INTO subscribers(chat_id, active, created_at, updated_at)
                    VALUES (?, 1, ?, ?)
                    ON CONFLICT(chat_id) DO UPDATE SET active = 1, updated_at = excluded.updated_at
                    """,
                    (chat_id, now, now),
                )
                await db.commit()
        except aiosqlite.Error:
            logger.exception("Failed to subscribe chat")
            raise

    async def unsubscribe(self, chat_id: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        try:
            async with aiosqlite.connect(self.path) as db:
                await db.execute(
                    "UPDATE subscribers SET active = 0, updated_at = ? WHERE chat_id = ?",
                    (now, chat_id),
                )
                await db.commit()
        except aiosqlite.Error:
            logger.exception("Failed to unsubscribe chat")
            raise

    async def active_subscribers(self) -> list[int]:
        try:
            async with aiosqlite.connect(self.path) as db:
                cursor = await db.execute("SELECT chat_id FROM subscribers WHERE active = 1")
                rows = await cursor.fetchall()
                return [int(row[0]) for row in rows]
        except aiosqlite.Error:
            logger.exception("Failed to read subscribers")
            raise

    async def is_subscribed(self, chat_id: int) -> bool:
        try:
            async with aiosqlite.connect(self.path) as db:
                cursor = await db.execute("SELECT active FROM subscribers WHERE chat_id = ?", (chat_id,))
                row = await cursor.fetchone()
                return bool(row and row[0])
        except aiosqlite.Error:
            logger.exception("Failed to read subscriber status")
            raise

    async def should_send_signal(self, signal_key: str, cooldown_minutes: int) -> bool:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=cooldown_minutes)
        try:
            async with aiosqlite.connect(self.path) as db:
                cursor = await db.execute("SELECT sent_at FROM sent_signals WHERE signal_key = ?", (signal_key,))
                row = await cursor.fetchone()
                if not row:
                    return True
                sent_at = datetime.fromisoformat(row[0])
                return sent_at < cutoff
        except (aiosqlite.Error, ValueError):
            logger.exception("Failed to check signal cooldown")
            raise

    async def mark_signal_sent(self, signal_key: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        try:
            async with aiosqlite.connect(self.path) as db:
                await db.execute(
                    """
                    INSERT INTO sent_signals(signal_key, sent_at)
                    VALUES (?, ?)
                    ON CONFLICT(signal_key) DO UPDATE SET sent_at = excluded.sent_at
                    """,
                    (signal_key, now),
                )
                await db.execute(
                    "DELETE FROM sent_signals WHERE sent_at < ?",
                    ((datetime.now(timezone.utc) - timedelta(days=7)).isoformat(),),
                )
                await db.commit()
        except aiosqlite.Error:
            logger.exception("Failed to mark signal as sent")
            raise
