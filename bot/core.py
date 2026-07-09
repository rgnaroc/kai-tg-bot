"""Kai TG Bot — точка входа."""

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_ADMIN_IDS,
)
from bot.services.llm.router import LLMRouter
from bot.services.memory import Memory
from bot.services.git_manager import GitManager
from bot.services.self_coder import SelfCoder
from bot.handlers.commands import setup_commands
from bot.handlers.chat import setup_chat
from bot.handlers.self_coding import setup_self_coding

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    # Проверяем токен
    if not TELEGRAM_BOT_TOKEN:
        logger.critical("TELEGRAM_BOT_TOKEN не задан! Создай .env файл.")
        sys.exit(1)

    # Инициализируем компоненты
    logger.info("Запуск Kai TG Bot...")

    # LLM Router
    llm = LLMRouter()
    logger.info("LLM Router: %s", llm.get_current_info())

    # Память
    memory = Memory()
    await memory.init()

    # Git
    git = GitManager()
    logger.info("Git: %s (%s)", git.repo_path, "clean" if git.is_clean() else "dirty")

    # Self-Coder
    self_coder = SelfCoder(llm=llm, git=git)

    # Бот
    bot = Bot(
        token=TELEGRAM_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
    )
    dp = Dispatcher()

    # Регистрируем хендлеры (порядок важен: команды → чат)
    dp.include_router(setup_commands(llm, memory))
    dp.include_router(setup_self_coding(self_coder, git))
    dp.include_router(setup_chat(llm, memory))

    logger.info("Бот запущен. Ожидаю сообщения...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
