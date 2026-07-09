"""Основной диалог с двухшаговым поиском: AI → [search] → бот ищет → AI анализирует → ответ."""

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

logger = logging.getLogger(__name__)

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
- Ты запущен в Docker-контейнере на VPS в Германии
- Твой код на Python (aiogram 3 + OpenAI API)
- Репозиторий: https://github.com/rgnaroc/kai-tg-bot
- 3 LLM-сервиса: DeepSeek Flash/Pro, Groq

Твой создатель — rgnaroc (Alexandr Sukhanov), специалист по кибербезопасности.
Ты лаконичный, полезный, с лёгким чувством юмора. Отвечай на русский.

**Память:**
[memory: store key="..." content="..." category="FACT"]
Категории: FACT, PREFERENCE, LEARNING, ERROR.

**Поиск в интернете:**
Если нужны актуальные данные — НЕ пиши ничего в ответ, просто напиши ТОЛЬКО тег:
[search: запрос]
Я выполню поиск и пришлю тебе результаты. После этого ты сможешь дать полноценный ответ.

ВАЖНО: Не пиши никакого текста вместе с [search] — только сам тег.
Ты получишь результаты поиска в следующем сообщении и должен будешь ответить пользователю.

**Курсы валют:**
Если пользователь спрашивает курс валют — напиши ТОЛЬКО тег:
[rates]
Я верну тебе официальные курсы ЦБ РФ.

**Загрузка страницы:**
Если нужно прочитать конкретную страницу — напиши ТОЛЬКО тег:
[fetch: https://example.com]
Я загружу содержимое и отдам тебе на анализ.""" 


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
        except Exception as e:
            logger.warning("Memory op failed: %s", e)
    return cleaned


def setup_chat(llm: LLMRouter, memory: Memory) -> Router:
    r = Router()

    @r.message()
    async def handle_chat(message: Message):
        user_id = message.from_user.id
        user_text = message.text or ""
        if not user_text:
            return

        await memory.add_message(user_id, "user", user_text)

        # ─── Формируем контекст ─────────────────────────────────────────
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
        full_system = KAI_SYSTEM_PROMPT + model_info
        promoted_section = await memory.format_promoted_section()
        if promoted_section:
            full_system += "\n" + promoted_section

        # ─── Первый запрос к AI ─────────────────────────────────────────
        result = await llm.send(prompt=prompt, system_prompt=full_system)
        reply = result.text if not result.error else f"⚠️ {result.error}"
        reply = await _process_memory_tags(reply, memory)

        # ─── Поиск ────────────────────────────────────────────────────────
        search_queries = parse_search_tags(reply)
        reply = remove_search_tags(reply).strip()

        # ─── Rates ──────────────────────────────────────────────────────────
        if "[rates]" in reply:
            reply = reply.replace("[rates]", "").strip()
            rates_text = await format_rates_text()
            result_rates = await llm.send(
                prompt=f"Пользователь спросил: {user_text}\n\n{rates_text}\n\nДай ответ с конкретными цифрами.",
                system_prompt=full_system,
            )
            reply = result_rates.text if not result_rates.error else rates_text
            reply = await _process_memory_tags(reply, memory)

        # ─── Fetch URL ────────────────────────────────────────────────────
        fetch_match = re.search(r'\[fetch:\s*(https?://[^\]]+)\]', reply)
        if fetch_match:
            url = fetch_match.group(1)
            reply = re.sub(r'\[fetch:\s*https?://[^\]]+\]', '', reply).strip()
            import httpx
            try:
                async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                    fr = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                    content_text = fr.text[:3000]  # первые 3000 символов
                result_fetch = await llm.send(
                    prompt=f"Пользователь спросил: {user_text}\n\nСодержимое страницы {url}:\n{content_text}\n\nПроанализируй и дай ответ.",
                    system_prompt=full_system,
                )
                reply = result_fetch.text if not result_fetch.error else f"Не удалось загрузить {url}"
                reply = await _process_memory_tags(reply, memory)
            except Exception as e:
                reply = f"⚠️ Ошибка загрузки {url}: {e}"

        if search_queries:
            # Выполняем поиск
            for query in search_queries:
                search_resp = await web_search(query.strip())
                search_text = format_search_results(search_resp)

                # Отправляем результаты обратно AI для анализа
                analysis_prompt = (
                    f"Пользователь спросил: {user_text}\n\n"
                    f"Результаты поиска:\n{search_text}\n\n"
                    "Проанализируй эти результаты и дай пользователю "
                    "исчерпывающий ответ на его вопрос. Если есть курс/цена — назови цифру."
                )
                result2 = await llm.send(prompt=analysis_prompt, system_prompt=full_system)
                reply = result2.text if not result2.error else f"⚠️ {result2.error}"
                reply = await _process_memory_tags(reply, memory)

        # ─── Сохраняем и отправляем ─────────────────────────────────────
        if reply:
            await memory.add_message(user_id, "assistant", reply)

        # Promotion
        try:
            for item in await memory.check_promotion():
                await memory.promote(item.key)
        except Exception:
            pass

        if len(history) > 30:
            try:
                hist = await memory.get_history(user_id)
                txt = "\n".join(f"{m['role']}: {m['content'][:200]}" for m in hist[-20:])
                res = await llm.send(prompt=f"Суммируй диалог в 2-3 предложения.\n\n{txt}",
                                     system_prompt="Кратко суммируй.", temperature=0.3)
                if res.text and not res.error:
                    await memory.save_summary(user_id, res.text, len(hist))
            except Exception:
                pass

        if reply:
            for chunk in _chunk_text(reply, 4000):
                await message.answer(chunk)

    return r
