"""Продвинутая SQLite-память: история диалогов + факты/обучения с promote_learning.

Архитектура как в Kai 9000:
- messages — история диалогов
- user_settings — настройки пользователя
- conversation_summary — саммари длинных диалогов
- memories — факты, предпочтения, обучения с hitCount и promote
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import aiosqlite

from bot.config import MEMORY_DB_PATH, MAX_HISTORY_MESSAGES

logger = logging.getLogger(__name__)

# ─── Data classes ───────────────────────────────────────────────────────────

PROMOTION_THRESHOLD = 5  # hitCount >= 5 → promote в soul


@dataclass
class MemoryItem:
    """Одна запись памяти (факт, предпочтение, обучение)."""
    key: str
    content: str
    category: str = "LEARNING"  # FACT | PREFERENCE | LEARNING | ERROR
    hit_count: int = 0
    promoted: bool = False
    source: str = ""
    created_at: str = ""
    updated_at: str = ""


# ─── Memory класс ───────────────────────────────────────────────────────────

class Memory:
    """Хранит историю диалогов, настройки, саммари и продвинутую память."""

    def __init__(self, db_path: str = str(MEMORY_DB_PATH)):
        self.db_path = db_path
        self._lock = asyncio.Lock()

    async def init(self):
        """Создать таблицы, если их нет."""
        MEMORY_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA journal_mode=WAL")
            # История сообщений
            await db.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)
            # Настройки пользователя
            await db.execute("""
                CREATE TABLE IF NOT EXISTS user_settings (
                    user_id INTEGER PRIMARY KEY,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)
            # Саммари диалогов
            await db.execute("""
                CREATE TABLE IF NOT EXISTS conversation_summary (
                    user_id INTEGER PRIMARY KEY,
                    summary TEXT NOT NULL,
                    message_count INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)
            # Продвинутая память (как в Kai)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    key TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT 'LEARNING',
                    hit_count INTEGER NOT NULL DEFAULT 0,
                    promoted INTEGER NOT NULL DEFAULT 0,
                    source TEXT DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)
            await db.commit()
        logger.info("Memory: база данных готова (%s)", self.db_path)

    # ═══ История диалогов ══════════════════════════════════════════════════

    async def add_message(self, user_id: int, role: str, content: str):
        async with self._lock, aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO messages (user_id, role, content) VALUES (?, ?, ?)",
                (user_id, role, content),
            )
            await db.commit()

    async def get_history(self, user_id: int, limit: int = MAX_HISTORY_MESSAGES) -> list[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT role, content FROM messages WHERE user_id = ? "
                "ORDER BY id DESC LIMIT ?",
                (user_id, limit),
            )
            rows = await cursor.fetchall()
        return [{"role": r, "content": c} for r, c in reversed(rows)]

    async def clear_history(self, user_id: int):
        async with self._lock, aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM messages WHERE user_id = ?", (user_id,))
            await db.execute(
                "DELETE FROM conversation_summary WHERE user_id = ?", (user_id,),
            )
            await db.commit()

    async def save_user_settings(self, user_id: int, provider: str, model: str):
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
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT summary FROM conversation_summary WHERE user_id = ?",
                (user_id,),
            )
            row = await cursor.fetchone()
        return row[0] if row else None

    async def save_summary(self, user_id: int, summary: str, message_count: int):
        async with self._lock, aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO conversation_summary (user_id, summary, message_count, updated_at) "
                "VALUES (?, ?, ?, datetime('now')) "
                "ON CONFLICT(user_id) DO UPDATE SET summary=excluded.summary, "
                "message_count=excluded.message_count, updated_at=datetime('now')",
                (user_id, summary, message_count),
            )
            await db.commit()

    # ═══ Продвинутая память (Kai-style) ═══════════════════════════════════

    async def store(self, key: str, content: str, category: str = "LEARNING",
                    source: str = "") -> bool:
        """Сохранить или обновить факт/обучение.

        Если ключ уже существует — обновляет content и сбрасывает hit_count.
        """
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        async with self._lock, aiosqlite.connect(self.db_path) as db:
            # Проверяем, есть ли уже такой ключ
            cursor = await db.execute(
                "SELECT key, hit_count, promoted FROM memories WHERE key = ?",
                (key,),
            )
            existing = await cursor.fetchone()
            if existing:
                # Обновляем, но сохраняем promoted и hit_count
                await db.execute(
                    "UPDATE memories SET content=?, category=?, source=?, "
                    "updated_at=? WHERE key=?",
                    (content, category, source, now, key),
                )
            else:
                await db.execute(
                    "INSERT INTO memories (key, content, category, source, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (key, content, category, source, now, now),
                )
            await db.commit()
        return True

    async def learn(self, key: str, content: str, category: str = "LEARNING",
                    source: str = "observation") -> bool:
        """Сохранить структурированное обучение (как memory_learn)."""
        return await self.store(key, content, category, source)

    async def reinforce(self, key: str) -> bool:
        """Увеличить hitCount для ключа (как memory_reinforce)."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        async with self._lock, aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT hit_count, promoted FROM memories WHERE key = ?",
                (key,),
            )
            row = await cursor.fetchone()
            if not row:
                return False
            hit_count = row[0] + 1
            promoted = row[1]
            await db.execute(
                "UPDATE memories SET hit_count=?, updated_at=? WHERE key=?",
                (hit_count, now, key),
            )
            await db.commit()
        return True

    async def forget(self, key: str) -> bool:
        """Удалить запись памяти (как memory_forget)."""
        async with self._lock, aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "DELETE FROM memories WHERE key = ?", (key,),
            )
            await db.commit()
        return cursor.rowcount > 0

    async def get_all(self, category: Optional[str] = None) -> list[MemoryItem]:
        """Получить все памяти, опционально фильтруя по категории."""
        async with aiosqlite.connect(self.db_path) as db:
            if category:
                cursor = await db.execute(
                    "SELECT key, content, category, hit_count, promoted, source, "
                    "created_at, updated_at FROM memories WHERE category = ? "
                    "ORDER BY hit_count DESC, updated_at DESC",
                    (category,),
                )
            else:
                cursor = await db.execute(
                    "SELECT key, content, category, hit_count, promoted, source, "
                    "created_at, updated_at FROM memories "
                    "ORDER BY hit_count DESC, updated_at DESC",
                )
            rows = await cursor.fetchall()
        return [
            MemoryItem(
                key=r[0], content=r[1], category=r[2],
                hit_count=r[3], promoted=bool(r[4]), source=r[5] or "",
                created_at=r[6] or "", updated_at=r[7] or "",
            )
            for r in rows
        ]

    async def get_promoted(self) -> list[MemoryItem]:
        """Получить продвинутые памяти (попадают в system prompt)."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT key, content, category, hit_count, promoted, source, "
                "created_at, updated_at FROM memories WHERE promoted = 1 "
                "ORDER BY hit_count DESC",
            )
            rows = await cursor.fetchall()
        return [
            MemoryItem(
                key=r[0], content=r[1], category=r[2],
                hit_count=r[3], promoted=bool(r[4]), source=r[5] or "",
                created_at=r[6] or "", updated_at=r[7] or "",
            )
            for r in rows
        ]

    async def get_relevant(self, context: str, limit: int = 10) -> list[MemoryItem]:
        """Найти релевантные памяти по ключевым словам из контекста.

        Простой поиск: ищет пересечение слов между context и содержимым памяти.
        В будущем можно заменить на embedding search.
        """
        words = set(context.lower().split())
        all_items = await self.get_all()
        scored = []
        for item in all_items:
            text = f"{item.key} {item.content}".lower()
            # Считаем сколько слов из контекста встречается в памяти
            match_count = sum(1 for w in words if w in text and len(w) > 3)
            if match_count > 0:
                scored.append((match_count * (1 + item.hit_count * 0.5), item))
        scored.sort(key=lambda x: -x[0])
        return [item for _, item in scored[:limit]]

    async def check_promotion(self) -> list[MemoryItem]:
        """Найти памяти с hitCount >= порога, которые ещё не продвинуты.
        Возвращает список для продвижения."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT key, content, category, hit_count FROM memories "
                "WHERE hit_count >= ? AND promoted = 0",
                (PROMOTION_THRESHOLD,),
            )
            rows = await cursor.fetchall()
        return [
            MemoryItem(key=r[0], content=r[1], category=r[2], hit_count=r[3])
            for r in rows
        ]

    async def promote(self, key: str) -> bool:
        """Продвинуть память в soul (system prompt)."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        async with self._lock, aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "UPDATE memories SET promoted=1, updated_at=? WHERE key=?",
                (now, key),
            )
            await db.commit()
        return cursor.rowcount > 0

    async def format_promoted_section(self) -> str:
        """Сформировать секцию для system prompt из продвинутых памятей."""
        items = await self.get_promoted()
        if not items:
            return ""
        lines = ["\n## Memories about the user"]
        for item in items:
            if item.category == "PREFERENCE":
                lines.append(f"- Preference: {item.content}")
            elif item.category == "LEARNING":
                lines.append(f"- Learning: {item.content}")
            elif item.category == "ERROR":
                lines.append(f"- Known issue: {item.content}")
            else:
                lines.append(f"- Fact: {item.content}")
        return "\n".join(lines)

    async def count(self) -> int:
        """Общее количество записей памяти."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("SELECT COUNT(*) FROM memories")
            row = await cursor.fetchone()
        return row[0] if row else 0
