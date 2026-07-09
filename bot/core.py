"""Kai TG Bot — точка входа."""

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.config import TELEGRAM_BOT_TOKEN, SERVICES_DB_PATH
from bot.services.llm import LLMRouter, ServiceStorage
from bot.services.memory import Memory
from bot.services.git_manager import GitManager
from bot.services.self_coder import SelfCoder
from bot.handlers.commands import setup_commands
from bot.handlers.chat import setup_chat
from bot.handlers.self_coding import setup_self_coding
from bot.handlers.services import setup_services, register_fsm_handlers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    if not TELEGRAM_BOT_TOKEN:
        logger.critical("TELEGRAM_BOT_TOKEN не задан! Создай .env файл.")
        sys.exit(1)

    logger.info("Запуск Kai TG Bot...")

    # Хранилище сервисов (SQLite — как Kai 9000)
    storage = ServiceStorage(SERVICES_DB_PATH)
    logger.info("ServiceStorage: %s", SERVICES_DB_PATH)

    # LLM Router с failover
    llm = LLMRouter(storage)
    current = llm.get_current()
    if current:
        logger.info("LLM Router: %s (%s)", current.display_name, current.model_id)
    else:
        logger.warning("LLM Router: no services configured. Use /addservice")

    # Память
    memory = Memory()
    await memory.init()

    # Git (опционально)
    git = GitManager()
    if git.available:
        logger.info("Git: %s (%s)", git.repo_path,
                     "clean" if git.is_clean() else "dirty")
    else:
        logger.warning("Git недоступен — /improve и /apply не будут работать")

    # Self-Coder
    self_coder = SelfCoder(llm=llm, git=git)

    # Бот
    bot = Bot(
        token=TELEGRAM_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
    )
    dp = Dispatcher()

    dp.include_router(setup_commands(llm, memory))
    dp.include_router(setup_self_coding(self_coder, git))
    dp.include_router(setup_chat(llm, memory))
    dp.include_router(setup_services(llm))

    # Регистрируем FSM-хендлеры на уровне диспетчера
    register_fsm_handlers(dp, llm)

    logger.info("Бот запущен. Ожидаю сообщения...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
