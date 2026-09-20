"""Shared HTTP/WS lane for Harbor berths."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, AsyncIterator
from urllib.parse import urljoin

import aiohttp

from aetherpackbot.kernel.logging import get_logger

logger = get_logger("harbor.wire")


@dataclass
class TideCall:
    method: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    json_body: dict[str, Any] | None = None
    params: dict[str, Any] | None = None
    data: Any = None
    timeout: float = 45.0


@dataclass
class TideReply:
    status: int
    headers: dict[str, str]
    text: str
    json: Any | None = None

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


class HarborWireError(RuntimeError):
    def __init__(self, message: str, status: int = 0, body: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.body = body


def join_url(base: str | None, path: str) -> str:
    if not path:
        return (base or "").rstrip("/")
    if path.startswith("http://") or path.startswith("https://"):
        return path
    if not base:
        return path
    return urljoin(base.rstrip("/") + "/", path.lstrip("/"))


class DockLane:
    """One HTTP/WS lane used by every berth."""

    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None

    async def open(self) -> None:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=90),
                connector=aiohttp.TCPConnector(ssl=False, limit=40),
            )

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None

    @property
    def session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            raise HarborWireError("dock lane is closed")
        return self._session

    async def request(self, call: TideCall) -> TideReply:
        await self.open()
        timeout = aiohttp.ClientTimeout(total=call.timeout)
        try:
            async with self.session.request(
                call.method,
                call.url,
                headers=call.headers or None,
                json=call.json_body,
                params=call.params,
                data=call.data,
                timeout=timeout,
            ) as resp:
                text = await resp.text()
                parsed = None
                if text:
                    try:
                        parsed = json.loads(text)
                    except Exception:
                        parsed = None
                return TideReply(
                    status=resp.status,
                    headers={k.lower(): v for k, v in resp.headers.items()},
                    text=text,
                    json=parsed,
                )
        except HarborWireError:
            raise
        except Exception as e:
            raise HarborWireError(f"{call.method} {call.url} {type(e).__name__}: {e}") from e

    async def ws(self, url: str, headers: dict[str, str] | None = None, timeout: float = 12.0):
        await self.open()
        return self.session.ws_connect(
            url,
            headers=headers,
            heartbeat=20,
            timeout=timeout,
        )
