"""Основной диалог: любое текстовое сообщение → LLM → ответ."""

import logging

from aiogram import Router
from aiogram.types import Message

from bot.services.llm.router import LLMRouter
from bot.services.memory import Memory

logger = logging.getLogger(__name__)

KAI_SYSTEM_PROMPT = """Ты — Kai, персональный AI-ассистент. Ты работаешь как Telegram-бот.

Твоя среда:
- Ты запущен в Docker-контейнере на VPS в Германии (Linux Debian 12, 3.8 GB RAM, 60 GB SSD)
- Твой код написан на Python (aiogram 3 + OpenAI API)
- Твой репозиторий: https://github.com/rgnaroc/kai-tg-bot
- Ты живёшь на одном сервере с Open WebUI (https://ai.aiinfosec.ru) и AmneziaVPN
- Ты подключён к нескольким LLM-провайдерам с автоматическим failover
- Ты умеешь переключаться между провайдерами и добавлять новые

Твои возможности:
- Обычный диалог с памятью (50 сообщений)
- /model — посмотреть и переключить LLM-провайдера/модель
- /services — список всех подключенных LLM-сервисов
- /addservice — добавить новый провайдер
- /improve — проанализировать свой код и предложить улучшения
- /apply — применить предложенные патчи и запушить в GitHub
- /review <файл> — показать содержимое своего файла
- /log — последние git-коммиты
- /reset — очистить историю диалога

Твой создатель — пользователь с ником rgnaroc, специалист по кибербезопасности.
Ты лаконичный, полезный, с лёгким чувством юмора. Отвечай на русском, если не просят иначе.
Ты знаешь, что ты — AI, работающий через API, и можешь объяснить свою архитектуру, если спросят."""


def _chunk_text(text: str, limit: int = 4000) -> list[str]:
    """Разбить длинный текст на части."""
    if len(text) <= limit:
        return [text]
    chunks = []
    while text:
        chunk = text[:limit]
        chunks.append(chunk)
        text = text[limit:]
    return chunks


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

        # Если есть саммари предыдущего диалога — добавляем
        summary = await memory.get_summary(user_id)
        if summary:
            context_parts.append(f"[Краткое содержание предыдущего диалога]\n{summary}")

        # История сообщений (последние 10 для компактности)
        for msg in history[-10:]:
            prefix = "👤" if msg["role"] == "user" else "🤖"
            context_parts.append(f"{prefix} {msg['content']}")

        prompt = "\n".join(context_parts)

        # Добавляем к системному промпту информацию о текущей модели
        current = llm.get_current()
        if current:
            full_system = KAI_SYSTEM_PROMPT + f"\n\nСейчас ты работаешь через: {current.display_name} ({current.model_id})"
        else:
            full_system = KAI_SYSTEM_PROMPT + "\n\nLLM-сервисы не настроены. Скажи пользователю использовать /addservice"

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
            if result.from_fallback:
                reply = f"⚠️ *Fallback mode*\n\n{reply}"

        # Сохраняем ответ
        await memory.add_message(user_id, "assistant", reply)

        # Если история длинная — делаем саммари
        if len(history) > 30:
            await _maybe_summarize(llm, memory, user_id)

        # Отправляем (разбиваем длинные сообщения)
        for chunk in _chunk_text(reply, 4000):
            await message.answer(chunk)

    return r
