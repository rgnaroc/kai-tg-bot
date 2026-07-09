"""Telegram-команды для управления LLM-сервисами — /addservice, /services, /removeservice, /service.

Использует aiogram 3.x (Router, FSM, InlineKeyboard).
"""

from __future__ import annotations

import logging

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from bot.services.llm.models import PREDEFINED_PROVIDERS, OPENAI_COMPATIBLE
from bot.services.llm.router import LLMRouter

logger = logging.getLogger(__name__)


# ─── FSM States для /addservice ─────────────────────────────────────────────

class AddService(StatesGroup):
    select_provider = State()
    enter_api_key = State()
    enter_base_url = State()
    enter_model = State()


# ─── /services ──────────────────────────────────────────────────────────────

def cmd_services(llm: LLMRouter):
    async def handler(message: Message):
        text = llm.format_providers_text()
        await message.answer(text)
    return handler


# ─── /service <id> ──────────────────────────────────────────────────────────

def cmd_service(llm: LLMRouter):
    async def handler(message: Message):
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            text = llm.format_providers_text()
            await message.answer(f"{text}\n\nUsage: `/service <id>`")
            return
        success, msg = llm.switch(args[1])
        await message.answer(msg)
    return handler


# ─── /removeservice <id> ────────────────────────────────────────────────────

def cmd_remove_service(llm: LLMRouter):
    async def handler(message: Message):
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            await message.answer("Usage: `/removeservice <id>`")
            return
        success, msg = llm.remove_service(args[1])
        await message.answer(f"{'✅' if success else '❌'} {msg}")
    return handler


# ─── /addservice ────────────────────────────────────────────────────────────

def _build_provider_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура выбора провайдера."""
    predefined = list(PREDEFINED_PROVIDERS.keys())
    buttons = []
    for pid in predefined:
        p = PREDEFINED_PROVIDERS[pid]
        buttons.append(InlineKeyboardButton(text=p.display_name, callback_data=f"prov_{pid}"))
    keyboard = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
    keyboard.append([InlineKeyboardButton(
        text="🔧 OpenAI-Compatible", callback_data="prov_openai-compatible"
    )])
    keyboard.append([InlineKeyboardButton(text="❌ Cancel", callback_data="prov_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def add_service_handlers(llm: LLMRouter):
    """Создать хендлеры для /addservice FSM с замыканием на llm."""

    async def cmd_add_service(message: Message, state: FSMContext):
        await state.set_state(AddService.select_provider)
        await message.answer(
            "**Add LLM Service**\nChoose a provider:",
            reply_markup=_build_provider_keyboard(),
        )

    async def select_provider_cb(query: CallbackQuery, state: FSMContext):
        await query.answer()
        provider_id = query.data.replace("prov_", "")

        if provider_id == "cancel":
            await state.clear()
            await query.message.edit_text("Cancelled.")
            return

        provider_def = PREDEFINED_PROVIDERS.get(provider_id) or OPENAI_COMPATIBLE
        await state.update_data(service_id=provider_id)

        text = f"Provider: **{provider_def.display_name}**\n\n"

        if provider_id == "openai-compatible":
            await state.set_state(AddService.enter_base_url)
            await query.message.edit_text(
                text + "Enter the **Base URL**\n(e.g. `https://my-ollama:11434/v1`):\n\n"
                "Send /cancel to abort",
            )
            return

        if not provider_def.requires_api_key:
            await state.update_data(api_key="")
            await state.set_state(AddService.enter_model)
            await query.message.edit_text(
                text + "No API key required.\nEnter model name (or /skip for default):"
            )
            return

        await state.set_state(AddService.enter_api_key)
        key_url = f"\n🔑 Get one at: `{provider_def.api_key_url}`" if provider_def.api_key_url else ""
        await query.message.edit_text(
            text + f"Enter your **API key**:{key_url}\n\nSend /cancel to abort",
        )

    async def enter_api_key(message: Message, state: FSMContext):
        await state.update_data(api_key=message.text.strip())
        data = await state.get_data()
        if data.get("service_id") == "openai-compatible":
            await state.set_state(AddService.enter_base_url)
            await message.answer("Now enter the **Base URL**:")
            return
        await state.set_state(AddService.enter_model)
        await message.answer("Enter model name (or /skip for default):")

    async def enter_base_url(message: Message, state: FSMContext):
        await state.update_data(base_url=message.text.strip())
        await state.set_state(AddService.enter_model)
        await message.answer("Enter model name (or /skip for default):")

    async def enter_model(message: Message, state: FSMContext):
        text = message.text.strip()
        await _finish_add(message, state, llm, "" if text.upper() == "/SKIP" else text)

    async def skip_model(message: Message, state: FSMContext):
        await _finish_add(message, state, llm, "")

    async def cancel_add(message: Message, state: FSMContext):
        await state.clear()
        await message.answer("Cancelled.")

    return {
        "cmd_add_service": cmd_add_service,
        "select_provider_cb": select_provider_cb,
        "enter_api_key": enter_api_key,
        "enter_base_url": enter_base_url,
        "enter_model": enter_model,
        "skip_model": skip_model,
        "cancel_add": cancel_add,
    }


async def _finish_add(message: Message, state: FSMContext, llm: LLMRouter, model_id: str):
    """Сохранить сервис и завершить."""
    data = await state.get_data()
    await state.clear()

    success, msg = await llm.add_service(
        service_id=data.get("service_id", ""),
        api_key=data.get("api_key", ""),
        base_url=data.get("base_url", ""),
        model_id=model_id,
    )
    await message.answer(msg)


# ─── /export ────────────────────────────────────────────────────────────────

def cmd_export(llm: LLMRouter):
    async def handler(message: Message):
        json_str = llm.storage.export_json()
        if len(json_str) > 3500:
            await message.answer("📋 Export is large, length: {} bytes".format(len(json_str)))
        else:
            await message.answer(f"📋 **Services export:**\n\n```json\n{json_str}\n```")
    return handler


# ─── Регистрация ────────────────────────────────────────────────────────────

def setup_services(llm: LLMRouter) -> Router:
    """Зарегистрировать хендлеры управления сервисами."""
    r = Router()

    # Простые команды
    r.message.register(cmd_services(llm), Command("services"))
    r.message.register(cmd_service(llm), Command("service"))
    r.message.register(cmd_remove_service(llm), Command("removeservice"))
    r.message.register(cmd_export(llm), Command("export"))

    # /addservice — FSM
    handlers = add_service_handlers(llm)
    r.message.register(handlers["cmd_add_service"], Command("addservice"))

    # Регистрируем FSM с фильтрацией по state (добавим в register_fsm_handlers)
    # Сохраняем в router для последующей регистрации
    r._add_service_handlers = handlers

    return r


def register_fsm_handlers(dp, llm: LLMRouter):
    """Зарегистрировать FSM-хендлеры (вызывается из core.py после инициализации dp)."""
    handlers = add_service_handlers(llm)

    # Callback — выбор провайдера
    dp.callback_query.register(handlers["select_provider_cb"], F.data.startswith("prov_"))

    # States
    dp.message.register(handlers["enter_api_key"], AddService.enter_api_key)
    dp.message.register(handlers["enter_base_url"], AddService.enter_base_url)
    dp.message.register(handlers["enter_model"], AddService.enter_model, ~Command("skip"), ~Command("cancel"))
    dp.message.register(handlers["skip_model"], Command("skip"), AddService.enter_model)
    dp.message.register(handlers["cancel_add"], Command("cancel"), AddService.select_provider)
    dp.message.register(handlers["cancel_add"], Command("cancel"), AddService.enter_api_key)
    dp.message.register(handlers["cancel_add"], Command("cancel"), AddService.enter_base_url)
    dp.message.register(handlers["cancel_add"], Command("cancel"), AddService.enter_model)
