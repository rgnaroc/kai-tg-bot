"""LLM Router — выбирает провайдера, переключает по команде юзера."""

import logging
from dataclasses import dataclass, field

from bot.config import LLM_PROVIDERS, DEFAULT_PROVIDER, DEFAULT_MODEL
from bot.services.llm.base import BaseLLMClient, LLMResponse
from bot.services.llm.openai_compat import OpenAICompatClient

logger = logging.getLogger(__name__)


@dataclass
class ProviderInfo:
    name: str
    description: str
    models: list[str]
    default_model: str
    is_available: bool


@dataclass
class LLMRouter:
    """Хранит текущего провайдера и умеет переключаться."""

    current_provider: str = DEFAULT_PROVIDER
    current_model: str = DEFAULT_MODEL
    _clients: dict[str, BaseLLMClient] = field(default_factory=dict)
    _available_providers: dict[str, ProviderInfo] = field(default_factory=dict)

    def __post_init__(self):
        self._init_clients()

    def _init_clients(self):
        """Создать клиенты для всех сконфигурированных провайдеров."""
        for name, cfg in LLM_PROVIDERS.items():
            api_key = cfg.get("api_key", "")
            base_url = cfg.get("base_url", "")
            if not api_key:
                logger.warning("Провайдер %s: нет API ключа, пропущен", name)
                continue

            self._clients[name] = OpenAICompatClient(
                base_url=base_url,
                api_key=api_key,
                default_model=cfg.get("default", ""),
            )
            self._available_providers[name] = ProviderInfo(
                name=name,
                description=cfg.get("description", name),
                models=cfg.get("models", []),
                default_model=cfg.get("default", ""),
                is_available=True,
            )
            logger.info("Провайдер %s: готов (%s)", name, cfg.get("default", ""))

    def get_client(self) -> BaseLLMClient:
        """Получить текущего клиента."""
        if self.current_provider not in self._clients:
            logger.warning(
                "Провайдер %s недоступен, переключаю на %s",
                self.current_provider, DEFAULT_PROVIDER,
            )
            self.current_provider = DEFAULT_PROVIDER
            self.current_model = DEFAULT_MODEL
        return self._clients[self.current_provider]

    async def send(self, prompt: str, system_prompt: str | None = None,
                   temperature: float = 0.7) -> LLMResponse:
        """Отправить запрос через текущего провайдера."""
        client = self.get_client()
        return await client.send(
            prompt=prompt,
            model=self.current_model,
            system_prompt=system_prompt,
            temperature=temperature,
        )

    def switch(self, provider: str, model: str | None = None) -> tuple[bool, str]:
        """Переключить провайдера и/или модель. Возвращает (успех, сообщение)."""
        # Формат: "groq:llama-3.3-70b" или просто "deepseek"
        if ":" in provider:
            prov, _, mod = provider.partition(":")
            provider, model = prov, mod

        if provider not in self._available_providers:
            available = ", ".join(self._available_providers.keys())
            return False, f"Провайдер «{provider}» недоступен. Доступны: {available}"

        info = self._available_providers[provider]
        chosen_model = model or info.default_model

        if chosen_model not in info.models and info.models:
            models = ", ".join(info.models)
            return False, f"Модель «{chosen_model}» не найдена у {provider}. Доступны: {models}"

        self.current_provider = provider
        self.current_model = chosen_model
        return True, f"✅ Переключён на {provider}:{chosen_model}"

    def list_providers(self) -> str:
        """Сформировать красивый список провайдеров для /model."""
        lines = [f"📌 Текущий: **{self.current_provider}:{self.current_model}**\n"]
        for name, info in self._available_providers.items():
            marker = "➤" if name == self.current_provider else " "
            lines.append(f"{marker} **{name}** — {info.description}")
            for m in info.models:
                cm = " ← текущая" if name == self.current_provider and m == self.current_model else ""
                lines.append(f"     • `{m}`{cm}")
        return "\n".join(lines)

    def get_current_info(self) -> str:
        """Короткая строка: текущий провайдер и модель."""
        return f"{self.current_provider}:{self.current_model}"
