"""MCP wire types and per-server config.

JSON-RPC 2.0. Transports: streamable HTTP, SSE, stdio.
Binding is many-to-many: one MCP server -> many provider ids.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


MCP_PROTOCOL_VERSION = "2024-11-05"


@dataclass
class McpServerConfig:
    """One MCP server. Bind it to any number of brain models."""

    id: str
    name: str = ""
    enabled: bool = True
    # http | sse | stdio
    transport: str = "http"
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    # stdio only
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    cwd: str = ""
    timeout: float = 30.0
    # empty = every model that has tools on
    bind_models: list[str] = field(default_factory=list)

    def display_name(self) -> str:
        return self.name or self.id

    def binds(self, provider_id: str) -> bool:
        if not self.bind_models:
            return True
        return provider_id in self.bind_models

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name or self.id,
            "enabled": self.enabled,
            "transport": self.transport,
            "url": self.url,
            "headers": dict(self.headers),
            "command": self.command,
            "args": list(self.args),
            "env": dict(self.env),
            "cwd": self.cwd,
            "timeout": self.timeout,
            "bind_models": list(self.bind_models),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> McpServerConfig:
        data = data or {}
        headers = data.get("headers") or {}
        if not isinstance(headers, dict):
            headers = {}
        bind = data.get("bind_models") or data.get("models") or []
        if isinstance(bind, str):
            bind = [bind]
        env = data.get("env") or {}
        if not isinstance(env, dict):
            env = {}
        args = data.get("args") or []
        if isinstance(args, str):
            args = [args]
        transport = str(data.get("transport") or "http").strip().lower()
        if transport in {"streamable_http", "streamable-http", "jsonrpc", "rpc"}:
            transport = "http"
        if transport not in {"http", "sse", "stdio"}:
            transport = "http"
        return cls(
            id=str(data.get("id") or data.get("name") or "mcp"),
            name=str(data.get("name") or data.get("id") or ""),
            enabled=bool(data.get("enabled", True)),
            transport=transport,
            url=str(data.get("url") or data.get("endpoint") or ""),
            headers={str(k): str(v) for k, v in headers.items()},
            command=str(data.get("command") or ""),
            args=[str(a) for a in args],
            env={str(k): str(v) for k, v in env.items()},
            cwd=str(data.get("cwd") or ""),
            timeout=float(data.get("timeout") or 30),
            bind_models=[str(x) for x in bind if str(x).strip()],
        )


@dataclass
class McpTool:
    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    server_id: str = ""

    def openai_function(self) -> dict[str, Any]:
        schema = self.input_schema or {"type": "object", "properties": {}}
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description or self.name,
                "parameters": schema,
            },
        }


def jsonrpc(method: str, params: dict[str, Any] | None = None, req_id: int | str = 1) -> dict[str, Any]:
    body: dict[str, Any] = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        body["params"] = params
    return body


def jsonrpc_notify(method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        body["params"] = params
    return body
