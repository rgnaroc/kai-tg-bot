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
        await message.answer(
            "👋 Привет! Я **Kai** — твой AI-ассистент в Telegram.\n\n"
            "Просто напиши мне, и я помогу с вопросами, кодом, "
            "генерацией и всем остальным.\n\n"
            "📋 Команды:\n"
            "/help — помощь\n"
            "/model — текущая модель и смена LLM\n"
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
            "/model groq — переключить на Groq\n"
            "/model deepseek:deepseek-reasoner — переключить модель\n"
            "/improve — AI анализирует код бота и предлагает улучшения\n"
            "/apply — применить предложенные улучшения\n"
            "/reset — очистить историю\n"
            "/log — последние git коммиты\n\n"
            "**Как работает:**\n"
            "Бот помнит контекст диалога (50 сообщений). "
            "Можно переключать LLM на лету.\n"
            "Через /improve бот читает свой код, находит баги и "
            "предлагает исправления.",
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
            info = llm.list_providers()
            await message.answer(info, parse_mode="Markdown")
        else:
            # Сменить
            success, msg = llm.switch(args[1])
            if success:
                await memory.save_user_settings(
                    message.from_user.id,
                    llm.current_provider,
                    llm.current_model,
                )
            await message.answer(msg)

    return r
