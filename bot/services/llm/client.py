"""OpenAI-совместимый LLM-клиент с продвинутой обработкой ошибок (как Requests.kt в Kai)."""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from openai import AsyncOpenAI
from openai import (
    APIConnectionError, APIStatusError, APIResponseValidationError,
    RateLimitError as OpenAIRateLimitError, AuthenticationError,
)

from bot.services.llm.models import (
    AuthError, ConnectionError_, ContentPolicyError, LLMError, LLMResult,
    ProviderError, RateLimitError,
)

logger = logging.getLogger(__name__)

# Максимальное количество retry при rate limit
MAX_RETRIES = 3
# Базовый delay для exponential backoff
BASE_DELAY = 1.0


class LLMClient:
    """Клиент для OpenAI-совместимых API с продвинутой обработкой ошибок."""

    def __init__(
        self,
        instance_id: str,
        base_url: str,
        api_key: str,
        default_model: str,
        provider_name: str = "",
    ):
        self.instance_id = instance_id
        self.provider_name = provider_name or instance_id
        self.base_url = base_url
        self.api_key = api_key
        self.default_model = default_model
        self._client = AsyncOpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=60.0,
            max_retries=0,  # Сами управляем retry
        )
        self._available_models: list[str] = []

    async def send(
        self,
        prompt: str,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> LLMResult:
        """Отправить запрос с retry и обработкой ошибок."""
        model = model or self.default_model
        if not model:
            return LLMResult(text="", error="No model configured", provider=self.provider_name)

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        last_error: Optional[Exception] = None

        for attempt in range(MAX_RETRIES):
            try:
                kwargs = dict(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                )
                if max_tokens:
                    kwargs["max_tokens"] = max_tokens

                response = await self._client.chat.completions.create(**kwargs)

                choice = response.choices[0]
                return LLMResult(
                    text=choice.message.content or "",
                    model=response.model or model,
                    provider=self.provider_name,
                    tokens_used=response.usage.total_tokens if response.usage else 0,
                )

            except OpenAIRateLimitError as e:
                retry_after = _parse_retry_after(e)
                logger.warning(
                    "[%s] Rate limit (attempt %d/%d), retry after %.1fs",
                    self.provider_name, attempt + 1, MAX_RETRIES, retry_after,
                )
                last_error = RateLimitError(retry_after=retry_after)
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(retry_after)

            except AuthenticationError as e:
                logger.error("[%s] Invalid API key: %s", self.provider_name, e)
                return LLMResult(
                    text="", error="Invalid API key",
                    provider=self.provider_name,
                )

            except APIConnectionError as e:
                logger.warning(
                    "[%s] Connection failed (attempt %d/%d): %s",
                    self.provider_name, attempt + 1, MAX_RETRIES, e,
                )
                last_error = ConnectionError_(str(e))
                if attempt < MAX_RETRIES - 1:
                    delay = BASE_DELAY * (2 ** attempt)
                    await asyncio.sleep(delay)

            except APIStatusError as e:
                status = e.response.status_code
                body = str(e.response.text)[:500] if e.response.text else ""
                logger.error(
                    "[%s] API error %d: %s",
                    self.provider_name, status, body,
                )

                # Content policy violation
                if status == 400 and ("content" in body.lower() or "policy" in body.lower()):
                    return LLMResult(
                        text="", error=f"Content blocked by moderation",
                        provider=self.provider_name,
                    )

                # 401/403
                if status in (401, 403):
                    return LLMResult(
                        text="", error=f"Authentication failed (HTTP {status})",
                        provider=self.provider_name,
                    )

                # 429 — rate limit (без OpenAIRateLimitError)
                if status == 429:
                    last_error = RateLimitError()
                    if attempt < MAX_RETRIES - 1:
                        await asyncio.sleep(BASE_DELAY * (2 ** attempt))
                    continue

                # 500+ — серверная ошибка, может пройти
                if status >= 500 and attempt < MAX_RETRIES - 1:
                    last_error = ProviderError(f"Server error {status}", status)
                    await asyncio.sleep(BASE_DELAY * (2 ** attempt))
                    continue

                return LLMResult(
                    text="", error=f"HTTP {status}: {body[:200]}",
                    provider=self.provider_name,
                )

            except APIResponseValidationError as e:
                logger.error("[%s] Response validation error: %s", self.provider_name, e)
                last_error = ProviderError(f"Invalid response schema: {e}")
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(BASE_DELAY)

            except asyncio.TimeoutError:
                logger.warning(
                    "[%s] Timeout (attempt %d/%d)",
                    self.provider_name, attempt + 1, MAX_RETRIES,
                )
                last_error = ConnectionError_("Request timed out")
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(BASE_DELAY * (2 ** attempt))

            except Exception as e:
                logger.exception("[%s] Unexpected error: %s", self.provider_name, e)
                return LLMResult(
                    text="", error=f"Unexpected error: {e}",
                    provider=self.provider_name,
                )

        # Все retry исчерпаны
        error_msg = str(last_error) if last_error else "Request failed after retries"
        return LLMResult(text="", error=error_msg, provider=self.provider_name)

    async def list_models(self) -> list[str]:
        """Загрузить список моделей с сервера."""
        if self._available_models:
            return self._available_models
        try:
            models = await self._client.models.list()
            self._available_models = sorted([m.id for m in models.data])
            return self._available_models
        except Exception as e:
            logger.warning("[%s] Failed to list models: %s", self.provider_name, e)
            return [self.default_model] if self.default_model else []


def _parse_retry_after(error: OpenAIRateLimitError) -> float:
    """Достать retry-after из ошибки rate limit."""
    try:
        if error.response and error.response.headers:
            val = error.response.headers.get("retry-after", "1")
            return float(val)
    except (ValueError, AttributeError):
        pass
    return 1.0
