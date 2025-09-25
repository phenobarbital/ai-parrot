"""
MCP (Model Context Protocol) Tool Integration for AI-Parrot
==========================================================

This module provides MCP server integration as tools within the AI-parrot framework.
Supports various MCP transports including HTTP/SSE, stdio, and OAuth authentication.
"""
import logging
import os
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from contextlib import AsyncExitStack
# AI-Parrot imports
from ..tools.abstract import AbstractTool, ToolResult
from ..tools.manager import ToolManager
from ..bots.agent import BasicAgent
# MCP imports
try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.client.sse import sse_client
    import mcp.types as mcp_types
except ImportError:
    raise ImportError(
        "MCP dependencies not found. Please install: pip install mcp python-dotenv"
    )


@dataclass
class MCPServerConfig:
    """Configuration for MCP server connection."""
    name: str
    url: Optional[str] = None  # For HTTP/SSE servers
    command: Optional[str] = None  # For stdio servers (e.g., "python", "node")
    args: Optional[List[str]] = None  # Command arguments
    env: Optional[Dict[str, str]] = None  # Environment variables

    # Authentication
    auth_type: Optional[str] = None  # "oauth", "bearer", "basic", "none"
    auth_config: Dict[str, Any] = field(default_factory=dict)

    # Transport type
    transport: str = "auto"  # "auto", "stdio", "sse", "http"

    # Additional headers for HTTP transports
    headers: Dict[str, str] = field(default_factory=dict)

    # Connection settings
    timeout: float = 30.0
    retry_count: int = 3

    # Tool filtering
    allowed_tools: Optional[List[str]] = None
    blocked_tools: Optional[List[str]] = None


class MCPOAuthHandler:
    """Handles OAuth authentication for MCP servers."""

    def __init__(self, config: Dict[str, Any]):
        self.client_id = config.get('client_id')
        self.client_secret = config.get('client_secret')
        self.auth_url = config.get('auth_url')
        self.token_url = config.get('token_url')
        self.redirect_uri = config.get(
            'redirect_uri', 'http://localhost:8080/callback'
        )
        self.scope = config.get('scope', '')
        self._access_token = config.get('access_token')
        self._refresh_token = config.get('refresh_token')

    async def get_access_token(self) -> str:
        """Get or refresh access token."""
        if self._access_token:
            # TODO: Check if token is expired and refresh if needed
            return self._access_token

        # For now, assume token is provided in config
        # In production, implement full OAuth flow
        if not self._access_token:
            raise ValueError(
                "No access token provided. Please implement OAuth flow or provide token in config."
            )

        return self._access_token

    async def get_auth_headers(self) -> Dict[str, str]:
        """Get authentication headers."""
        token = await self.get_access_token()
        return {"Authorization": f"Bearer {token}"}


class MCPToolProxy(AbstractTool):
    """Proxy tool that wraps an individual MCP tool."""

    def __init__(
        self,
        mcp_tool_def: Dict[str, Any],
        mcp_client: 'MCPClient',
        server_name: str,
        **kwargs
    ):
        super().__init__(**kwargs)

        self.mcp_tool_def = mcp_tool_def
        self.mcp_client = mcp_client
        self.server_name = server_name

        # Extract tool information from MCP definition
        self.name = f"mcp_{server_name}_{mcp_tool_def['name']}"
        self.description = mcp_tool_def.get(
            'description',
            f"MCP tool: {mcp_tool_def['name']}"
        )

        # Convert MCP input schema to our format
        self.input_schema = mcp_tool_def.get('inputSchema', {})

        self.logger = logging.getLogger(f"MCPTool.{self.name}")

    async def _execute(self, **kwargs) -> Any:
        """Execute the MCP tool."""
        try:
            # Call the MCP tool through the client
            result = await self.mcp_client.call_tool(
                self.mcp_tool_def['name'],
                kwargs
            )

            # Convert MCP result to our format
            if hasattr(result, 'content') and result.content:
                # Extract text content from MCP response
                content = []
                for item in result.content:
                    if hasattr(item, 'text'):
                        content.append(item.text)
                    elif isinstance(item, dict) and 'text' in item:
                        content.append(item['text'])
                    else:
                        content.append(str(item))

                return ToolResult(
                    status="success",
                    result="\n".join(content) if len(content) > 1 else content[0] if content else str(result),
                    metadata={
                        "server": self.server_name,
                        "tool": self.mcp_tool_def['name']
                    }
                )
            else:
                return ToolResult(
                    status="success",
                    result=str(result),
                    metadata={
                        "server": self.server_name,
                        "tool": self.mcp_tool_def['name']
                    }
                )

        except Exception as e:
            self.logger.error(f"Error executing MCP tool {self.name}: {e}")
            return ToolResult(
                status="error",
                result=None,
                error=str(e),
                metadata={
                    "server": self.server_name,
                    "tool": self.mcp_tool_def['name']
                }
            )


class MCPClient:
    """MCP client wrapper for AI-parrot integration."""
    def __init__(self, config: MCPServerConfig):
        self.config = config
        self.session: Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()
        self.logger = logging.getLogger(f"Parrot.MCPClient.{config.name}")

        # Authentication handler
        self.auth_handler = None
        if config.auth_type == "oauth":
            self.auth_handler = MCPOAuthHandler(config.auth_config)

        self._connected = False
        self._available_tools = []

    async def connect(self):
        """Connect to the MCP server."""
        if self._connected:
            return

        try:
            # Determine transport type
            transport = self._detect_transport()

            if transport == "stdio":
                await self._connect_stdio()
            elif transport in ["sse", "http"]:
                await self._connect_http_sse()
            else:
                raise ValueError(
                    f"Unsupported transport type: {transport}"
                )

            # Initialize session
            await self.session.initialize()

            # List available tools
            tools_result = await self.session.list_tools()
            self._available_tools = tools_result.tools if hasattr(tools_result, 'tools') else []

            self._connected = True
            self.logger.info(f"Connected to MCP server {self.config.name}")
            self.logger.info(f"Available tools: {[t.name for t in self._available_tools]}")

        except Exception as e:
            self.logger.error(f"Failed to connect to MCP server {self.config.name}: {e}")
            raise

    def _detect_transport(self) -> str:
        """Auto-detect transport type."""
        if self.config.transport != "auto":
            return self.config.transport

        if self.config.url:
            return "sse"  # Default to SSE for HTTP URLs
        elif self.config.command:
            return "stdio"
        else:
            raise ValueError("Cannot auto-detect transport. Please specify url or command.")

    async def _connect_stdio(self):
        """Connect using stdio transport."""
        if not self.config.command:
            raise ValueError("Command is required for stdio transport")

        args = self.config.args or []
        env = dict(os.environ)
        if self.config.env:
            env.update(self.config.env)

        server_params = StdioServerParameters(
            command=self.config.command,
            args=args,
            env=env
        )

        stdio_session = await self.exit_stack.enter_async_context(
            stdio_client(server_params)
        )

        self.session = stdio_session

    async def _connect_http_sse(self):
        """Connect using HTTP/SSE transport."""
        if not self.config.url:
            raise ValueError(
                "URL is required for HTTP/SSE transport"
            )

        headers = dict(self.config.headers)

        # Add authentication headers
        if self.auth_handler:
            auth_headers = await self.auth_handler.get_auth_headers()
            headers.update(auth_headers)

        # Use SSE client
        sse_session = await self.exit_stack.enter_async_context(
            sse_client(self.config.url, headers=headers)
        )

        self.session = sse_session

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]):
        """Call an MCP tool."""
        if not self._connected:
            await self.connect()

        try:
            result = await self.session.call_tool(tool_name, arguments)
            return result
        except Exception as e:
            self.logger.error(f"Error calling tool {tool_name}: {e}")
            raise

    async def list_resources(self):
        """List available MCP resources."""
        if not self._connected:
            await self.connect()

        try:
            return await self.session.list_resources()
        except Exception as e:
            self.logger.error(f"Error listing resources: {e}")
            return None

    async def read_resource(self, uri: str):
        """Read an MCP resource."""
        if not self._connected:
            await self.connect()

        try:
            return await self.session.read_resource(uri)
        except Exception as e:
            self.logger.error(f"Error reading resource {uri}: {e}")
            return None

    def get_available_tools(self) -> List[Dict[str, Any]]:
        """Get list of available tools."""
        tools = []
        for tool in self._available_tools:
            tool_dict = {
                'name': tool.name,
                'description': tool.description,
                'inputSchema': tool.inputSchema.__dict__ if hasattr(tool, 'inputSchema') else {}
            }
            tools.append(tool_dict)
        return tools

    async def disconnect(self):
        """Disconnect from MCP server."""
        if self.session:
            try:
                await self.exit_stack.aclose()
            except Exception as e:
                self.logger.error(f"Error disconnecting: {e}")

        self._connected = False


class MCPToolManager:
    """Manages multiple MCP servers and their tools."""

    def __init__(self, tool_manager: ToolManager):
        self.tool_manager = tool_manager
        self.mcp_clients: Dict[str, MCPClient] = {}
        self.logger = logging.getLogger("MCPToolManager")

    async def add_mcp_server(self, config: MCPServerConfig) -> List[str]:
        """Add an MCP server and register its tools."""
        client = MCPClient(config)

        try:
            await client.connect()
            self.mcp_clients[config.name] = client

            # Register all tools from this server
            available_tools = client.get_available_tools()
            registered_tools = []

            for tool_def in available_tools:
                # Apply tool filtering
                if config.allowed_tools and tool_def['name'] not in config.allowed_tools:
                    continue
                if config.blocked_tools and tool_def['name'] in config.blocked_tools:
                    continue

                # Create proxy tool
                proxy_tool = MCPToolProxy(
                    mcp_tool_def=tool_def,
                    mcp_client=client,
                    server_name=config.name
                )

                # Register with tool manager
                self.tool_manager.register_tool(proxy_tool)
                registered_tools.append(proxy_tool.name)

                self.logger.info(f"Registered MCP tool: {proxy_tool.name}")

            return registered_tools

        except Exception as e:
            self.logger.error(f"Failed to add MCP server {config.name}: {e}")
            raise

    async def remove_mcp_server(self, server_name: str):
        """Remove an MCP server and unregister its tools."""
        if server_name in self.mcp_clients:
            client = self.mcp_clients[server_name]

            # Remove tools from tool manager
            tools_to_remove = []
            for tool_name in self.tool_manager.list_tools():
                if tool_name.startswith(f"mcp_{server_name}_"):
                    tools_to_remove.append(tool_name)

            for tool_name in tools_to_remove:
                self.tool_manager.unregister_tool(tool_name)
                self.logger.info(f"Unregistered MCP tool: {tool_name}")

            # Disconnect client
            await client.disconnect()
            del self.mcp_clients[server_name]

    async def disconnect_all(self):
        """Disconnect all MCP clients."""
        for client in self.mcp_clients.values():
            await client.disconnect()
        self.mcp_clients.clear()

    def list_mcp_servers(self) -> List[str]:
        """List connected MCP servers."""
        return list(self.mcp_clients.keys())

    def get_mcp_client(self, server_name: str) -> Optional[MCPClient]:
        """Get MCP client by server name."""
        return self.mcp_clients.get(server_name)


# Extension for BaseAgent
class MCPEnabledAgent:
    """Mixin to add MCP capabilities to BaseAgent."""

    def __init__(self, *args, **kwargs):
        self.tool_manager = kwargs.pop("tool_manager", None)
        super().__init__(*args, **kwargs)
        self.mcp_manager = MCPToolManager(self.tool_manager)

    async def add_mcp_server(
        self,
        name: str,
        url: Optional[str] = None,
        command: Optional[str] = None,
        args: Optional[List[str]] = None,
        auth_type: Optional[str] = None,
        auth_config: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> List[str]:
        """Add an MCP server as tools."""
        config = MCPServerConfig(
            name=name,
            url=url,
            command=command,
            args=args,
            auth_type=auth_type,
            auth_config=auth_config or {},
            **kwargs
        )

        return await self.mcp_manager.add_mcp_server(config)

    async def add_fireflies_mcp(
        self,
        access_token: str,
        server_name: str = "fireflies"
    ) -> List[str]:
        """Add Fireflies.ai MCP server with OAuth authentication."""
        return await self.add_mcp_server(
            name=server_name,
            url="https://api.fireflies.ai/mcp",
            auth_type="oauth",
            auth_config={
                "access_token": access_token
            },
            headers={
                "Content-Type": "application/json",
                "User-Agent": "AI-Parrot-MCP-Client/1.0"
            }
        )

    async def remove_mcp_server(self, server_name: str):
        """Remove an MCP server."""
        await self.mcp_manager.remove_mcp_server(server_name)

    def list_mcp_servers(self) -> List[str]:
        """List connected MCP servers."""
        return self.mcp_manager.list_mcp_servers()

    async def shutdown(self, **kwargs):
        """Extended shutdown to disconnect MCP clients."""
        if hasattr(self, 'mcp_manager'):
            await self.mcp_manager.disconnect_all()

        # Call parent shutdown if it exists
        if hasattr(super(), 'shutdown'):
            await super().shutdown(**kwargs)


def create_local_mcp_server(
    name: str,
    script_path: str,
    interpreter: str = "python"
) -> MCPServerConfig:
    """Create configuration for local MCP server."""
    return MCPServerConfig(
        name=name,
        command=interpreter,
        args=[script_path],
        transport="stdio"
    )
