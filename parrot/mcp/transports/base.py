from abc import ABC, abstractmethod
import logging
from typing import Dict, List, Optional, Any
from aiohttp import web

from parrot.tools.abstract import AbstractTool
from parrot.mcp.config import MCPServerConfig
from parrot.mcp.adapter import MCPToolAdapter
from parrot.mcp.oauth import OAuthAuthorizationServer


class MCPServerBase(ABC):
    """Base class for MCP servers."""

    def __init__(self, config: MCPServerConfig):
        self.config = config
        self.tools: Dict[str, MCPToolAdapter] = {}
        self.logger = logging.getLogger(f"MCPServer.{config.name}")
        log_level = getattr(logging, config.log_level.upper(), logging.WARNING)
        self.logger.setLevel(log_level)
        self.oauth_server: Optional[OAuthAuthorizationServer] = None
        if self.config.enable_oauth:
            self.oauth_server = OAuthAuthorizationServer(
                default_scopes=self.config.oauth_scopes,
                allow_dynamic_registration=self.config.oauth_allow_dynamic_registration,
                token_ttl=self.config.oauth_token_ttl,
                code_ttl=self.config.oauth_code_ttl,
            )

    def register_tool(self, tool: AbstractTool):
        """Register an AI-Parrot tool with the MCP server."""
        tool_name = tool.name

        # Apply filtering
        if self.config.allowed_tools and tool_name not in self.config.allowed_tools:
            self.logger.info(f"Skipping tool {tool_name} (not in allowed_tools)")
            return

        if self.config.blocked_tools and tool_name in self.config.blocked_tools:
            self.logger.info(f"Skipping tool {tool_name} (in blocked_tools)")
            return

        adapter = MCPToolAdapter(tool)
        self.tools[tool_name] = adapter
        self.logger.info(f"Registered tool: {tool_name}")

    def register_tools(self, tools: List[AbstractTool]):
        """Register multiple tools."""
        for tool in tools:
            self.register_tool(tool)

    def _authenticate_request(self, request: web.Request) -> Optional[web.Response]:
        """Validate OAuth access token when OAuth is enabled."""
        if not self.oauth_server:
            return None

        token = self.oauth_server.bearer_token_from_header(
            request.headers.get("Authorization")
        )
        if not self.oauth_server.is_token_valid(token):
            return web.json_response(
                {
                    "error": "unauthorized",
                    "error_description": "Valid Bearer token is required",
                },
                status=401,
            )
        return None

    async def handle_initialize(self, params: Dict[str, Any]) -> Dict[str, Any]:
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

    async def handle_tools_list(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle tools/list request."""
        self.logger.info(f"Listing {len(self.tools)} available tools")

        tools = []
        tools.extend(
            adapter.to_mcp_tool_definition() for adapter in self.tools.values()
        )

        return {"tools": tools}

    async def handle_tools_call(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Handle tools/call request."""
        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        self.logger.info(f"Calling tool: {tool_name} with args: {arguments}")

        if tool_name not in self.tools:
            raise RuntimeError(
                f"Tool not found: {tool_name}"
            )

        adapter = self.tools[tool_name]
        return await adapter.execute(arguments)

    @abstractmethod
    async def start(self):
        """Start the MCP server."""
        pass

    @abstractmethod
    async def stop(self):
        """Stop the MCP server."""
        pass
