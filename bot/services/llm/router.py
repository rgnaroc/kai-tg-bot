"""LLM Router — динамическое управление провайдерами с failover (как в Kai 9000)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from bot.services.llm.client import LLMClient
from bot.services.llm.models import (
    PREDEFINED_PROVIDERS, OPENAI_COMPATIBLE, ConnectionError_,
    LLMResult, ProviderDef, ProviderType, RateLimitError, ServiceInstance,
)
from bot.services.llm.storage import ServiceStorage

logger = logging.getLogger(__name__)


@dataclass
class ProviderInfo:
    """Информация о провайдере для пользователя."""
    id: str
    display_name: str
    model_id: str
    is_active: bool
    priority: int
    is_online: bool = True


class LLMRouter:
    """Маршрутизатор с failover — если один провайдер упал, переключает на следующий."""

    def __init__(self, storage: ServiceStorage):
        self.storage = storage
        self._clients: dict[str, LLMClient] = {}
        self._current_id: str = ""  # ID текущего активного инстанса
        self._init_clients()

    def _init_clients(self):
        """Инициализировать клиенты из БД."""
        self._clients = {}
        instances = self.storage.list_instances()
        for inst in instances:
            if not inst.is_active:
                continue
            client = self._build_client(inst)
            if client:
                self._clients[inst.id] = client

        # Если нет ни одного клиента — пробуем из старого config.py (миграция)
        if not self._clients:
            self._migrate_from_env()

        # Выбрать первый активный как текущий
        if self._clients and not self._current_id:
            self._current_id = list(self._clients.keys())[0]

    def _migrate_from_env(self):
        """Миграция провайдеров из .env (если БД пуста и есть DEEPSEEK_API_KEY)."""
        import os
        deepseek_key = os.getenv("DEEPSEEK_API_KEY", "")
        groq_key = os.getenv("GROQ_API_KEY", "")
        owui_key = os.getenv("OWUI_API_KEY", "")

        if deepseek_key:
            inst = ServiceInstance(
                id="deepseek",
                service_id="deepseek",
                display_name="DeepSeek",
                api_key=deepseek_key,
                base_url="https://api.deepseek.com/v1",
                model_id=os.getenv("DEFAULT_LLM_MODEL", "deepseek-chat"),
                priority=0,
            )
            self.storage.add_instance(inst)
            if client := self._build_client(inst):
                self._clients[inst.id] = client

        if groq_key:
            inst = ServiceInstance(
                id="groq",
                service_id="groq",
                display_name="GroqCloud",
                api_key=groq_key,
                base_url="https://api.groq.com/openai/v1",
                model_id="llama-3.3-70b-versatile",
                priority=1,
            )
            self.storage.add_instance(inst)
            if client := self._build_client(inst):
                self._clients[inst.id] = client

        if owui_key:
            base = os.getenv("OWUI_BASE_URL", "https://ai.aiinfosec.ru/api")
            inst = ServiceInstance(
                id="openwebui",
                service_id="openai-compatible",
                display_name="Open WebUI",
                api_key=owui_key,
                base_url=base,
                model_id="deepseek-chat",
                priority=2,
            )
            self.storage.add_instance(inst)
            if client := self._build_client(inst):
                self._clients[inst.id] = client

        if self._clients:
            logger.info("Migrated %d providers from .env to DB", len(self._clients))
            self._current_id = list(self._clients.keys())[0]

    def _build_client(self, inst: ServiceInstance) -> Optional[LLMClient]:
        """Создать клиент для инстанса."""
        provider_def = self.storage.get_provider_def(inst.service_id)
        if not provider_def:
            logger.warning("Unknown service_id: %s", inst.service_id)
            return None

        # Определить URL
        if inst.service_id == "openai-compatible" or inst.base_url:
            base_url = inst.base_url or provider_def.chat_url
        else:
            base_url = provider_def.chat_url.rstrip("/chat/completions").rstrip("/v1")

        # Для openai-compatible добавляем /v1 если нужно
        if not base_url.endswith("/v1") and inst.service_id == "openai-compatible":
            base_url = base_url.rstrip("/") + "/v1"

        name = inst.display_name or inst.id
        return LLMClient(
            instance_id=inst.id,
            base_url=base_url,
            api_key=inst.api_key,
            default_model=inst.model_id or provider_def.default_model,
            provider_name=name,
        )

    # ─── Основной метод ─────────────────────────────────────────────────────

    async def send(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        preferred_instance: Optional[str] = None,
    ) -> LLMResult:
        """Отправить запрос с failover между провайдерами."""
        # Собираем порядок провайдеров для попытки
        candidates = []

        if preferred_instance and preferred_instance in self._clients:
            candidates.append(preferred_instance)

        if self._current_id and self._current_id not in candidates:
            candidates.append(self._current_id)

        # Остальные по priority
        for inst in self.storage.list_instances():
            if inst.id not in candidates and inst.is_active and inst.id in self._clients:
                candidates.append(inst.id)

        if not candidates:
            return LLMResult(
                text="", error="No active LLM services configured. Use /addservice to add one.",
            )

        errors = []
        for idx, instance_id in enumerate(candidates):
            client = self._clients[instance_id]
            model = ""
            inst = self.storage.get_instance(instance_id)
            if inst:
                model = inst.model_id

            result = await client.send(
                prompt=prompt,
                model=model or None,
                system_prompt=system_prompt,
                temperature=temperature,
            )

            if not result.error:
                # Успех!
                if idx > 0:
                    result.from_fallback = True
                    result.text = f"[Fallback: {result.provider}]\n\n{result.text}"
                # Запомнить текущий
                self._current_id = instance_id
                return result

            errors.append(f"{result.provider}: {result.error}")
            logger.warning(
                "Provider %s failed (%d/%d): %s",
                instance_id, idx + 1, len(candidates), result.error,
            )

        # Все провайдеры упали
        error_detail = " | ".join(errors[:3])
        return LLMResult(
            text="",
            error=f"All providers failed: {error_detail}",
        )

    # ─── Управление ─────────────────────────────────────────────────────────

    async def add_service(
        self,
        service_id: str,
        api_key: str = "",
        base_url: str = "",
        model_id: str = "",
        display_name: str = "",
    ) -> tuple[bool, str]:
        """Добавить новый сервис. Возвращает (успех, сообщение)."""
        provider_def = self.storage.get_provider_def(service_id)
        if not provider_def:
            return False, f"Unknown provider: {service_id}"

        if not display_name:
            display_name = provider_def.display_name

        instance_id = self.storage.generate_instance_id(service_id)

        # Для openai-compatible — base_url обязателен
        if service_id == "openai-compatible" and not base_url:
            return False, "OpenAI-Compatible requires a Base URL"

        priority = self.storage.next_priority()

        inst = ServiceInstance(
            id=instance_id,
            service_id=service_id,
            display_name=display_name,
            api_key=api_key,
            base_url=base_url,
            model_id=model_id or provider_def.default_model,
            priority=priority,
        )

        if self.storage.add_instance(inst):
            client = self._build_client(inst)
            if client:
                self._clients[instance_id] = client
                self._current_id = instance_id
                return True, f"✅ Added {display_name} ({instance_id})"
            else:
                self.storage.remove_instance(instance_id)
                return False, f"Failed to create client for {service_id}"
        else:
            return False, f"Instance {instance_id} already exists"

    def remove_service(self, instance_id: str) -> tuple[bool, str]:
        """Удалить сервис."""
        if instance_id not in self._clients:
            return False, f"Unknown instance: {instance_id}"

        self._clients.pop(instance_id, None)
        self.storage.remove_instance(instance_id)

        if self._current_id == instance_id:
            self._current_id = list(self._clients.keys())[0] if self._clients else ""

        return True, f"Removed {instance_id}"

    def switch(self, instance_id: str) -> tuple[bool, str]:
        """Переключить текущий сервис."""
        if instance_id not in self._clients:
            available = ", ".join(self._clients.keys())
            return False, f"Instance '{instance_id}' not found. Available: {available}"
        self._current_id = instance_id
        inst = self.storage.get_instance(instance_id)
        name = inst.display_name if inst else instance_id
        model = inst.model_id if inst else ""
        return True, f"✅ Switched to {name} ({model})"

    # ─── Информация ─────────────────────────────────────────────────────────

    def list_providers(self) -> list[ProviderInfo]:
        """Список всех подключенных провайдеров."""
        result = []
        for inst in self.storage.list_instances():
            result.append(ProviderInfo(
                id=inst.id,
                display_name=inst.display_name,
                model_id=inst.model_id,
                is_active=inst.is_active,
                priority=inst.priority,
                is_online=inst.id in self._clients,
            ))
        return result

    def format_providers_text(self) -> str:
        """Красивое текстовое описание для Telegram."""
        lines = []
        instances = self.storage.list_instances()

        if not instances:
            return "No services configured. Use /addservice to add one."

        for inst in instances:
            marker = "🟢" if inst.id == self._current_id else "⚪"
            if not inst.is_active:
                marker = "🔴"
            status = "online" if inst.id in self._clients else "offline"
            model = inst.model_id or "—"
            lines.append(
                f"{marker} **{inst.display_name}** (`{inst.id}`)\n"
                f"   Model: `{model}` | Status: {status}"
            )

        lines.insert(0, f"📌 **Current:** `{self._current_id}`\n")
        return "\n\n".join(lines)

    def get_current(self) -> Optional[ProviderInfo]:
        """Текущий активный провайдер."""
        if not self._current_id:
            return None
        inst = self.storage.get_instance(self._current_id)
        if not inst:
            return None
        return ProviderInfo(
            id=inst.id,
            display_name=inst.display_name,
            model_id=inst.model_id,
            is_active=inst.is_active,
            priority=inst.priority,
            is_online=inst.id in self._clients,
        )
