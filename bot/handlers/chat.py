"""Основной диалог: любое текстовое сообщение → LLM → ответ."""

import logging

from aiogram import Router
from aiogram.types import Message

from bot.services.llm.router import LLMRouter
from bot.services.memory import Memory

logger = logging.getLogger(__name__)

KAI_SYSTEM_PROMPT = """Ты — Kai, персональный AI-ассистент в Telegram.
Ты помогаешь с вопросами, кодом, анализом, генерацией контента.
Ты лаконичный, полезный, с чувством юмора.
Ты работаешь через разных LLM-провайдеров, но сохраняешь свою личность.
Отвечай на русском, если не просят иначе."""


def setup_chat(llm: LLMRouter, memory: Memory) -> Router:
    """Собрать роутер чата."""
    r = Router()

    @r.message()
    async def handle_chat(message: Message):
        user_id = message.from_user.id
        user_text = message.text or ""

        # Сохраняем сообщение пользователя
        await memory.add_message(user_id, "user", user_text)

        # Получаем историю
        history = await memory.get_history(user_id)
        context_parts = []

        # Если есть саммари предыдущего диалога — добавляем
        summary = await memory.get_summary(user_id)
        if summary:
            context_parts.append(f"[Краткое содержание предыдущего диалога]\n{summary}")

        # История сообщений
        for msg in history[-10:]:  # последние 10 для компактности
            prefix = "👤" if msg["role"] == "user" else "🤖"
            context_parts.append(f"{prefix} {msg['content']}")

        prompt = "\n".join(context_parts)

        # Отправляем в LLM
        try:
            response = await llm.send(
                prompt=prompt,
                system_prompt=KAI_SYSTEM_PROMPT,
            )
            reply = response.text
        except Exception as e:
            logger.error("LLM error: %s", e)
            reply = f"⚠️ Ошибка при обращении к {llm.current_provider}:{llm.current_model}: {e}"

        # Сохраняем ответ
        await memory.add_message(user_id, "assistant", reply)

        # Если история длинная — делаем саммари
        if len(history) > 30:
            await _maybe_summarize(llm, memory, user_id)

        # Отправляем (разбиваем длинные сообщения)
        if len(reply) > 4000:
            for chunk in _chunk_text(reply, 4000):
                await message.answer(chunk)
        else:
            await message.answer(reply)

    return r


async def _maybe_summarize(llm: LLMRouter, memory: Memory, user_id: int):
    """Сжать историю в саммари, если она слишком длинная."""
    try:
        full_history = await memory.get_history(user_id)
        if len(full_history) < 30:
            return

        dialogue = "\n".join(
            f"{'User' if m['role']=='user' else 'Kai'}: {m['content']}"
            for m in full_history[-30:]
        )
        resp = await llm.send(
            prompt=f"Сделай краткое саммари этого диалога (2-3 предложения):\n\n{dialogue}",
            temperature=0.3,
        )
        await memory.save_summary(user_id, resp.text, len(full_history))
        logger.info("Саммари создано для user %d", user_id)
    except Exception as e:
        logger.warning("Не удалось создать саммари: %s", e)


def _chunk_text(text: str, size: int) -> list[str]:
    """Разбить текст на чанки по размеру, не разрывая строки."""
    chunks = []
    for i in range(0, len(text), size):
        chunks.append(text[i:i + size])
    return chunks
