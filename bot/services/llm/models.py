"""Модели данных для LLM-слоя — Service enum, ошибки, результаты."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ─── Иерархия ошибок (как в Kai 9000) ───────────────────────────────────────


class LLMError(Exception):
    """Базовый класс для всех LLM-ошибок."""
    pass


class ConnectionError_(LLMError):
    """Не удалось соединиться с сервером."""
    pass


class RateLimitError(LLMError):
    """429 Too Many Requests."""
    def __init__(self, retry_after: Optional[float] = None):
        self.retry_after = retry_after
        super().__init__(f"Rate limit" + (f", retry after {retry_after}s" if retry_after else ""))


class AuthError(LLMError):
    """401/403 — невалидный API-ключ."""
    pass


class ContentPolicyError(LLMError):
    """Контент заблокирован модерацией."""
    def __init__(self, reason: str = ""):
        self.reason = reason
        super().__init__(f"Content policy violation: {reason}" if reason else "Content blocked")


class ProviderError(LLMError):
    """Ошибка конкретного провайдера (400, 500, и т.д.)."""
    def __init__(self, message: str, status_code: int = 0):
        self.status_code = status_code
        super().__init__(f"[{status_code}] {message}" if status_code else message)


# ─── Service enum (как sealed class Service в Kai) ──────────────────────────


class ProviderType(str, Enum):
    """Тип API — как разные методы Requests в Kai."""
    OPENAI_COMPAT = "openai-compat"  # DeepSeek, Groq, OpenRouter, Ollama...
    GEMINI = "gemini"                # Google Gemini
    ANTHROPIC = "anthropic"          # Claude


@dataclass
class ProviderDef:
    """Определение предустановленного провайдера (как data object Service в Kai)."""
    id: str
    display_name: str
    provider_type: ProviderType
    chat_url: str = ""
    models_url: str = ""
    requires_api_key: bool = True
    supports_optional_api_key: bool = False
    default_model: str = ""
    api_key_url: str = ""
    supports_pdf: bool = False
    supports_images: bool = True
    reasoning_request_mode: str = "none"  # "none" или "reasoning_content"


# ─── Все предустановленные провайдеры ───────────────────────────────────────

PREDEFINED_PROVIDERS: dict[str, ProviderDef] = {
    "deepseek": ProviderDef(
        id="deepseek", display_name="DeepSeek",
        provider_type=ProviderType.OPENAI_COMPAT,
        chat_url="https://api.deepseek.com/v1/chat/completions",
        models_url="https://api.deepseek.com/v1/models",
        default_model="deepseek-v4-flash",
        api_key_url="platform.deepseek.com/api_keys",
        supports_pdf=True,
        reasoning_request_mode="thinking_param",
    ),
    "groq": ProviderDef(
        id="groq", display_name="GroqCloud",
        provider_type=ProviderType.OPENAI_COMPAT,
        chat_url="https://api.groq.com/openai/v1/chat/completions",
        models_url="https://api.groq.com/openai/v1/models",
        api_key_url="console.groq.com/keys",
        reasoning_request_mode="none",  # Groq не принимает reasoning_content
    ),
    "openai": ProviderDef(
        id="openai", display_name="OpenAI",
        provider_type=ProviderType.OPENAI_COMPAT,
        chat_url="https://api.openai.com/v1/chat/completions",
        models_url="https://api.openai.com/v1/models",
        api_key_url="platform.openai.com/api-keys",
        supports_pdf=True,
    ),
    "openrouter": ProviderDef(
        id="openrouter", display_name="OpenRouter",
        provider_type=ProviderType.OPENAI_COMPAT,
        chat_url="https://openrouter.ai/api/v1/chat/completions",
        models_url="https://openrouter.ai/api/v1/models",
        api_key_url="openrouter.ai/settings/keys",
        supports_pdf=True,
    ),
    "gemini": ProviderDef(
        id="gemini", display_name="Gemini",
        provider_type=ProviderType.GEMINI,
        chat_url="https://generativelanguage.googleapis.com/v1beta/models/",
        api_key_url="aistudio.google.com/apikey",
        supports_pdf=True,
    ),
    "mistral": ProviderDef(
        id="mistral", display_name="Mistral AI",
        provider_type=ProviderType.OPENAI_COMPAT,
        chat_url="https://api.mistral.ai/v1/chat/completions",
        models_url="https://api.mistral.ai/v1/models",
        api_key_url="console.mistral.ai/api-keys",
    ),
    "xai": ProviderDef(
        id="xai", display_name="xAI (Grok)",
        provider_type=ProviderType.OPENAI_COMPAT,
        chat_url="https://api.x.ai/v1/chat/completions",
        models_url="https://api.x.ai/v1/models",
        api_key_url="console.x.ai",
    ),
    "together": ProviderDef(
        id="together", display_name="Together AI",
        provider_type=ProviderType.OPENAI_COMPAT,
        chat_url="https://api.together.xyz/v1/chat/completions",
        models_url="https://api.together.xyz/v1/models",
        api_key_url="api.together.ai/settings/api-keys",
    ),
    "cerebras": ProviderDef(
        id="cerebras", display_name="Cerebras",
        provider_type=ProviderType.OPENAI_COMPAT,
        chat_url="https://api.cerebras.ai/v1/chat/completions",
        models_url="https://api.cerebras.ai/v1/models",
        api_key_url="cloud.cerebras.ai",
        reasoning_request_mode="none",
    ),
    "ollama": ProviderDef(
        id="ollama", display_name="Ollama (local)",
        provider_type=ProviderType.OPENAI_COMPAT,
        chat_url="http://localhost:11434/v1/chat/completions",
        models_url="http://localhost:11434/v1/models",
        requires_api_key=False,
        default_model="llama3.2",
    ),
    "nvidia": ProviderDef(
        id="nvidia", display_name="NVIDIA",
        provider_type=ProviderType.OPENAI_COMPAT,
        chat_url="https://integrate.api.nvidia.com/v1/chat/completions",
        models_url="https://integrate.api.nvidia.com/v1/models",
        api_key_url="build.nvidia.com/settings/api-keys",
    ),
    "huggingface": ProviderDef(
        id="huggingface", display_name="Hugging Face",
        provider_type=ProviderType.OPENAI_COMPAT,
        chat_url="https://router.huggingface.co/v1/chat/completions",
        models_url="https://router.huggingface.co/v1/models",
        api_key_url="huggingface.co/settings/tokens",
    ),
    "deepinfra": ProviderDef(
        id="deepinfra", display_name="Deep Infra",
        provider_type=ProviderType.OPENAI_COMPAT,
        chat_url="https://api.deepinfra.com/v1/openai/chat/completions",
        models_url="https://api.deepinfra.com/v1/openai/models",
        api_key_url="deepinfra.com/dash/api_keys",
    ),
    "fireworks": ProviderDef(
        id="fireworks", display_name="Fireworks AI",
        provider_type=ProviderType.OPENAI_COMPAT,
        chat_url="https://api.fireworks.ai/inference/v1/chat/completions",
        models_url="https://api.fireworks.ai/inference/v1/models",
        api_key_url="app.fireworks.ai/settings/users/api-keys",
    ),
    "anthropic": ProviderDef(
        id="anthropic", display_name="Anthropic (Claude)",
        provider_type=ProviderType.ANTHROPIC,
        chat_url="https://api.anthropic.com/v1/messages",
        models_url="https://api.anthropic.com/v1/models",
        api_key_url="console.anthropic.com/settings/keys",
        supports_pdf=True,
    ),
}

# OpenAI-compatible — отдельный тип для кастомных URL
OPENAI_COMPATIBLE = ProviderDef(
    id="openai-compatible", display_name="OpenAI-Compatible",
    provider_type=ProviderType.OPENAI_COMPAT,
    chat_url="/v1/chat/completions",
    models_url="/v1/models",
    requires_api_key=False,
    supports_optional_api_key=True,
)


# ─── Инстанс сервиса ────────────────────────────────────────────────────────


@dataclass
class ServiceInstance:
    """Один экземпляр подключенного сервиса (как ServiceInstance в Kai)."""
    id: str                    # "deepseek" или "openai-compatible_2"
    service_id: str            # "deepseek", "openai-compatible"
    display_name: str          # Пользовательское название
    api_key: str = ""
    base_url: str = ""         # Для кастомных URL
    model_id: str = ""
    is_active: bool = True
    priority: int = 0


# ─── Результат запроса ──────────────────────────────────────────────────────


@dataclass
class LLMResult:
    """Результат LLM-запроса с мета-информацией."""
    text: str
    model: str = ""
    provider: str = ""
    tokens_used: int = 0
    error: Optional[str] = None
    from_fallback: bool = False
