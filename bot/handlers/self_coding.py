"""Команды само-кодинга: /improve, /review, /apply, /log."""

import logging
from typing import TYPE_CHECKING

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.services.self_coder import SelfCoder
from bot.services.git_manager import GitManager

logger = logging.getLogger(__name__)

# Храним последний анализ в памяти бота (на время сессии)
_last_patches: list = []


def setup_self_coding(self_coder: SelfCoder, git: GitManager) -> Router:
    """Собрать роутер команд само-кодинга."""
    global _last_patches
    r = Router()

    @r.message(Command("improve"))
    async def cmd_improve(message: Message):
        """AI анализирует код бота и предлагает улучшения."""
        await message.answer("🔍 Анализирую код бота... Это может занять 10-20 секунд.")

        try:
            patches = await self_coder.analyze()
            _last_patches.clear()
            _last_patches.extend(patches)

            if not patches:
                await message.answer("✅ Код в порядке — улучшений не найдено.")
                return

            # Показываем дифф
            diff_text = self_coder.format_diff(patches)
            await message.answer(diff_text, parse_mode="Markdown")
            await message.answer(
                "📝 Чтобы применить улучшения, введи /apply\n"
                "❌ Чтобы отклонить — просто игнорируй.",
            )
        except Exception as e:
            logger.error("Ошибка в /improve: %s", e)
            await message.answer(f"❌ Ошибка анализа: {e}")

    @r.message(Command("apply"))
    async def cmd_apply(message: Message):
        """Применить предложенные патчи."""
        if not _last_patches:
            await message.answer("⚠️ Нет предложенных улучшений. Сначала /improve.")
            return

        # Сохраняем состояние через stash
        git.stash()
        try:
            results = self_coder.apply(_last_patches)
            result_text = "\n".join(results)
            await message.answer(f"📝 Результаты применения:\n{result_text}")

            # Коммитим и пушим
            commit_msg = f"🤖 Auto-improve: {len(_last_patches)} patches applied"
            push_result = git.commit_and_push(commit_msg)
            await message.answer(push_result)

            _last_patches.clear()
            await message.answer(
                "🔄 Изменения запушены в GitHub. "
                "Рекомендую перезапустить бота, чтобы изменения вступили в силу."
            )
        except Exception as e:
            # Откатываем
            git.unstash()
            logger.error("Ошибка в /apply: %s", e)
            await message.answer(f"❌ Ошибка применения — изменения откачены: {e}")

    @r.message(Command("log"))
    async def cmd_log(message: Message):
        """Показать последние коммиты."""
        try:
            log = git.get_log(5)
            await message.answer(f"📋 **Последние коммиты:**\n{log}", parse_mode="Markdown")
        except Exception as e:
            await message.answer(f"❌ Ошибка: {e}")

    @r.message(Command("review"))
    async def cmd_review(message: Message):
        """Код-ревью конкретного файла."""
        args = message.text.split(maxsplit=1)
        if len(args) == 1:
            files = git.list_python_files()
            await message.answer(
                "📂 Укажи файл для ревью:\n"
                + "\n".join(f"• `{f}`" for f in files),
                parse_mode="Markdown",
            )
            return

        filename = args[1].strip()
        try:
            content = git.read_file(filename)
            await message.answer(
                f"📄 **{filename}** ({len(content)} символов)\n"
                f"```python\n{content[:3000]}\n```",
                parse_mode="Markdown",
            )
        except Exception as e:
            await message.answer(f"❌ Не могу прочитать {filename}: {e}")

    return r
