"""Базовые команды: /start, /help, /reset, /model."""

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.services.llm.router import LLMRouter
from bot.services.memory import Memory

router = Router()

def setup_commands(llm: LLMRouter, memory: Memory) -> Router:
    """Собрать роутер команд с зависимостями."""
    r = Router()

    @r.message(Command("start"))
    async def cmd_start(message: Message):
        current = llm.get_current()
        model_info = f"{current.display_name} ({current.model_id})" if current else "not configured"
        await message.answer(
            f"👋 Привет! Я **Kai** — твой AI-ассистент в Telegram.\n\n"
            f"Текущий LLM: `{model_info}`\n\n"
            "Просто напиши мне, и я помогу с вопросами, кодом, "
            "генерацией и всем остальным.\n\n"
            "📋 **Команды:**\n"
            "/help — помощь\n"
            "/model — текущая модель и смена LLM\n"
            "/services — список подключенных LLM-сервисов\n"
            "/addservice — добавить новый LLM-сервис\n"
            "/improve — анализ кода бота и улучшения\n"
            "/review — код-ревью файла\n"
            "/reset — очистить историю диалога\n"
            "/log — последние коммиты",
        )

    @r.message(Command("help"))
    async def cmd_help(message: Message):
        await message.answer(
            "🤖 **Kai TG Bot**\n\n"
            "**Команды:**\n"
            "/model — посмотреть и сменить LLM-провайдера\n"
            "/model <id> — переключить на сервис\n"
            "/services — список всех подключенных сервисов\n"
            "/addservice — пошаговое добавление нового провайдера\n"
            "/removeservice <id> — удалить сервис\n"
            "/service <id> — переключиться на сервис\n"
            "/improve — AI анализирует код бота и предлагает улучшения\n"
            "/apply — применить предложенные улучшения\n"
            "/reset — очистить историю\n"
            "/log — последние git коммиты\n"
            "/export — экспорт настроек сервисов\n\n"
            "**Как работает:**\n"
            "Бот помнит контекст диалога (50 сообщений). "
            "Если один LLM упал — автоматически переключается на следующий.",
        )

    @r.message(Command("reset"))
    async def cmd_reset(message: Message):
        await memory.clear_history(message.from_user.id)
        await message.answer("🧹 История диалога очищена.")

    @r.message(Command("model"))
    async def cmd_model(message: Message):
        """Показать или сменить модель."""
        args = message.text.split(maxsplit=1)
        if len(args) == 1:
            # Просто показать
            info = llm.format_providers_text()
            await message.answer(info)
        else:
            # Сменить сервис
            success, msg = llm.switch(args[1])
            await message.answer(msg)

    return r
