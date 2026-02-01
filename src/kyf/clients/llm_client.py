"""LLM client abstraction following Interface Segregation and Dependency Inversion.

Defines an abstract interface so the agent doesn't depend on a specific LLM provider.
GeminiClient is the concrete implementation for Google's Gemini API.
"""

import json
from abc import ABC, abstractmethod

from google import genai
from google.genai import types
from pydantic import SecretStr
from tenacity import retry, stop_after_attempt, wait_exponential

from kyf.logger import get_logger
from kyf.models.llm import LLMConfig

logger = get_logger(__name__)


class LLMClient(ABC):
    """Abstract interface for LLM providers (Dependency Inversion Principle)."""

    @abstractmethod
    async def generate(self, system_prompt: str, user_prompt: str) -> str:
        """Generate a text response given system and user prompts."""
        ...

    @abstractmethod
    async def generate_json(self, system_prompt: str, user_prompt: str) -> dict:
        """Generate a structured JSON response."""
        ...


class GeminiClient(LLMClient):
    """Concrete LLM client using Google Gemini API."""

    def __init__(self, api_key: SecretStr, config: LLMConfig | None = None) -> None:
        self._config = config or LLMConfig()
        self._client = genai.Client(api_key=api_key.get_secret_value())

    def _build_config(self, as_json: bool = False) -> types.GenerateContentConfig:
        config = types.GenerateContentConfig(
            temperature=self._config.temperature,
            max_output_tokens=self._config.max_output_tokens,
        )
        if as_json:
            config.response_mime_type = "application/json"
        return config

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def generate(self, system_prompt: str, user_prompt: str) -> str:
        response = await self._client.aio.models.generate_content(
            model=self._config.model,
            contents=[
                types.Content(
                    role="user",
                    parts=[types.Part(text=f"{system_prompt}\n\n{user_prompt}")],
                ),
            ],
            config=self._build_config(),
        )
        result = response.text or ""
        logger.debug("llm_generate", model=self._config.model, output_len=len(result))
        return result

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def generate_json(self, system_prompt: str, user_prompt: str) -> dict:
        response = await self._client.aio.models.generate_content(
            model=self._config.model,
            contents=[
                types.Content(
                    role="user",
                    parts=[types.Part(text=f"{system_prompt}\n\n{user_prompt}")],
                ),
            ],
            config=self._build_config(as_json=True),
        )
        raw = response.text or "{}"
        logger.debug("llm_generate_json", model=self._config.model, output_len=len(raw))
        return json.loads(raw)
