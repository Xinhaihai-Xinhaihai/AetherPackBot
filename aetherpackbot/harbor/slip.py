"""A slip is a live berth with tide, cooldown, and send path."""
from __future__ import annotations

import time
from typing import Any, Awaitable, Callable

from aetherpackbot.harbor.berth import Berth, Tide
from aetherpackbot.harbor.wire import DockLane, HarborWireError
from aetherpackbot.kernel.logging import get_logger
from aetherpackbot.protocols.messages import Message, MessageChain, MessageSession
from aetherpackbot.protocols.platforms import (
    BasePlatformAdapter,
    PlatformCapabilities,
    PlatformConfig,
    PlatformStatus,
)

logger = get_logger("harbor.slip")


class HarborSlip(BasePlatformAdapter):
    """One configured dock slip. Agent talks to this, not to vendor SDKs."""

    def __init__(self, config: PlatformConfig, berth: Berth, lane: DockLane) -> None:
        super().__init__(config)
        self.berth = berth
        self.lane = lane
        self.tide = Tide()
        self._listen_task = None
        self._capabilities = berth.capabilities or PlatformCapabilities()

    @property
    def creds(self) -> dict[str, Any]:
        return dict(self._config.credentials or {})

    @property
    def settings(self) -> dict[str, Any]:
        return dict(self._config.settings or {})

    async def beat(self) -> Tide:
        t0 = time.time()
        call = self.berth.ping_call(self.creds, self.settings)
        if call is None:
            self.tide = Tide(
                ok=False,
                reachable=False,
                hint="no credential / endpoint",
                checked_at=time.time(),
            )
            self._set_status(PlatformStatus.DISCONNECTED)
            return self.tide
        try:
            reply = await self.lane.request(call)
            tide = self.berth.read_tide(reply, self.creds)
            tide.latency_ms = int((time.time() - t0) * 1000)
            tide.checked_at = time.time()
            if not tide.reachable:
                tide.reachable = reply.status > 0
            self.tide = tide
            self._set_status(PlatformStatus.CONNECTED if tide.ok else PlatformStatus.ERROR)
            return tide
        except Exception as e:
            self.tide = Tide(
                ok=False,
                reachable=False,
                hint=f"{type(e).__name__}: {e}"[:200],
                latency_ms=int((time.time() - t0) * 1000),
                checked_at=time.time(),
            )
            self._set_status(PlatformStatus.ERROR)
            return self.tide

    async def start(self) -> None:
        self._set_status(PlatformStatus.CONNECTING)
        await self.lane.open()
        tide = await self.beat()
        if tide.ok:
            self._set_status(PlatformStatus.CONNECTED)
        else:
            self._set_status(PlatformStatus.ERROR)
            logger.warning("slip %s tide fail: %s", self.platform_id, tide.hint)

    async def stop(self) -> None:
        self._set_status(PlatformStatus.DISCONNECTED)

    async def send_message(
        self,
        session: MessageSession,
        chain: MessageChain,
        reply_to: str | None = None,
    ) -> str | None:
        if self.status != PlatformStatus.CONNECTED and not self.tide.ok:
            await self.beat()
        try:
            return await self.berth.send(
                self.lane, self.creds, self.settings, session, chain, reply_to
            )
        except HarborWireError as e:
            logger.warning("slip %s send fail: %s", self.platform_id, e)
            raise

    def snapshot(self) -> dict[str, Any]:
        return {
            "id": self.platform_id,
            "kind": self.platform_type,
            "berth": self.berth.name,
            "status": self.status.name,
            "tide": {
                "ok": self.tide.ok,
                "reachable": self.tide.reachable,
                "status": self.tide.status,
                "latency_ms": self.tide.latency_ms,
                "hint": self.tide.hint[:180],
            },
        }
