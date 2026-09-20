"""Cortex node.

One brain endpoint with pulse, retry, and lane split (local / cloud).
Long-run stability lives here, not in vendor SDKs.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from aetherpackbot.protocols.providers import (
    LLMMessage,
    LLMRequest,
    LLMResponse,
    ProviderCapabilities,
    ProviderConfig,
    StreamingChunk,
)
from aetherpackbot.providers.base import BaseLLMProvider
from aetherpackbot.providers.dialects import Dialect, classify_lane, resolve_dialect
from aetherpackbot.providers.wire import BrainWireError, HttpLane
from aetherpackbot.kernel.logging import get_logger

logger = get_logger("brain.cortex")

RETRYABLE = {408, 409, 425, 429, 500, 502, 503, 504}


def _shape_message(msg: LLMMessage, caps: ProviderCapabilities) -> LLMMessage:
    content = msg.content
    if isinstance(content, list):
        kept: list[Any] = []
        for part in content:
            if not isinstance(part, dict):
                if caps.enable_text:
                    kept.append(part)
                continue
            kind = str(part.get("type") or "")
            is_image = kind in {"image", "image_url", "input_image"} or "image_url" in part
            if is_image and not caps.enable_vision:
                continue
            if (not is_image) and not caps.enable_text:
                continue
            kept.append(part)
        content = kept if kept else ("" if not caps.enable_text else content)
    elif not caps.enable_text:
        content = ""
    return LLMMessage(
        role=msg.role,
        content=content,
        name=msg.name,
        tool_calls=msg.tool_calls if caps.enable_tools else None,
        tool_call_id=msg.tool_call_id,
        metadata=msg.metadata,
    )


@dataclass
class Pulse:
    ok: bool = False
    reachable: bool = False
    status: int = 0
    latency_ms: int = 0
    score: float = 0.0
    hint: str = ""
    checked_at: float = 0.0
    lane: str = "cloud"


@dataclass
class CortexStats:
    calls: int = 0
    fails: int = 0
    last_ok_at: float = 0.0
    last_fail_at: float = 0.0
    avg_ms: float = 0.0
    cooldown_until: float = 0.0


class CortexNode(BaseLLMProvider):
    """A single configured brain, speaking one dialect on one lane."""

    def __init__(self, config: ProviderConfig, dialect: Dialect, lane_kind: str) -> None:
        super().__init__(config)
        self.dialect = dialect
        self.lane_kind = lane_kind
        self.timeout = float((config.extra or {}).get("timeout") or 60)
        self.capabilities = config.capabilities or ProviderCapabilities()
        self.pulse_state = Pulse(lane=lane_kind)
        self.stats = CortexStats()
        self._lock = asyncio.Lock()

    @property
    def dialect_name(self) -> str:
        return self.dialect.name

    @property
    def healthy(self) -> bool:
        if time.time() < self.stats.cooldown_until:
            return False
        if self.pulse_state.checked_at and not self.pulse_state.ok:
            return False
        return True

    def score(self) -> float:
        now = time.time()
        if now < self.stats.cooldown_until:
            return -1.0
        s = self.pulse_state.score
        if self.stats.calls:
            fail_rate = self.stats.fails / max(self.stats.calls, 1)
            s -= fail_rate * 40
        if self.stats.avg_ms:
            s -= min(self.stats.avg_ms / 400.0, 25)
        if self.lane_kind == "local":
            s += 8  # local gate is cheaper and usually faster
        return s

    def apply_capabilities(self, caps: ProviderCapabilities | dict[str, Any]) -> ProviderCapabilities:
        if isinstance(caps, dict):
            caps = ProviderCapabilities.from_dict({**self.capabilities.to_dict(), **caps})
        self.capabilities = caps
        self._config.capabilities = caps
        return self.capabilities

    def shape_request(self, request: LLMRequest) -> LLMRequest:
        caps = self.capabilities
        if not caps.enable_text and not caps.enable_vision:
            raise RuntimeError(f"cortex {self.provider_id}: text and vision both off")
        messages = [_shape_message(m, caps) for m in request.messages]
        tools = request.tools if caps.enable_tools else None
        tool_choice = request.tool_choice if caps.enable_tools else None
        temperature = caps.temperature if request.temperature in (None, 0.7) else request.temperature
        if request.extra.get("use_node_temperature", True):
            temperature = caps.temperature
        max_tokens = request.max_tokens if request.max_tokens is not None else caps.max_tokens
        return LLMRequest(
            messages=messages,
            model=request.model or self._model,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
            tool_choice=tool_choice,
            stream=request.stream,
            extra=request.extra,
        )

    async def chat(self, request: LLMRequest) -> LLMResponse:
        request = self.shape_request(request)
        last_err: Exception | None = None
        for attempt in range(1, 4):
            t0 = time.time()
            try:
                resp = await self.dialect.chat(
                    self._api_key,
                    self._api_base,
                    self._model,
                    request,
                    self.timeout,
                    self._config.extra or {},
                )
                self._mark_ok((time.time() - t0) * 1000)
                return resp
            except BrainWireError as e:
                last_err = e
                self._mark_fail(e)
                if e.status not in RETRYABLE or attempt == 3:
                    raise
                await asyncio.sleep(0.25 * attempt)
            except Exception as e:
                last_err = e
                self._mark_fail(e)
                raise
        raise last_err or RuntimeError("chat failed")

    async def chat_stream(self, request: LLMRequest) -> AsyncIterator[StreamingChunk]:
        request = self.shape_request(request)
        t0 = time.time()
        try:
            async for chunk in self.dialect.chat_stream(
                self._api_key,
                self._api_base,
                self._model,
                request,
                self.timeout,
                self._config.extra or {},
            ):
                yield chunk
            self._mark_ok((time.time() - t0) * 1000)
        except Exception as e:
            self._mark_fail(e)
            raise

    async def health_check(self) -> bool:
        pulse = await self.beat()
        return pulse.ok

    async def beat(self) -> Pulse:
        t0 = time.time()
        try:
            raw = await self.dialect.pulse(
                self._api_key,
                self._api_base,
                self._model,
                min(self.timeout, 12),
                self._config.extra or {},
            )
            ms = int((time.time() - t0) * 1000)
            ok = bool(raw.get("ok"))
            score = 100.0
            if not ok:
                score = 20.0 if raw.get("reachable") else 0.0
            else:
                score = max(10.0, 100.0 - ms / 80.0)
            self.pulse_state = Pulse(
                ok=ok,
                reachable=bool(raw.get("reachable")),
                status=int(raw.get("status") or 0),
                latency_ms=ms,
                score=score,
                hint=str(raw.get("hint") or ""),
                checked_at=time.time(),
                lane=self.lane_kind,
            )
        except Exception as e:
            self.pulse_state = Pulse(
                ok=False,
                reachable=False,
                status=0,
                latency_ms=int((time.time() - t0) * 1000),
                score=0.0,
                hint=str(e)[:160],
                checked_at=time.time(),
                lane=self.lane_kind,
            )
        return self.pulse_state

    def snapshot(self) -> dict[str, Any]:
        return {
            "id": self.provider_id,
            "name": self._config.provider_name,
            "dialect": self.dialect_name,
            "lane": self.lane_kind,
            "model": self._model,
            "base": self._api_base,
            "healthy": self.healthy,
            "score": round(self.score(), 2),
            "timeout": self.timeout,
            "enabled": self._config.enabled,
            "capabilities": self.capabilities.to_dict(),
            "pulse": {
                "ok": self.pulse_state.ok,
                "status": self.pulse_state.status,
                "latency_ms": self.pulse_state.latency_ms,
                "hint": self.pulse_state.hint,
            },
            "stats": {
                "calls": self.stats.calls,
                "fails": self.stats.fails,
                "avg_ms": int(self.stats.avg_ms),
            },
        }

    def _mark_ok(self, ms: float) -> None:
        self.stats.calls += 1
        self.stats.last_ok_at = time.time()
        self.stats.cooldown_until = 0
        if self.stats.avg_ms:
            self.stats.avg_ms = self.stats.avg_ms * 0.7 + ms * 0.3
        else:
            self.stats.avg_ms = ms
        self.pulse_state.ok = True
        self.pulse_state.latency_ms = int(ms)
        self.pulse_state.checked_at = time.time()

    def _mark_fail(self, err: Exception) -> None:
        self.stats.calls += 1
        self.stats.fails += 1
        self.stats.last_fail_at = time.time()
        status = getattr(err, "status", 0) or 0
        # cool down flaky cloud gates; local stays hot for retry
        if self.lane_kind == "cloud" and status in RETRYABLE:
            self.stats.cooldown_until = time.time() + min(20, 4 * self.stats.fails)
        self.pulse_state.ok = False
        self.pulse_state.hint = str(err)[:160]
        self.pulse_state.checked_at = time.time()
        logger.warning(f"cortex {self.provider_id} fail: {err}")


class BrainRouter:
    """Pick the fastest healthy cortex. Local lane wins when both are up."""

    def __init__(self, lane: HttpLane) -> None:
        self.lane = lane
        self.nodes: dict[str, CortexNode] = {}
        self.default_id: str | None = None
        self._pulse_task: asyncio.Task | None = None

    def attach(self, node: CortexNode) -> None:
        self.nodes[node.provider_id] = node
        if self.default_id is None:
            self.default_id = node.provider_id

    def drop(self, provider_id: str) -> None:
        self.nodes.pop(provider_id, None)
        if self.default_id == provider_id:
            self.default_id = next(iter(self.nodes), None)

    def get(self, provider_id: str) -> CortexNode | None:
        return self.nodes.get(provider_id)

    def pick(self, prefer: str | None = None) -> CortexNode | None:
        if prefer and prefer in self.nodes and self.nodes[prefer].healthy:
            return self.nodes[prefer]
        ranked = sorted(self.nodes.values(), key=lambda n: n.score(), reverse=True)
        for node in ranked:
            if node.healthy and node.score() >= 0:
                return node
        return ranked[0] if ranked else None

    def default(self) -> CortexNode | None:
        if self.default_id and self.default_id in self.nodes:
            node = self.nodes[self.default_id]
            if node.healthy:
                return node
        return self.pick()

    async def chat(self, request: LLMRequest, provider_id: str | None = None) -> LLMResponse:
        tried: set[str] = set()
        last_err: Exception | None = None
        node = self.pick(provider_id) if provider_id else self.default()
        while node and node.provider_id not in tried:
            tried.add(node.provider_id)
            try:
                return await node.chat(request)
            except Exception as e:
                last_err = e
                logger.warning(f"router failover {node.provider_id}: {e}")
                node = self.pick()
                if node and node.provider_id in tried:
                    node = None
                    for cand in sorted(self.nodes.values(), key=lambda n: n.score(), reverse=True):
                        if cand.provider_id not in tried:
                            node = cand
                            break
        raise last_err or RuntimeError("no healthy cortex")

    async def pulse_all(self) -> dict[str, Pulse]:
        out: dict[str, Pulse] = {}
        for pid, node in list(self.nodes.items()):
            out[pid] = await node.beat()
        return out

    def start_pulse(self, interval: float = 45.0) -> None:
        if self._pulse_task and not self._pulse_task.done():
            return

        async def _loop() -> None:
            while True:
                try:
                    await self.pulse_all()
                except Exception as e:
                    logger.warning(f"pulse loop: {e}")
                await asyncio.sleep(interval)

        self._pulse_task = asyncio.create_task(_loop())

    async def stop_pulse(self) -> None:
        if self._pulse_task:
            self._pulse_task.cancel()
            try:
                await self._pulse_task
            except asyncio.CancelledError:
                pass
            self._pulse_task = None
