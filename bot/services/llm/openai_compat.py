"""OpenAI-совместимый клиент — подходит для DeepSeek, Groq, Open WebUI."""

from openai import AsyncOpenAI

from .base import BaseLLMClient, LLMResponse


class OpenAICompatClient(BaseLLMClient):
    """Клиент для любого OpenAI-совместимого API."""

    def __init__(self, base_url: str, api_key: str, default_model: str):
        super().__init__(base_url, api_key, default_model)
        self._client = AsyncOpenAI(base_url=base_url, api_key=api_key)
        self._available_models: list[str] = []

    async def send(self, prompt: str, model: str | None = None,
                   system_prompt: str | None = None,
                   temperature: float = 0.7) -> LLMResponse:
        model = model or self.default_model
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        response = await self._client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
        )
        choice = response.choices[0]
        return LLMResponse(
            text=choice.message.content or "",
            model=response.model,
            tokens_used=response.usage.total_tokens if response.usage else 0,
        )

    async def list_models(self) -> list[str]:
        if self._available_models:
            return self._available_models
        try:
            models = await self._client.models.list()
            self._available_models = [m.id for m in models.data]
            return self._available_models
        except Exception:
            return [self.default_model]
