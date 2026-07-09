"""Основной диалог: любое текстовое сообщение → LLM → ответ + извлечение памяти."""

from __future__ import annotations

import logging
import re

from aiogram import Router
from aiogram.types import Message

from bot.services.llm.router import LLMRouter
from bot.services.memory import Memory

logger = logging.getLogger(__name__)

# Регулярка для [memory: ...] тегов в ответе AI
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
- Ты живёшь на одном сервере с Open WebUI (https://ai.aiinfosec.ru) и AmneziaVPN
- Ты подключён к нескольким LLM-провайдерам с автоматическим failover

Твой создатель — пользователь с ником rgnaroc (Alexandr Sukhanov), специалист по кибербезопасности.
Ты лаконичный, полезный, с лёгким чувством юмора. Отвечай на русском, если не просят иначе.

**Важно: управление памятью**
Ты можешь запоминать информацию о пользователе. Для этого включи в свой ответ
специальный тег в самом конце (после основного ответа):

[memory: store key="user_name" content="Александр, кибербезопасник"]

Поддерживаемые операции:
- store — сохранить факт (key, content, category=FACT|PREFERENCE|LEARNING|ERROR)
- learn — сохранить обучение (key, content, category)
- reinforce — усилить существующую память (key)
- forget — удалить память (key)

Не злоупотребляй тегами — сохраняй только важную информацию."""


def _chunk_text(text: str, limit: int = 4000) -> list[str]:
    """Разбить длинный текст на части."""
    if len(text) <= limit:
        return [text]
    chunks = []
    while text:
        chunk = text[:limit]
        # Режем по последнему переводу строки
        if len(chunk) == limit:
            last_nl = chunk.rfind("\n")
            if last_nl > limit // 2:
                chunk = chunk[:last_nl]
        chunks.append(chunk)
        text = text[len(chunk):]
    return chunks


async def _process_memory_tags(text: str, memory: Memory) -> str:
    """Обработать [memory: ...] теги в ответе AI и выполнить операции.
    Возвращает текст без тегов."""
    cleaned = MEMORY_TAG_RE.sub("", text).strip()
    # Убираем лишние пустые строки после удаления тегов
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

    for match in MEMORY_TAG_RE.finditer(text):
        operation = match.group(1).lower()
        key = match.group(2)
        content = match.group(3)
        category = match.group(4) or "FACT"

        try:
            if operation == "store" and key:
                await memory.store(key, content or "", category)
                logger.info("Memory store: %s = %s", key, content)
            elif operation == "learn" and key:
                await memory.learn(key, content or "", category)
                logger.info("Memory learn: %s (%s)", key, category)
            elif operation == "reinforce" and key:
                await memory.reinforce(key)
                logger.info("Memory reinforce: %s", key)
            elif operation == "forget" and key:
                await memory.forget(key)
                logger.info("Memory forget: %s", key)
        except Exception as e:
            logger.warning("Memory operation failed: %s", e)

    return cleaned


async def _maybe_summarize(llm: LLMRouter, memory: Memory, user_id: int):
    """Сделать саммари длинной истории."""
    history = await memory.get_history(user_id)
    if len(history) < 30:
        return
    text = "\n".join(f"{m['role']}: {m['content'][:200]}" for m in history[-20:])
    result = await llm.send(
        prompt=f"Суммируй этот диалог в 2-3 предложения. Что обсуждали? Какие важные факты?\n\n{text}",
        system_prompt="Ты — ассистент для суммаризации диалогов. Кратко и по делу.",
        temperature=0.3,
    )
    if result.text and not result.error:
        await memory.save_summary(user_id, result.text, len(history))
        logger.info("Summary saved for user %s", user_id)


def setup_chat(llm: LLMRouter, memory: Memory) -> Router:
    """Собрать роутер чата."""
    r = Router()

    @r.message()
    async def handle_chat(message: Message):
        user_id = message.from_user.id
        user_text = message.text or ""

        if not user_text:
            return

        # Сохраняем сообщение пользователя
        await memory.add_message(user_id, "user", user_text)

        # Получаем историю
        history = await memory.get_history(user_id)
        context_parts = []

        # Продвинутая память (promoted → system prompt)
        promoted = await memory.get_promoted()
        if promoted:
            context_parts.append("[Постоянная память о пользователе]")
            for item in promoted:
                context_parts.append(f"- {item.content}")

        # Релевантные памяти (поиск по словам из сообщения)
        relevant = await memory.get_relevant(user_text, limit=5)
        if relevant:
            context_parts.append("[Релевантные воспоминания]")
            for item in relevant:
                context_parts.append(f"- {item.key}: {item.content}")

        # Саммари предыдущего диалога
        summary = await memory.get_summary(user_id)
        if summary:
            context_parts.append(f"[Краткое содержание предыдущего диалога]\n{summary}")

        # История сообщений (последние 10)
        for msg in history[-10:]:
            prefix = "👤" if msg["role"] == "user" else "🤖"
            context_parts.append(f"{prefix} {msg['content']}")

        prompt = "\n".join(context_parts)

        # Формируем system prompt с promoted memories
        current = llm.get_current()
        model_info = f" ({current.display_name}: {current.model_id})" if current else ""
        full_system = KAI_SYSTEM_PROMPT + model_info

        # Добавляем promoted memories в system prompt
        promoted_section = await memory.format_promoted_section()
        if promoted_section:
            full_system += "\n" + promoted_section

        # Отправляем в LLM
        result = await llm.send(
            prompt=prompt,
            system_prompt=full_system,
        )

        if result.error:
            logger.error("LLM error: %s", result.error)
            reply = f"⚠️ {result.error}"
        else:
            reply = result.text
            # Обрабатываем memory теги
            reply = await _process_memory_tags(reply, memory)
            if result.from_fallback:
                reply = f"⚠️ *Fallback mode*\n\n{reply}"

        # Сохраняем ответ
        await memory.add_message(user_id, "assistant", reply)

        # Проверяем продвижение памятей (hitCount >= 5)
        try:
            for item in await memory.check_promotion():
                await memory.promote(item.key)
                logger.info("Memory promoted: %s (hit_count=%d)", item.key, item.hit_count)
        except Exception as e:
            logger.warning("Promotion check failed: %s", e)

        # Если история длинная — делаем саммари
        if len(history) > 30:
            await _maybe_summarize(llm, memory, user_id)

        # Отправляем
        for chunk in _chunk_text(reply, 4000):
            await message.answer(chunk)

    return r
