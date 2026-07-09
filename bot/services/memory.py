"""SQLite-память: история диалогов, контекст, настройки пользователя."""

import asyncio
import json
import logging
from datetime import datetime, timezone

import aiosqlite

from bot.config import MEMORY_DB_PATH, MAX_HISTORY_MESSAGES

logger = logging.getLogger(__name__)


class Memory:
    """Хранит историю диалогов и настройки пользователей."""

    def __init__(self, db_path: str = str(MEMORY_DB_PATH)):
        self.db_path = db_path
        self._lock = asyncio.Lock()

    async def init(self):
        """Создать таблицы, если их нет."""
        MEMORY_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    role TEXT NOT NULL,  -- 'user' или 'assistant'
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS user_settings (
                    user_id INTEGER PRIMARY KEY,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS conversation_summary (
                    user_id INTEGER PRIMARY KEY,
                    summary TEXT NOT NULL,
                    message_count INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)
            await db.commit()
        logger.info("Memory: база данных готова (%s)", self.db_path)

    async def add_message(self, user_id: int, role: str, content: str):
        """Добавить сообщение в историю."""
        async with self._lock, aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO messages (user_id, role, content) VALUES (?, ?, ?)",
                (user_id, role, content),
            )
            await db.commit()

    async def get_history(self, user_id: int, limit: int = MAX_HISTORY_MESSAGES) -> list[dict]:
        """Получить последние N сообщений пользователя."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT role, content FROM messages WHERE user_id = ? "
                "ORDER BY id DESC LIMIT ?",
                (user_id, limit),
            )
            rows = await cursor.fetchall()
        return [{"role": r, "content": c} for r, c in reversed(rows)]

    async def clear_history(self, user_id: int):
        """Удалить всю историю пользователя."""
        async with self._lock, aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM messages WHERE user_id = ?", (user_id,))
            await db.execute("DELETE FROM conversation_summary WHERE user_id = ?", (user_id,))
            await db.commit()

    async def save_user_settings(self, user_id: int, provider: str, model: str):
        """Сохранить настройки LLM для пользователя."""
        async with self._lock, aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO user_settings (user_id, provider, model, updated_at) "
                "VALUES (?, ?, ?, datetime('now')) "
                "ON CONFLICT(user_id) DO UPDATE SET provider=excluded.provider, "
                "model=excluded.model, updated_at=datetime('now')",
                (user_id, provider, model),
            )
            await db.commit()

    async def get_user_settings(self, user_id: int) -> dict | None:
        """Получить настройки пользователя."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT provider, model FROM user_settings WHERE user_id = ?",
                (user_id,),
            )
            row = await cursor.fetchone()
        if row:
            return {"provider": row[0], "model": row[1]}
        return None

    async def get_summary(self, user_id: int) -> str | None:
        """Получить саммари предыдущего диалога."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT summary FROM conversation_summary WHERE user_id = ?",
                (user_id,),
            )
            row = await cursor.fetchone()
        return row[0] if row else None

    async def save_summary(self, user_id: int, summary: str, message_count: int):
        """Сохранить саммари диалога."""
        async with self._lock, aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO conversation_summary (user_id, summary, message_count, updated_at) "
                "VALUES (?, ?, ?, datetime('now')) "
                "ON CONFLICT(user_id) DO UPDATE SET summary=excluded.summary, "
                "message_count=excluded.message_count, updated_at=datetime('now')",
                (user_id, summary, message_count),
            )
            await db.commit()
