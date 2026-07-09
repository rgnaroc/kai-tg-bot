"""Диалог с циклом инструментов: AI может искать, загружать страницы, переспрашивать, пока не даст ответ."""

from __future__ import annotations

import logging
import re

from aiogram import Router
from aiogram.types import Message

from bot.services.llm.router import LLMRouter
from bot.services.memory import Memory
from bot.handlers.search import parse_search_tags, remove_search_tags
from bot.services.web_search import web_search, format_search_results
from bot.services.currency import format_rates_text
import httpx

logger = logging.getLogger(__name__)

MEMORY_TAG_RE = re.compile(
    r'\[memory:\s*(store|learn|reinforce|forget)\s*'
    r'(?:key\s*=\s*"([^"]*)"\s*)?'
    r'(?:content\s*=\s*"([^"]*)"\s*)?'
    r'(?:category\s*=\s*"([^"]*)"\s*)?'
    r'\]', re.IGNORECASE,
)

MAX_ROUNDS = 5  # максимум раундов поиска/загрузки

TOOL_SYSTEM = """Ты — Kai с доступом в интернет.

ПРАВИЛО: Если вопрос про текущие данные (цены, курсы, погода, 
новости, стоимость, события) — НЕ ОТВЕЧАЙ ТЕКСТОМ.
Напиши ТОЛЬКО одну из команд:

[search: запрос] — найти в интернете
[fetch: https://...] — загрузить страницу
[rates] — курсы валют

Пример:
Пользователь: курс доллара
AI: [search: курс доллара к рублю сегодня]

После поиска изучи ссылки, загрузи через [fetch], проанализируй и дай ответ с цифрами.
"""


def _chunk_text(text: str, limit: int = 4000) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks = []
    while text:
        chunks.append(text[:limit])
        text = text[limit:]
    return chunks


async def _process_memory_tags(text: str, memory: Memory) -> str:
    cleaned = MEMORY_TAG_RE.sub("", text).strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    for match in MEMORY_TAG_RE.finditer(text):
        op, key, content, cat = match.group(1).lower(), match.group(2), match.group(3), match.group(4) or "FACT"
        try:
            if op == "store" and key:
                await memory.store(key, content or "", cat)
            elif op == "learn" and key:
                await memory.learn(key, content or "", cat)
            elif op == "reinforce" and key:
                await memory.reinforce(key)
            elif op == "forget" and key:
                await memory.forget(key)
        except Exception:
            pass
    return cleaned


async def _execute_tools(text: str, user_text: str, full_system: str, llm: LLMRouter) -> str:
    """Выполнить все инструменты из текста AI и вернуть ответ."""

    # [rates]
    if "[rates]" in text:
        text = text.replace("[rates]", "").strip()
        rates_text = await format_rates_text()
        return await llm.send(
            prompt=f"Вопрос: {user_text}\n\n{rates_text}\n\nОтветь с цифрами.",
            system_prompt=full_system,
        )

    # [search: ...]
    search_queries = parse_search_tags(text)
    if search_queries:
        text = remove_search_tags(text).strip()
        for query in search_queries:
            search_resp = await web_search(query.strip())
            search_text = format_search_results(search_resp)
            return await llm.send(
                prompt=f"Вопрос: {user_text}\n\nРезультаты поиска:\n{search_text}\n\n"
                       f"Если среди результатов есть полезные ссылки — загрузи их через [fetch: url]. "
                       f"Если данных достаточно — дай ответ.",
                system_prompt=full_system,
            )

    # [fetch: url]
    fetch_match = re.search(r'\[fetch:\s*(https?://[^\]]+)\]', text)
    if fetch_match:
        url = fetch_match.group(1)
        text = re.sub(r'\[fetch:\s*https?://[^\]]+\]', '', text).strip()
        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                fr = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                raw = fr.text
                # Очищаем HTML от тегов для читаемости
                import html
                clean = re.sub(r'<[^>]+>', ' ', raw)
                clean = re.sub(r'\s+', ' ', clean).strip()[:5000]
            return await llm.send(
                prompt=f"Вопрос: {user_text}\n\nСодержимое {url}:\n{clean}\n\n"
                       f"Проанализируй и дай ответ. Если нужно больше данных — используй [search] снова.",
                system_prompt=full_system,
            )
        except Exception as e:
            return await llm.send(
                prompt=f"Вопрос: {user_text}\n\nОшибка загрузки {url}: {e}\n\nПопробуй другой источник через [search].",
                system_prompt=full_system,
            )

    return None  # нет инструментов


def setup_chat(llm: LLMRouter, memory: Memory) -> Router:
    r = Router()

    @r.message()
    async def handle_chat(message: Message):
        user_id = message.from_user.id
        user_text = message.text or ""
        if not user_text:
            return

        await memory.add_message(user_id, "user", user_text)

        # ─── Контекст ─────────────────────────────────────────────────────
        ctx = []
        history = await memory.get_history(user_id)

        promoted = await memory.get_promoted()
        if promoted:
            ctx.append("[О пользователе]")
            for item in promoted:
                ctx.append(f"- {item.content}")

        relevant = await memory.get_relevant(user_text, limit=5)
        if relevant:
            ctx.append("[Воспоминания]")
            for item in relevant:
                ctx.append(f"- {item.key}: {item.content}")

        summary = await memory.get_summary(user_id)
        if summary:
            ctx.append(f"[Краткое содержание]\n{summary}")

        for msg in history[-10:]:
            ctx.append(f"{'👤' if msg['role'] == 'user' else '🤖'} {msg['content']}")

        prompt = "\n".join(ctx)
        current = llm.get_current()
        model_info = f" ({current.display_name}: {current.model_id})" if current else ""
        full_system = TOOL_SYSTEM + model_info
        promoted_section = await memory.format_promoted_section()
        if promoted_section:
            full_system += "\n" + promoted_section

        # ─── Основной цикл ────────────────────────────────────────────────
        current_prompt = prompt
        final_text = ""

        for round_num in range(MAX_ROUNDS):
            result = await llm.send(
                prompt=current_prompt,
                system_prompt=full_system,
            )
            reply = result.text if not result.error else f"⚠️ {result.error}"

            # Memory
            reply = await _process_memory_tags(reply, memory)

            # Проверяем, есть ли инструменты
            tool_result = await _execute_tools(reply, user_text, full_system, llm)

            if tool_result is None:
                # Нет инструментов — финальный ответ
                final_text = reply
                break

            # Есть инструменты — результат идёт как новый промпт для AI
            if round_num == MAX_ROUNDS - 1:
                # Последний раунд — форсируем ответ без инструментов
                force = await llm.send(
                    prompt=f"Вопрос: {user_text}\n\n"
                           f"Результаты поиска/загрузки:\n{tool_result.text}\n\n"
                           f"Дай финальный ответ. Больше никаких [search] или [fetch].",
                    system_prompt=full_system,
                )
                final_text = force.text if not force.error else tool_result.text
                final_text = await _process_memory_tags(final_text, memory)
                break

            # Продолжаем цикл с результатами инструментов
            current_prompt = (
                f"Вопрос пользователя: {user_text}\n\n"
                f"Результаты предыдущего шага:\n{tool_result.text}\n\n"
                f"Если у тебя достаточно данных — ответь пользователю.\n"
                f"Если нет — используй [search] или [fetch] для уточнения."
            )

        # ─── Финал ────────────────────────────────────────────────────────
        if not final_text:
            final_text = "⚠️ Не удалось получить ответ."

        await memory.add_message(user_id, "assistant", final_text)

        # Promotion
        try:
            for item in await memory.check_promotion():
                await memory.promote(item.key)
        except Exception:
            pass

        # Summary
        if len(history) > 30:
            try:
                hist = await memory.get_history(user_id)
                txt = "\n".join(f"{m['role']}: {m['content'][:200]}" for m in hist[-20:])
                res = await llm.send(prompt=f"Суммируй диалог.\n\n{txt}",
                                     system_prompt="Кратко.", temperature=0.3)
                if res.text and not res.error:
                    await memory.save_summary(user_id, res.text, len(hist))
            except Exception:
                pass

        for chunk in _chunk_text(final_text, 4000):
            await message.answer(chunk)

    return r
