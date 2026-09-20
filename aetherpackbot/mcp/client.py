"""MCP client.

Talks JSON-RPC 2.0 over streamable HTTP, SSE, or local stdio.
Keeps tools listed and callable. Binding to models lives on the config.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any, TYPE_CHECKING

from aetherpackbot.kernel.logging import get_logger
from aetherpackbot.mcp.protocol import (
    MCP_PROTOCOL_VERSION,
    McpServerConfig,
    McpTool,
    jsonrpc,
    jsonrpc_notify,
)
from aetherpackbot.providers.wire import BrainWireError, HttpLane, WireCall

if TYPE_CHECKING:
    from aetherpackbot.kernel.container import ServiceContainer

logger = get_logger("mcp")


class McpSession:
    def __init__(self, config: McpServerConfig, lane: HttpLane) -> None:
        self.config = config
        self.lane = lane
        self.tools: list[McpTool] = []
        self.ok = False
        self.hint = ""
        self._rpc_id = 0
        self._session_id = ""
        self._proc: asyncio.subprocess.Process | None = None
        self._stdio_lock = asyncio.Lock()

    def _next_id(self) -> int:
        self._rpc_id += 1
        return self._rpc_id

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        headers.update(self.config.headers)
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        return headers

    async def open(self) -> None:
        if self.config.transport == "stdio":
            await self._open_stdio()
        try:
            await self._handshake()
            await self.refresh_tools()
            self.ok = True
            self.hint = f"{len(self.tools)} tools"
            logger.info(f"mcp {self.config.id} up transport={self.config.transport} tools={len(self.tools)}")
        except Exception as e:
            self.ok = False
            self.hint = str(e)[:160]
            logger.warning(f"mcp {self.config.id} open fail: {e}")

    async def close(self) -> None:
        if self._proc and self._proc.returncode is None:
            try:
                self._proc.terminate()
                await asyncio.wait_for(self._proc.wait(), timeout=3)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
        self._proc = None

    async def _open_stdio(self) -> None:
        if not self.config.command:
            raise RuntimeError("stdio mcp needs command")
        env = os.environ.copy()
        env.update(self.config.env)
        self._proc = await asyncio.create_subprocess_exec(
            self.config.command,
            *self.config.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.config.cwd or None,
            env=env,
        )

    async def _handshake(self) -> None:
        result = await self.call(
            "initialize",
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "clientInfo": {"name": "AetherPackBot", "version": "1.0.0"},
            },
        )
        if isinstance(result, dict) and result.get("protocolVersion"):
            self.hint = str(result.get("protocolVersion"))
        await self.notify("notifications/initialized")

    async def refresh_tools(self) -> list[McpTool]:
        result = await self.call("tools/list", {})
        items = []
        if isinstance(result, dict):
            items = result.get("tools") or []
        elif isinstance(result, list):
            items = result
        tools: list[McpTool] = []
        for item in items:
            if not isinstance(item, dict) or not item.get("name"):
                continue
            tools.append(
                McpTool(
                    name=str(item["name"]),
                    description=str(item.get("description") or ""),
                    input_schema=item.get("inputSchema") or item.get("input_schema") or {},
                    server_id=self.config.id,
                )
            )
        self.tools = tools
        return tools

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        return await self.call("tools/call", {"name": name, "arguments": arguments or {}})

    async def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        body = jsonrpc_notify(method, params)
        try:
            await self._send(body, expect_result=False)
        except Exception as e:
            logger.debug(f"mcp notify {method}: {e}")

    async def call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        body = jsonrpc(method, params, self._next_id())
        reply = await self._send(body, expect_result=True)
        if not isinstance(reply, dict):
            return reply
        if reply.get("error"):
            err = reply["error"]
            raise RuntimeError(f"mcp {self.config.id} {method}: {err}")
        return reply.get("result")

    async def _send(self, body: dict[str, Any], expect_result: bool) -> Any:
        transport = self.config.transport
        if transport == "stdio":
            return await self._send_stdio(body, expect_result)
        if transport == "sse":
            return await self._send_http(body, expect_result, sse=True)
        return await self._send_http(body, expect_result, sse=False)

    async def _send_http(self, body: dict[str, Any], expect_result: bool, sse: bool) -> Any:
        if not self.config.url:
            raise RuntimeError(f"mcp {self.config.id} missing url")
        call = WireCall(
            method="POST",
            url=self.config.url,
            headers=self._headers(),
            json_body=body,
            timeout=self.config.timeout,
        )
        reply = await self.lane.request(call)
        sid = reply.headers.get("Mcp-Session-Id") or reply.headers.get("mcp-session-id")
        if sid:
            self._session_id = sid
        if not expect_result:
            return None
        if not reply.ok:
            raise BrainWireError(
                f"mcp http {reply.status}: {reply.text[:300]}",
                status=reply.status,
                body=reply.text,
            )
        data = reply.json
        if data is None and reply.text:
            data = _parse_sse_json(reply.text)
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and ("result" in item or "error" in item):
                    return item
            return data[-1] if data else {}
        return data if data is not None else {}

    async def _send_stdio(self, body: dict[str, Any], expect_result: bool) -> Any:
        if not self._proc or not self._proc.stdin or not self._proc.stdout:
            raise RuntimeError(f"mcp {self.config.id} stdio not open")
        line = json.dumps(body, ensure_ascii=False) + "\n"
        async with self._stdio_lock:
            self._proc.stdin.write(line.encode("utf-8"))
            await self._proc.stdin.drain()
            if not expect_result:
                return None
            raw = await asyncio.wait_for(self._proc.stdout.readline(), timeout=self.config.timeout)
        if not raw:
            raise RuntimeError(f"mcp {self.config.id} stdio closed")
        return json.loads(raw.decode("utf-8"))

    def snapshot(self) -> dict[str, Any]:
        data = self.config.to_dict()
        data["ok"] = self.ok
        data["hint"] = self.hint
        data["tools"] = [
            {"name": t.name, "description": t.description, "server_id": t.server_id}
            for t in self.tools
        ]
        return data


def _parse_sse_json(text: str) -> Any:
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if payload in ("[DONE]", "DONE", ""):
            continue
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            continue
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


class McpManager:
    def __init__(self, container: ServiceContainer) -> None:
        self._container = container
        self._lane = HttpLane()
        self._sessions: dict[str, McpSession] = {}

    @property
    def sessions(self) -> dict[str, McpSession]:
        return self._sessions

    async def initialize(self) -> None:
        from aetherpackbot.storage.config import ConfigurationManager

        await self._lane.open()
        config_manager = await self._container.resolve(ConfigurationManager)
        servers = config_manager.get("mcp.servers", None)
        if servers is None:
            servers = config_manager.get("mcp", [])
            if isinstance(servers, dict):
                servers = servers.get("servers") or []
        if not isinstance(servers, list):
            servers = []
        for raw in servers:
            if not isinstance(raw, dict):
                continue
            cfg = McpServerConfig.from_dict(raw)
            if not cfg.enabled:
                continue
            session = McpSession(cfg, self._lane)
            self._sessions[cfg.id] = session
            try:
                await session.open()
            except Exception as e:
                logger.warning(f"mcp {cfg.id} skipped: {e}")
        logger.info(f"MCP ready {len(self._sessions)} servers")

    async def start(self) -> None:
        return

    async def stop(self) -> None:
        for session in list(self._sessions.values()):
            await session.close()
        self._sessions.clear()
        await self._lane.close()

    def tools_for(self, provider_id: str | None) -> list[McpTool]:
        out: list[McpTool] = []
        for session in self._sessions.values():
            if not session.config.enabled:
                continue
            if provider_id and not session.config.binds(provider_id):
                continue
            out.extend(session.tools)
        return out

    def snapshots(self) -> list[dict[str, Any]]:
        return [s.snapshot() for s in self._sessions.values()]

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None, server_id: str | None = None) -> Any:
        if server_id and server_id in self._sessions:
            return await self._sessions[server_id].call_tool(name, arguments)
        for session in self._sessions.values():
            if any(t.name == name for t in session.tools):
                return await session.call_tool(name, arguments)
        raise KeyError(f"mcp tool not found: {name}")

    async def apply_config(self, servers: list[dict[str, Any]]) -> None:
        await self.stop()
        await self._lane.open()
        for raw in servers:
            cfg = McpServerConfig.from_dict(raw)
            if not cfg.enabled:
                session = McpSession(cfg, self._lane)
                self._sessions[cfg.id] = session
                continue
            session = McpSession(cfg, self._lane)
            self._sessions[cfg.id] = session
            await session.open()

    async def bind_models(self, server_id: str, model_ids: list[str]) -> McpSession:
        session = self._sessions.get(server_id)
        if not session:
            raise KeyError(f"mcp server not found: {server_id}")
        session.config.bind_models = [str(x) for x in model_ids]
        from aetherpackbot.storage.config import ConfigurationManager

        config_manager = await self._container.resolve(ConfigurationManager)
        servers = list(config_manager.get("mcp.servers") or [])
        found = False
        for item in servers:
            if item.get("id") == server_id:
                item["bind_models"] = list(session.config.bind_models)
                found = True
                break
        if not found:
            servers.append(session.config.to_dict())
        config_manager.set("mcp.servers", servers)
        await config_manager.save()
        return session
