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

#: MCP protocol revisions this server can speak, oldest first.
SUPPORTED_PROTOCOL_VERSIONS: tuple[str, ...] = (
    "2024-11-05",
    "2025-03-26",
    "2025-06-18",
)
#: Newest revision we support — offered when the client requests an unknown one.
LATEST_PROTOCOL_VERSION: str = SUPPORTED_PROTOCOL_VERSIONS[-1]
#: Revision assumed when the client does not send ``protocolVersion`` at all
#: (legacy hand-rolled clients); keeps historical behavior unchanged.
DEFAULT_PROTOCOL_VERSION: str = SUPPORTED_PROTOCOL_VERSIONS[0]


def negotiate_protocol_version(requested: str | None) -> str:
    """Negotiate the MCP protocol revision for an ``initialize`` request.

    Args:
        requested: The ``protocolVersion`` sent by the client, if any.

    Returns:
        The requested version when supported; the latest supported version
        when the client asked for an unknown one; the legacy default when
        the client sent no version at all.
    """
    if requested is None:
        return DEFAULT_PROTOCOL_VERSION
    if requested in SUPPORTED_PROTOCOL_VERSIONS:
        return requested
    return LATEST_PROTOCOL_VERSION


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
            "protocolVersion": negotiate_protocol_version(
                params.get("protocolVersion")
            ),
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
