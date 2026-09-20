"""Brain manager.

Registers cortex nodes from config, splits local/cloud lanes,
and keeps a pulse loop for long-run stability.
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from aetherpackbot.protocols.providers import ProviderCapabilities, ProviderConfig, ProviderType
from aetherpackbot.providers.base import BaseLLMProvider
from aetherpackbot.providers.cortex import BrainRouter, CortexNode
from aetherpackbot.providers.dialects import classify_lane, resolve_dialect
from aetherpackbot.providers.wire import HttpLane
from aetherpackbot.kernel.logging import get_logger

if TYPE_CHECKING:
    from aetherpackbot.kernel.container import ServiceContainer

logger = get_logger("providers")

# type aliases kept for old config files
TYPE_ALIASES = {
    "openai": "openai_compat",
    "openai_chat_completion": "openai_compat",
    "openai_compatible": "openai_compat",
    "azure": "openai_compat",
    "claude": "anthropic",
    "google": "gemini",
    "gemini_native": "gemini",
    "kimi": "moonshot",
    "qwen": "dashscope",
    "glm": "zhipu",
    "grok": "xai",
    "local": "ollama",
}


class ProviderManager:
    def __init__(self, container: ServiceContainer) -> None:
        self._container = container
        self._lane = HttpLane()
        self._router = BrainRouter(self._lane)
        self._providers: dict[str, CortexNode] = self._router.nodes
        self._default_provider_id: str | None = None

    @property
    def router(self) -> BrainRouter:
        return self._router

    async def initialize(self) -> None:
        from aetherpackbot.storage.config import ConfigurationManager

        await self._lane.open()
        config_manager = await self._container.resolve(ConfigurationManager)
        providers_config = config_manager.get("providers", [])

        for provider_data in providers_config:
            if not provider_data.get("enabled", True):
                continue
            try:
                await self.register_from_config(provider_data)
            except Exception as e:
                logger.error(f"Failed to register provider: {e}")

        default_id = config_manager.get("agent.default_provider", "")
        if default_id and default_id in self._providers:
            self._default_provider_id = default_id
            self._router.default_id = default_id
        elif self._providers:
            self._default_provider_id = next(iter(self._providers))
            self._router.default_id = self._default_provider_id

        logger.info(f"Initialized {len(self._providers)} cortex nodes")

    async def start(self) -> None:
        self._router.start_pulse(45.0)
        # first beat in background so boot is not blocked
        import asyncio

        asyncio.create_task(self._router.pulse_all())

    async def stop(self) -> None:
        await self._router.stop_pulse()
        await self._lane.close()
        self._providers.clear()

    def _make_node(self, config_data: dict[str, Any]) -> CortexNode:
        raw_type = str(config_data.get("type") or config_data.get("dialect") or "openai_compat")
        dialect_name = TYPE_ALIASES.get(raw_type, raw_type)
        api_base = config_data.get("api_base_url") or config_data.get("api_base")
        extra = dict(config_data.get("extra") or {})
        if config_data.get("timeout"):
            extra["timeout"] = config_data["timeout"]
        if config_data.get("headers"):
            extra["headers"] = config_data["headers"]
        if config_data.get("custom_headers"):
            extra["headers"] = config_data["custom_headers"]
        caps_raw = dict(config_data.get("capabilities") or {})
        for key in ("temperature", "enable_tools", "enable_vision", "enable_text", "max_tokens", "stream"):
            if key in config_data and key not in caps_raw:
                caps_raw[key] = config_data[key]

        config = ProviderConfig(
            provider_id=config_data.get("id") or f"{dialect_name}_{len(self._providers)}",
            provider_type=ProviderType.LLM,
            provider_name=config_data.get("name") or dialect_name,
            api_key=config_data.get("api_key") or config_data.get("key") or "",
            api_base_url=api_base,
            model=config_data.get("model") or "",
            enabled=config_data.get("enabled", True),
            capabilities=ProviderCapabilities.from_dict(caps_raw),
            extra=extra,
        )
        dialect = resolve_dialect(dialect_name, self._lane)
        lane_kind = config_data.get("lane") or classify_lane(api_base)
        node = CortexNode(config, dialect, lane_kind)
        node.dialect.lane = self._lane
        return node

    async def register_from_config(self, config_data: dict[str, Any]) -> BaseLLMProvider:
        node = self._make_node(config_data)
        self._router.attach(node)
        logger.info(
            f"Registered cortex: {node.provider_id} dialect={node.dialect_name} lane={node.lane_kind}"
        )
        return node

    def register(self, provider_id: str, provider: BaseLLMProvider) -> None:
        if isinstance(provider, CortexNode):
            provider.dialect.lane = self._lane
            self._router.attach(provider)
        else:
            self._providers[provider_id] = provider  # type: ignore[assignment]

    def unregister(self, provider_id: str) -> None:
        self._router.drop(provider_id)

    def get(self, provider_id: str) -> BaseLLMProvider | None:
        return self._router.get(provider_id)

    def get_default(self) -> BaseLLMProvider | None:
        return self._router.default()

    def set_default(self, provider_id: str) -> None:
        if provider_id not in self._providers:
            raise ValueError(f"Provider not found: {provider_id}")
        self._default_provider_id = provider_id
        self._router.default_id = provider_id

    def get_all(self) -> dict[str, BaseLLMProvider]:
        return dict(self._providers)

    def list_provider_ids(self) -> list[str]:
        return list(self._providers.keys())

    def snapshots(self) -> list[dict[str, Any]]:
        return [n.snapshot() for n in self._providers.values()]

    def apply_capabilities(self, provider_id: str, caps: dict[str, Any]) -> dict[str, Any]:
        node = self._router.get(provider_id)
        if not node:
            raise KeyError(f"provider not found: {provider_id}")
        node.apply_capabilities(caps)
        return node.snapshot()

    async def health_check_all(self) -> dict[str, bool]:
        pulses = await self._router.pulse_all()
        return {pid: p.ok for pid, p in pulses.items()}
