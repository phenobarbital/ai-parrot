"""Core MCP server base — tool registration + JSON-RPC handlers only.

This module holds the transport-agnostic, dependency-light half of the
MCP server hierarchy (FEAT-403). It has zero dependency on aiohttp, auth,
or resources — those remain server-only concerns handled by
``RemoteMCPServerBase`` in ``ai-parrot-server``.
"""
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from parrot.mcp.adapter import MCPToolAdapter
from parrot.tools.abstract import AbstractTool


@dataclass
class LocalServerConfig:
    """Lightweight config for local-only MCP servers."""

    name: str = "parrot-mcp-local"
    version: str = "1.0.0"
    description: str = ""
    log_level: str = "WARNING"


class MCPServerBase(ABC):
    """Base class for MCP servers (core, transport-agnostic)."""

    def __init__(self, config: LocalServerConfig):
        self.config = config
        self.tools: dict[str, MCPToolAdapter] = {}

        self.logger = logging.getLogger(f"MCPServer.{config.name}")
        log_level = getattr(logging, config.log_level.upper(), logging.WARNING)
        self.logger.setLevel(log_level)

    def register_tool(self, tool: AbstractTool):
        """Register an AI-Parrot tool with the MCP server."""
        tool_name = tool.name
        adapter = MCPToolAdapter(tool)
        self.tools[tool_name] = adapter
        self.logger.info("Registered tool: %s", tool_name)

    def register_tools(self, tools: list[AbstractTool]):
        """Register multiple tools."""
        for tool in tools:
            self.register_tool(tool)

    async def handle_initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle MCP initialize request."""
        self.logger.info("Initializing MCP server...")

        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {
                "tools": {
                    "listChanged": False
                }
            },
            "serverInfo": {
                "name": self.config.name,
                "version": self.config.version,
                "description": self.config.description
            }
        }

    async def handle_tools_list(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle tools/list request."""
        self.logger.info("Listing %s available tools", len(self.tools))

        tools = []
        tools.extend(
            adapter.to_mcp_tool_definition() for adapter in self.tools.values()
        )

        return {"tools": tools}

    async def handle_tools_call(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle tools/call request."""
        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        self.logger.info("Calling tool: %s with args: %s", tool_name, arguments)

        if tool_name not in self.tools:
            raise RuntimeError(
                f"Tool not found: {tool_name}"
            )

        adapter = self.tools[tool_name]
        return await adapter.execute(arguments)

    @abstractmethod
    async def start(self):
        """Start the MCP server."""

    @abstractmethod
    async def stop(self):
        """Stop the MCP server."""
