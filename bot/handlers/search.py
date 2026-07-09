"""Web Search: /search <query> + [search: ...] теги в ответах AI."""

from __future__ import annotations

import logging
import re

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.services.web_search import web_search, format_search_results

logger = logging.getLogger(__name__)

# Регулярка для [search: ...] тегов
SEARCH_TAG_RE = re.compile(r'\[search:\s*(.*?)\]', re.IGNORECASE)


def setup_search() -> Router:
    """Зарегистрировать поисковые команды."""
    r = Router()

    @r.message(Command("search"))
    async def cmd_search(message: Message):
        """Поиск в интернете."""
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            await message.answer(
                "🔍 **Web Search**\n\n"
                "Usage: `/search <query>`\n"
                "Example: `/search погода в Берлине`"
            )
            return

        query = args[1].strip()
        await message.answer(f"🔍 Searching for: _{query}_...")

        response = await web_search(query)
        text = format_search_results(response)

        if len(text) > 4000:
            text = text[:3997] + "..."

        await message.answer(text, disable_web_page_preview=True)

    return r


def parse_search_tags(text: str) -> list[str]:
    """Извлечь [search: ...] теги из текста."""
    return SEARCH_TAG_RE.findall(text)


def remove_search_tags(text: str) -> str:
    """Удалить [search: ...] теги из текста."""
    return SEARCH_TAG_RE.sub("", text).strip()
