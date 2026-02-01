"""LLM client abstraction following Interface Segregation and Dependency Inversion.

Defines an abstract interface so the agent doesn't depend on a specific LLM provider.
GroqClient is the concrete implementation for Groq's inference API.
"""

import json
import logging
from abc import ABC, abstractmethod

from groq import AsyncGroq, RateLimitError
from pydantic import SecretStr
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_not_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from kyf.logger import get_logger
from kyf.models.llm import LLMConfig

logger = get_logger(__name__)
_std_logger = logging.getLogger(__name__)


class LLMRateLimitError(Exception):
    """Raised when the LLM provider's rate or token limit is exceeded.

    Provider-agnostic — agent layer catches this without knowing about Groq.
    """

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        self.retry_after = retry_after
        super().__init__(message)


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


class GroqClient(LLMClient):
    """Concrete LLM client using Groq inference API."""

    def __init__(self, api_key: SecretStr, config: LLMConfig | None = None) -> None:
        self._config = config or LLMConfig()
        self._client = AsyncGroq(api_key=api_key.get_secret_value())

    def _handle_rate_limit(self, e: RateLimitError) -> None:
        """Convert Groq RateLimitError to our provider-agnostic LLMRateLimitError."""
        retry_after = None
        if hasattr(e, "response") and e.response is not None:
            raw = e.response.headers.get("retry-after")
            if raw:
                try:
                    retry_after = float(raw)
                except ValueError:
                    pass
        raise LLMRateLimitError(str(e), retry_after=retry_after) from e

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=10),
        retry=retry_if_not_exception_type(LLMRateLimitError),
        before_sleep=before_sleep_log(_std_logger, logging.WARNING),
    )
    async def generate(self, system_prompt: str, user_prompt: str) -> str:
        try:
            response = await self._client.chat.completions.create(
                model=self._config.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=self._config.temperature,
                max_tokens=self._config.max_output_tokens,
            )
            result = response.choices[0].message.content or ""
            logger.debug("llm_generate", model=self._config.model, output_len=len(result))
            return result
        except RateLimitError as e:
            logger.warning("llm_rate_limited", model=self._config.model, error=str(e))
            self._handle_rate_limit(e)
        except Exception as e:
            logger.error("llm_generate_error", model=self._config.model, error=str(e), error_type=type(e).__name__)
            raise

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=10),
        retry=retry_if_not_exception_type(LLMRateLimitError),
        before_sleep=before_sleep_log(_std_logger, logging.WARNING),
    )
    async def generate_json(self, system_prompt: str, user_prompt: str) -> dict:
        try:
            response = await self._client.chat.completions.create(
                model=self._config.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt + "\n\nRespond ONLY with valid JSON, no markdown or extra text."},
                ],
                temperature=self._config.temperature,
                max_tokens=self._config.max_output_tokens,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content or "{}"
            logger.debug("llm_generate_json", model=self._config.model, output_len=len(raw))
            return json.loads(raw)
        except RateLimitError as e:
            logger.warning("llm_rate_limited", model=self._config.model, error=str(e))
            self._handle_rate_limit(e)
        except Exception as e:
            logger.error("llm_generate_json_error", model=self._config.model, error=str(e), error_type=type(e).__name__)
            raise
