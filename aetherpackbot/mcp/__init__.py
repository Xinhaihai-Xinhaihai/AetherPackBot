"""MCP layer — Model Context Protocol, separate from Brain knobs.

One MCP server can bind many cortex models.
"""

from aetherpackbot.mcp.protocol import McpServerConfig, McpTool
from aetherpackbot.mcp.client import McpManager

__all__ = ["McpServerConfig", "McpTool", "McpManager"]
