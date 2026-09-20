"""HTTP lane for brain dialects.

One shared transport. Dialects only describe how a vendor talks on the wire.
No official SDKs, no per-vendor client objects.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

import aiohttp

from aetherpackbot.kernel.logging import get_logger

logger = get_logger("brain.wire")


@dataclass
class WireCall:
    method: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    json_body: dict[str, Any] | None = None
    params: dict[str, str] | None = None
    timeout: float = 120.0


@dataclass
class WireReply:
    status: int
    headers: dict[str, str]
    text: str
    json: Any | None = None

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


class BrainWireError(RuntimeError):
    def __init__(self, message: str, status: int = 0, body: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.body = body


def join_url(base: str | None, path: str) -> str:
    if not base:
        return path
    root = base.rstrip("/")
    leaf = path if path.startswith("/") else f"/{path}"
    if root.endswith(leaf):
        return root
    return root + leaf


def normalize_openai_base(url: str | None) -> str:
    if not url:
        return "https://api.openai.com/v1"
    raw = url.strip().rstrip("/")
    if raw.endswith("/chat/completions"):
        raw = raw[: -len("/chat/completions")]
    if not raw.endswith("/v1") and not raw.endswith("/v4") and "/openai/v1" not in raw:
        if "openai.azure.com" not in raw and "bigmodel.cn" not in raw:
            raw = raw + "/v1"
    return raw


class HttpLane:
    """Single async HTTP lane used by every dialect."""

    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None

    async def open(self) -> None:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=180),
                trust_env=True,
            )

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None

    async def request(self, call: WireCall) -> WireReply:
        await self.open()
        assert self._session is not None
        timeout = aiohttp.ClientTimeout(total=call.timeout)
        try:
            async with self._session.request(
                call.method,
                call.url,
                headers=call.headers,
                json=call.json_body,
                params=call.params,
                timeout=timeout,
            ) as resp:
                text = await resp.text()
                parsed = None
                ctype = resp.headers.get("Content-Type", "")
                if "json" in ctype or (text and text[:1] in "{["):
                    try:
                        parsed = json.loads(text)
                    except json.JSONDecodeError:
                        parsed = None
                return WireReply(
                    status=resp.status,
                    headers={k: v for k, v in resp.headers.items()},
                    text=text,
                    json=parsed,
                )
        except aiohttp.ClientError as e:
            raise BrainWireError(f"lane error: {e}") from e

    async def sse(self, call: WireCall) -> AsyncIterator[dict[str, Any]]:
        await self.open()
        assert self._session is not None
        timeout = aiohttp.ClientTimeout(total=call.timeout, sock_read=call.timeout)
        try:
            async with self._session.request(
                call.method,
                call.url,
                headers=call.headers,
                json=call.json_body,
                params=call.params,
                timeout=timeout,
            ) as resp:
                if resp.status >= 400:
                    text = await resp.text()
                    raise BrainWireError(
                        f"stream http {resp.status}: {text[:400]}",
                        status=resp.status,
                        body=text,
                    )
                buf = ""
                async for raw in resp.content:
                    buf += raw.decode("utf-8", "replace")
                    while "\n" in buf:
                        line, buf = buf.split("\n", 1)
                        line = line.strip()
                        if not line or line.startswith(":"):
                            continue
                        if not line.startswith("data:"):
                            continue
                        payload = line[5:].strip()
                        if payload in ("[DONE]", "DONE"):
                            return
                        try:
                            yield json.loads(payload)
                        except json.JSONDecodeError:
                            continue
        except aiohttp.ClientError as e:
            raise BrainWireError(f"lane stream error: {e}") from e
