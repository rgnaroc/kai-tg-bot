"""Команды управления памятью: /memories, /forget, /remember."""

from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.services.memory import Memory

logger = logging.getLogger(__name__)


def setup_memory_commands(memory: Memory) -> Router:
    """Зарегистрировать команды управления памятью."""
    r = Router()

    @r.message(Command("memories"))
    async def cmd_memories(message: Message):
        """Показать все сохранённые памяти."""
        items = await memory.get_all()
        if not items:
            await message.answer("🧠 Память пуста. Поговори со мной — я запомню важное.")
            return

        # Группируем по категориям
        by_category: dict[str, list] = {}
        for item in items:
            by_category.setdefault(item.category, []).append(item)

        lines = ["**🧠 Memory Bank**"]
        total = len(items)
        promoted_count = sum(1 for i in items if i.promoted)
        lines.append(f"*{total} entries · {promoted_count} promoted*\n")

        for cat in ["FACT", "PREFERENCE", "LEARNING", "ERROR"]:
            cat_items = by_category.get(cat, [])
            if not cat_items:
                continue
            emoji = {"FACT": "📌", "PREFERENCE": "⭐", "LEARNING": "💡", "ERROR": "⚠️"}.get(cat, "📌")
            lines.append(f"\n{emoji} **{cat}** ({len(cat_items)})")
            for item in cat_items[:10]:  # макс 10 на категорию
                tag = " 🔥" if item.promoted else ""
                lines.append(f"  `{item.key}` ×{item.hit_count}{tag}")
                # Показываем только начало контента
                content = item.content[:100]
                lines.append(f"  _{content}_")

        text = "\n".join(lines)
        if len(text) > 4000:
            text = text[:3997] + "..."

        await message.answer(text)

    @r.message(Command("forget"))
    async def cmd_forget(message: Message):
        """Удалить память по ключу."""
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            await message.answer("Usage: `/forget <key>`")
            return
        key = args[1].strip()
        success = await memory.forget(key)
        if success:
            await message.answer(f"🗑️ Забыл `{key}`")
        else:
            await message.answer(f"❌ Память `{key}` не найдена")

    @r.message(Command("remember"))
    async def cmd_remember(message: Message):
        """Вручную сохранить факт."""
        args = message.text.split(maxsplit=2)
        if len(args) < 3:
            await message.answer(
                "Usage: `/remember <key> <content>`\n"
                "Example: `/remember fav_color Любимый цвет — синий`"
            )
            return
        key = args[1].strip()
        content = args[2].strip()
        await memory.store(key, content, category="FACT")
        await message.answer(f"✅ Запомнил: `{key}` = {content[:200]}")

    return r
