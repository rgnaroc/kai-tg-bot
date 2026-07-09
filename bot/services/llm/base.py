"""Абстрактный LLM-клиент — все провайдеры реализуют этот интерфейс."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class LLMResponse:
    text: str
    model: str
    tokens_used: int = 0


class BaseLLMClient(ABC):
    """Все провайдеры наследуются от этого класса."""

    def __init__(self, base_url: str, api_key: str, default_model: str):
        self.base_url = base_url
        self.api_key = api_key
        self.default_model = default_model

    @abstractmethod
    async def send(self, prompt: str, model: str | None = None,
                   system_prompt: str | None = None,
                   temperature: float = 0.7) -> LLMResponse:
        """Отправить запрос и получить ответ."""
        ...

    @abstractmethod
    async def list_models(self) -> list[str]:
        """Вернуть список доступных моделей."""
        ...
