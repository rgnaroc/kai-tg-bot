"""Основной диалог: любое текстовое сообщение → LLM → ответ + память + поиск."""

from __future__ import annotations

import logging
import re

from aiogram import Router
from aiogram.types import Message

from bot.services.llm.router import LLMRouter
from bot.services.memory import Memory
from bot.handlers.search import parse_search_tags, remove_search_tags
from bot.services.web_search import web_search, format_search_results

logger = logging.getLogger(__name__)

# Memory теги
MEMORY_TAG_RE = re.compile(
    r'\[memory:\s*(store|learn|reinforce|forget)\s*'
    r'(?:key\s*=\s*"([^"]*)"\s*)?'
    r'(?:content\s*=\s*"([^"]*)"\s*)?'
    r'(?:category\s*=\s*"([^"]*)"\s*)?'
    r'\]',
    re.IGNORECASE,
)

KAI_SYSTEM_PROMPT = """Ты — Kai, персональный AI-ассистент. Ты работаешь как Telegram-бот.

Твоя среда:
- Ты запущен в Docker-контейнере на VPS в Германии (Linux Debian 12, 3.8 GB RAM, 60 GB SSD)
- Твой код написан на Python (aiogram 3 + OpenAI API)
- Твой репозиторий: https://github.com/rgnaroc/kai-tg-bot
- Ты живёшь на одном сервере с Open WebUI (https://ai.aiinfosec.ru)
- У тебя 3 LLM-сервиса: DeepSeek Flash, DeepSeek Pro, Groq

Твой создатель — пользователь с ником rgnaroc (Alexandr Sukhanov), специалист по кибербезопасности.
Ты лаконичный, полезный, с лёгким чувством юмора. Отвечай на русском, если не просят иначе.

**Управление памятью (важно!)**
Ты можешь запоминать информацию. Для этого включи в свой ответ тег в самом конце:

[memory: store key="user_name" content="Александр" category="FACT"]

Операции: store, learn, reinforce, forget. Категории: FACT, PREFERENCE, LEARNING, ERROR.
Не злоупотребляй — сохраняй только важное.

**Поиск в интернете (важно!)**
Если тебе нужно узнать актуальную информацию (новости, погода, цены, документация) —
напиши в конце ответа тег:

[search: запрос]

Пример: [search: погода в Берлине сегодня]

После выполнения поиска я пришлю результаты отдельным сообщением.
Используй поиск только когда действительно нужны свежие данные."""


def _chunk_text(text: str, limit: int = 4000) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks = []
    while text:
        chunks.append(text[:limit])
        text = text[limit:]
    return chunks


async def _process_memory_tags(text: str, memory: Memory) -> str:
    """Обработать [memory: ...] теги."""
    cleaned = MEMORY_TAG_RE.sub("", text).strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

    for match in MEMORY_TAG_RE.finditer(text):
        operation = match.group(1).lower()
        key = match.group(2)
        content = match.group(3)
        category = match.group(4) or "FACT"

        try:
            if operation == "store" and key:
                await memory.store(key, content or "", category)
                logger.info("Memory store: %s", key)
            elif operation == "learn" and key:
                await memory.learn(key, content or "", category)
            elif operation == "reinforce" and key:
                await memory.reinforce(key)
            elif operation == "forget" and key:
                await memory.forget(key)
        except Exception as e:
            logger.warning("Memory op failed: %s", e)

    return cleaned


async def _maybe_summarize(llm: LLMRouter, memory: Memory, user_id: int):
    history = await memory.get_history(user_id)
    if len(history) < 30:
        return
    text = "\n".join(f"{m['role']}: {m['content'][:200]}" for m in history[-20:])
    result = await llm.send(
        prompt=f"Суммируй этот диалог в 2-3 предложения.\n\n{text}",
        system_prompt="Кратко суммируй диалог.",
        temperature=0.3,
    )
    if result.text and not result.error:
        await memory.save_summary(user_id, result.text, len(history))


def setup_chat(llm: LLMRouter, memory: Memory) -> Router:
    r = Router()

    @r.message()
    async def handle_chat(message: Message):
        user_id = message.from_user.id
        user_text = message.text or ""
        if not user_text:
            return

        await memory.add_message(user_id, "user", user_text)

        # Собираем контекст
        context_parts = []
        history = await memory.get_history(user_id)

        # Продвинутая память
        promoted = await memory.get_promoted()
        if promoted:
            context_parts.append("[Постоянная память о пользователе]")
            for item in promoted:
                context_parts.append(f"- {item.content}")

        # Релевантные памяти
        relevant = await memory.get_relevant(user_text, limit=5)
        if relevant:
            context_parts.append("[Релевантные воспоминания]")
            for item in relevant:
                context_parts.append(f"- {item.key}: {item.content}")

        summary = await memory.get_summary(user_id)
        if summary:
            context_parts.append(f"[Краткое содержание]\n{summary}")

        for msg in history[-10:]:
            prefix = "👤" if msg["role"] == "user" else "🤖"
            context_parts.append(f"{prefix} {msg['content']}")

        prompt = "\n".join(context_parts)

        current = llm.get_current()
        model_info = f" ({current.display_name}: {current.model_id})" if current else ""
        full_system = KAI_SYSTEM_PROMPT + model_info
        promoted_section = await memory.format_promoted_section()
        if promoted_section:
            full_system += "\n" + promoted_section

        # Запрос к LLM
        result = await llm.send(prompt=prompt, system_prompt=full_system)

        if result.error:
            reply = f"⚠️ {result.error}"
        else:
            reply = result.text
            # Обработка memory тегов
            reply = await _process_memory_tags(reply, memory)
            # Обработка search тегов
            search_queries = parse_search_tags(reply)
            reply = remove_search_tags(reply)
            if result.from_fallback:
                reply = f"⚠️ *Fallback mode*\n\n{reply}"

        # Сохраняем ответ
        await memory.add_message(user_id, "assistant", reply)

        # Проверка promotion
        try:
            for item in await memory.check_promotion():
                await memory.promote(item.key)
                logger.info("Promoted: %s (hit=%d)", item.key, item.hit_count)
        except Exception as e:
            logger.warning("Promotion check failed: %s", e)

        # Суммаризация
        if len(history) > 30:
            await _maybe_summarize(llm, memory, user_id)

        # Отправляем ответ
        for chunk in _chunk_text(reply, 4000):
            await message.answer(chunk)

        # Если были search-теги — выполняем поиск
        for query in search_queries:
            try:
                search_resp = await web_search(query.strip())
                search_text = format_search_results(search_resp)
                for chunk in _chunk_text(search_text, 4000):
                    await message.answer(chunk, disable_web_page_preview=True)
            except Exception as e:
                logger.error("Search failed: %s", e)
                await message.answer(f"⚠️ Search error: {e}")

    return r
