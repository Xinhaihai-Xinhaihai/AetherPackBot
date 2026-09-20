"""Brain nodes.

Keep the old class names so the rest of the kernel does not care
that vendor SDKs are gone. Everything is a CortexNode now.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator

from aetherpackbot.protocols.providers import (
    LLMRequest,
    LLMResponse,
    ProviderConfig,
    StreamingChunk,
)
from aetherpackbot.kernel.logging import get_logger

logger = get_logger("providers")


class BaseLLMProvider(ABC):
    def __init__(self, config: ProviderConfig) -> None:
        self._config = config
        self._model = config.model
        self._api_key = config.api_key
        self._api_base = config.api_base_url

    @property
    def provider_id(self) -> str:
        return self._config.provider_id

    @property
    def model(self) -> str:
        return self._model

    @property
    def config(self) -> ProviderConfig:
        return self._config

    @abstractmethod
    async def chat(self, request: LLMRequest) -> LLMResponse:
        pass

    @abstractmethod
    async def chat_stream(self, request: LLMRequest) -> AsyncIterator[StreamingChunk]:
        pass

    async def health_check(self) -> bool:
        try:
            from aetherpackbot.protocols.providers import LLMMessage

            request = LLMRequest(
                messages=[LLMMessage(role="user", content="Reply with exactly: PONG")],
                max_tokens=128,
                temperature=0,
            )
            response = await self.chat(request)
            return bool(response.content)
        except Exception as e:
            logger.warning(f"Health check failed for {self.provider_id}: {e}")
            return False


def _spawn(config: ProviderConfig, dialect_name: str):
    from aetherpackbot.providers.cortex import CortexNode
    from aetherpackbot.providers.dialects import classify_lane, resolve_dialect
    from aetherpackbot.providers.wire import HttpLane

    # dialect holds the shared lane later; manager injects the real one
    dialect = resolve_dialect(dialect_name, HttpLane())
    return CortexNode(config, dialect, classify_lane(config.api_base_url))


class OpenAIProvider(BaseLLMProvider):
    def __new__(cls, config: ProviderConfig):
        return _spawn(config, "openai_compat")


class OpenAIOfficialProvider(BaseLLMProvider):
    def __new__(cls, config: ProviderConfig):
        return _spawn(config, "openai_official")


class AnthropicProvider(BaseLLMProvider):
    def __new__(cls, config: ProviderConfig):
        return _spawn(config, "anthropic")


class GeminiProvider(BaseLLMProvider):
    def __new__(cls, config: ProviderConfig):
        return _spawn(config, "gemini")
