"""HarborMaster: pick a live slip, keep tides, talk in Manifests."""
from __future__ import annotations

import asyncio
from typing import Any, TYPE_CHECKING

from aetherpackbot.harbor.berth import BERTHS, resolve_berth
from aetherpackbot.harbor.slip import HarborSlip
from aetherpackbot.harbor.wire import DockLane
from aetherpackbot.kernel.logging import get_logger
from aetherpackbot.protocols.messages import MessageChain, MessageSession
from aetherpackbot.protocols.platforms import PlatformConfig, PlatformStatus

if TYPE_CHECKING:
    from aetherpackbot.kernel.container import ServiceContainer
    from aetherpackbot.messaging.events import EventDispatcher

logger = get_logger("harbor")


class HarborMaster:
    def __init__(self, container: "ServiceContainer", event_dispatcher: "EventDispatcher") -> None:
        self._container = container
        self._event_dispatcher = event_dispatcher
        self.lane = DockLane()
        self.slips: dict[str, HarborSlip] = {}

    async def start(self) -> None:
        from aetherpackbot.storage.config import ConfigurationManager

        await self.lane.open()
        config_manager = await self._container.resolve(ConfigurationManager)
        platforms = config_manager.get("platforms", []) or []
        for item in platforms:
            if not item.get("enabled", True):
                continue
            try:
                await self.register_from_config(item)
            except Exception as e:
                logger.error("harbor register fail: %s", e)
        for slip in self.slips.values():
            try:
                await slip.start()
            except Exception as e:
                logger.error("harbor start %s fail: %s", slip.platform_id, e)
        logger.info("harbor opened %s slips", len(self.slips))

    async def stop(self) -> None:
        for slip in self.slips.values():
            try:
                await slip.stop()
            except Exception as e:
                logger.error("harbor stop %s fail: %s", slip.platform_id, e)
        await self.lane.close()
        self.slips.clear()

    async def register_from_config(self, data: dict[str, Any]) -> HarborSlip:
        kind = str(data.get("type") or data.get("kind") or "")
        berth = resolve_berth(kind)
        creds = dict(data.get("credentials") or {})
        # allow flat keys for convenience
        for k in (
            "token",
            "bot_token",
            "access_token",
            "page_token",
            "app_id",
            "secret",
            "base_url",
            "http_url",
            "ws_url",
            "sync_buf",
            "account_id",
            "context_tokens",
            "api_base",
        ):
            if k in data and k not in creds:
                creds[k] = data[k]
        config = PlatformConfig(
            platform_id=str(data.get("id") or f"{kind}_{len(self.slips)}"),
            platform_type=kind,
            enabled=bool(data.get("enabled", True)),
            display_name=str(data.get("name") or berth.name),
            credentials=creds,
            settings=dict(data.get("settings") or {}),
        )
        slip = HarborSlip(config, berth, self.lane)
        self.slips[config.platform_id] = slip
        return slip

    def get_slip(self, platform_id: str) -> HarborSlip | None:
        return self.slips.get(platform_id)

    def get_adapter(self, platform_id: str):
        return self.get_slip(platform_id)

    def get_all_adapters(self) -> dict[str, HarborSlip]:
        return dict(self.slips)

    def list_platform_ids(self) -> list[str]:
        return list(self.slips.keys())

    async def send_message(
        self,
        platform_id: str,
        session: MessageSession,
        chain: MessageChain,
        reply_to: str | None = None,
    ) -> str | None:
        slip = self.get_slip(platform_id)
        if not slip:
            logger.warning("no slip %s", platform_id)
            return None
        return await slip.send_message(session, chain, reply_to)

    def get_status(self) -> dict[str, dict[str, Any]]:
        return {pid: slip.snapshot() for pid, slip in self.slips.items()}

    async def pulse_all(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for pid, slip in self.slips.items():
            tide = await slip.beat()
            out[pid] = {
                "ok": tide.ok,
                "reachable": tide.reachable,
                "status": tide.status,
                "latency_ms": tide.latency_ms,
                "hint": tide.hint[:180],
                "berth": slip.berth.name,
            }
        return out

    @staticmethod
    def berth_names() -> list[str]:
        return sorted(set(b.name for b in BERTHS.values()))
