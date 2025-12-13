import os
from typing import Dict, List, Any, Optional, Union
import logging
from pathlib import Path
# AI-Parrot imports
from ..tools.abstract import AbstractTool, ToolResult
from ..tools.manager import ToolManager
from .oauth import (
    OAuthManager,
    InMemoryTokenStore,
    RedisTokenStore
)
from .client import (
    MCPClientConfig as MCPServerConfig,
    MCPConnectionError
)
from .transports.stdio import StdioMCPSession
from .transports.unix import UnixMCPSession
from .transports.http import HttpMCPSession
from .transports.websocket import WebSocketMCPSession
from .transports.sse import SseMCPSession
from .transports.quic import (
    QuicMCPSession,
    QuicMCPConfig,
    SerializationFormat
)


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

        self.name = f"mcp_{server_name}_{mcp_tool_def['name']}"
        self.description = mcp_tool_def.get('description', f"MCP tool: {mcp_tool_def['name']}")
        self.input_schema = mcp_tool_def.get('inputSchema', {})

        self.logger = logging.getLogger(f"MCPTool.{self.name}")

    async def _execute(self, **kwargs) -> ToolResult:
        """Execute the MCP tool."""
        try:
            result = await self.mcp_client.call_tool(
                self.mcp_tool_def['name'],
                kwargs
            )

            result_text = self._extract_result_text(result)

            return ToolResult(
                status="success",
                result=result_text,
                metadata={
                    "server": self.server_name,
                    "tool": self.mcp_tool_def['name'],
                    "transport": self.mcp_client.config.transport,
                    "mcp_response_type": type(result).__name__
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

    def _extract_result_text(self, result) -> str:
        """Extract text content from MCP response."""
        if hasattr(result, 'content') and result.content:
            content_parts = []
            for item in result.content:
                if hasattr(item, 'text'):
                    content_parts.append(item.text)
                elif isinstance(item, dict):
                    content_parts.append(item.get('text', str(item)))
                else:
                    content_parts.append(str(item))
            return "\n".join(content_parts) if content_parts else str(result)
        return str(result)


class MCPClient:
    """Complete MCP client with stdio and HTTP transport support."""

    def __init__(self, config: MCPServerConfig):
        self.config = config
        self.logger = logging.getLogger(f"MCPClient.{config.name}")
        self._session = None
        self._connected = False
        self._available_tools = []

    def _detect_transport(self) -> str:
        """Auto-detect transport type."""
        if self.config.transport != "auto":
            return self.config.transport

        if self.config.socket_path:
            return "unix"
        if self.config.url:
            # Check if URL looks like SSE endpoint
            if "events" in self.config.url or "sse" in self.config.url:
                return "sse"
            else:
                return "http"
        elif self.config.command:
            return "stdio"
        else:
            raise ValueError(
                "Cannot auto-detect transport. "
                "Please specify socket_path, url, or command."
            )

    async def connect(self):
        """Connect to MCP server using appropriate transport."""
        if self._connected:
            return

        transport = self._detect_transport()

        try:
            if transport == "stdio":
                self._session = StdioMCPSession(self.config, self.logger)
            elif transport == "http":
                self._session = HttpMCPSession(self.config, self.logger)
            elif transport == "sse":
                self._session = SseMCPSession(self.config, self.logger)
            elif transport == "unix":
                self._session = UnixMCPSession(self.config, self.logger)
            elif transport == "websocket":

                self._session = WebSocketMCPSession(self.config, self.logger)
            elif transport == "quic":
                try:
                    self._session = QuicMCPSession(self.config, self.logger)
                except ImportError as e:
                    raise ImportError(
                        "QUIC transport requires 'aioquic' package. Install with: pip install aioquic msgpack"
                    ) from e
            else:
                raise ValueError(
                    f"Unsupported transport: {transport}"
                )

            await self._session.connect()
            self._available_tools = await self._session.list_tools()
            self._connected = True

            self.logger.info(
                f"Connected to MCP server {self.config.name} "
                f"via {transport} with {len(self._available_tools)} tools"
            )

        except Exception as e:
            self.logger.error(f"Failed to connect: {e}")
            await self.disconnect()
            raise

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]):
        """Call an MCP tool."""
        if not self._connected:
            raise MCPConnectionError("Not connected to MCP server")

        return await self._session.call_tool(tool_name, arguments)

    def get_available_tools(self) -> List[Dict[str, Any]]:
        """Get available tools as dictionaries."""
        tools = []
        for tool in self._available_tools:
            tool_dict = {
                'name': getattr(tool, 'name', 'unknown'),
                'description': getattr(tool, 'description', ''),
                'inputSchema': getattr(tool, 'inputSchema', {})
            }
            tools.append(tool_dict)
        return tools

    async def disconnect(self):
        """Disconnect from MCP server."""
        if not self._connected:
            return

        self._connected = False

        if self._session:
            await self._session.disconnect()
            self._session = None

        self._available_tools = []
        self.logger.info(f"Disconnected from {self.config.name}")

    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()


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

            available_tools = client.get_available_tools()
            registered_tools = []

            for tool_def in available_tools:
                tool_name = tool_def.get('name', 'unknown')

                if self._should_skip_tool(tool_name, config):
                    continue

                proxy_tool = MCPToolProxy(
                    mcp_tool_def=tool_def,
                    mcp_client=client,
                    server_name=config.name
                )

                self.tool_manager.register_tool(proxy_tool)
                registered_tools.append(proxy_tool.name)
                self.logger.info(f"Registered MCP tool: {proxy_tool.name}")

            transport = getattr(client, '_session', None)
            transport_type = config.transport if config.transport != "auto" else "detected"

            self.logger.info(
                f"Successfully added MCP server {config.name} "
                f"({transport_type} transport) with {len(registered_tools)} tools"
            )
            return registered_tools

        except Exception as e:
            self.logger.error(f"Failed to add MCP server {config.name}: {e}")
            await self._cleanup_failed_client(config.name, client)
            raise

    def _should_skip_tool(self, tool_name: str, config: MCPServerConfig) -> bool:
        """Check if tool should be skipped based on filtering rules."""
        if config.allowed_tools and tool_name not in config.allowed_tools:
            self.logger.debug(f"Skipping tool {tool_name} (not in allowed_tools)")
            return True
        if config.blocked_tools and tool_name in config.blocked_tools:
            self.logger.debug(f"Skipping tool {tool_name} (in blocked_tools)")
            return True
        return False

    async def _cleanup_failed_client(self, server_name: str, client: MCPClient):
        """Clean up a failed client connection."""
        if server_name in self.mcp_clients:
            del self.mcp_clients[server_name]

        try:
            await client.disconnect()
        except Exception:
            pass

    async def remove_mcp_server(self, server_name: str):
        """Remove an MCP server and unregister its tools."""
        if server_name not in self.mcp_clients:
            self.logger.warning(f"MCP server {server_name} not found")
            return

        client = self.mcp_clients[server_name]

        tools_to_remove = [
            tool_name for tool_name in self.tool_manager.list_tools()
            if tool_name.startswith(f"mcp_{server_name}_")
        ]

        for tool_name in tools_to_remove:
            self.tool_manager.unregister_tool(tool_name)
            self.logger.info(f"Unregistered MCP tool: {tool_name}")

        await client.disconnect()
        del self.mcp_clients[server_name]

    async def reconfigure_mcp_server(self, config: MCPServerConfig) -> List[str]:
        """Reconfigure an existing MCP server with new configuration.

        This method removes the existing server connection and re-adds it with the
        new configuration. Useful for updating credentials or connection parameters.

        Args:
            config: New MCPServerConfig with updated parameters

        Returns:
            List of registered tool names

        Example:
            >>> # Update Fireflies API key for a different user
            >>> new_config = create_fireflies_mcp_server(api_key="new-user-api-key")
            >>> tools = await manager.reconfigure_mcp_server(new_config)
        """
        server_name = config.name

        # Remove existing server if it exists
        if server_name in self.mcp_clients:
            self.logger.info(f"Reconfiguring MCP server: {server_name}")
            await self.remove_mcp_server(server_name)
        else:
            self.logger.info(f"Adding new MCP server: {server_name}")

        # Add with new configuration
        return await self.add_mcp_server(config)

    async def disconnect_all(self):
        """Disconnect all MCP clients."""
        for client in list(self.mcp_clients.values()):
            await client.disconnect()
        self.mcp_clients.clear()

    def list_mcp_servers(self) -> List[str]:
        return list(self.mcp_clients.keys())

    def get_mcp_client(self, server_name: str) -> Optional[MCPClient]:
        return self.mcp_clients.get(server_name)


# Convenience functions for different server types
def create_local_mcp_server(
    name: str,
    script_path: Union[str, Path],
    interpreter: str = "python",
    **kwargs
) -> MCPServerConfig:
    """Create configuration for local stdio MCP server."""
    script_path = Path(script_path)
    if not script_path.exists():
        raise FileNotFoundError(f"MCP server script not found: {script_path}")

    return MCPServerConfig(
        name=name,
        command=interpreter,
        args=[str(script_path)],
        transport="stdio",
        **kwargs
    )


def create_http_mcp_server(
    name: str,
    url: str,
    auth_type: Optional[str] = None,
    auth_config: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    **kwargs
) -> MCPServerConfig:
    """Create configuration for HTTP MCP server."""
    return MCPServerConfig(
        name=name,
        url=url,
        transport="http",
        auth_type=auth_type,
        auth_config=auth_config or {},
        headers=headers or {},
        **kwargs
    )

def create_oauth_mcp_server(
    *,
    name: str,
    url: str,
    user_id: str,
    client_id: str,
    auth_url: str,
    token_url: str,
    scopes: list[str],
    client_secret: str | None = None,
    redis=None,  # pass an aioredis client if you have it; else None -> in-memory
    redirect_host: str = "127.0.0.1",
    redirect_port: int = 8765,
    redirect_path: str = "/mcp/oauth/callback",
    extra_token_params: dict | None = None,
    headers: dict | None = None,
) -> MCPServerConfig:
    token_store = RedisTokenStore(redis) if redis else InMemoryTokenStore()
    oauth = OAuthManager(
        user_id=user_id,
        server_name=name,
        client_id=client_id,
        client_secret=client_secret,
        auth_url=auth_url,
        token_url=token_url,
        scopes=scopes,
        redirect_host=redirect_host,
        redirect_port=redirect_port,
        redirect_path=redirect_path,
        token_store=token_store,
        extra_token_params=extra_token_params,
    )

    cfg = MCPServerConfig(
        name=name,
        transport="http",
        url=url,
        headers=headers or {"Content-Type": "application/json"},
        auth_type="oauth",
        auth_config={
            "auth_url": auth_url,
            "token_url": token_url,
            "scopes": scopes,
            "client_id": client_id,
            "client_secret": bool(client_secret),
            "redirect_uri": oauth.redirect_uri,
        },
        token_supplier=oauth.token_supplier,  # this is called before each request
    )

    # Attach a small helper so the client can ensure token before using the server.
    cfg._ensure_oauth_token = oauth.ensure_token  # attribute on purpose
    return cfg

def create_unix_mcp_server(
    name: str,
    socket_path: str,
    **kwargs
) -> MCPServerConfig:
    """Create a Unix socket MCP server configuration.

    Args:
        name: Server name
        socket_path: Path to Unix socket
        **kwargs: Additional MCPServerConfig parameters

    Returns:
        MCPServerConfig configured for Unix socket transport

    Example:
        >>> config = create_unix_mcp_server(
        ...     "workday",
        ...     "/tmp/parrot-mcp-workday.sock"
        ... )
        >>> async with MCPClient(config) as client:
        ...     tools = await client.list_tools()
    """
    return MCPServerConfig(
        name=name,
        transport="unix",
        socket_path=socket_path,
        **kwargs
    )


def create_websocket_mcp_server(
    name: str,
    url: str,
    auth_type: Optional[str] = None,
    auth_config: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    **kwargs
) -> MCPServerConfig:
    """Create a WebSocket MCP server configuration.

    Args:
        name: Server name
        url: WebSocket URL (ws:// or wss://)
        auth_type: Authentication type ("bearer", "api_key", "oauth", or None)
        auth_config: Authentication configuration dict
        headers: Additional HTTP headers for WebSocket upgrade
        **kwargs: Additional MCPServerConfig parameters

    Returns:
        MCPServerConfig configured for WebSocket transport

    Example:
        >>> config = create_websocket_mcp_server(
        ...     "my-ws-server",
        ...     "ws://localhost:8766/mcp/ws",
        ...     auth_type="bearer",
        ...     auth_config={"token": "my-secret-token"}
        ... )
        >>> async with MCPClient(config) as client:
        ...     tools = await client.list_tools()
    """
    return MCPServerConfig(
        name=name,
        url=url,
        transport="websocket",
        auth_type=auth_type,
        auth_config=auth_config or {},
        headers=headers or {},
        **kwargs
    )


def create_api_key_mcp_server(
    name: str,
    url: str,
    api_key: str,
    header_name: str = "X-API-Key",
    use_bearer_prefix: bool = False,
    **kwargs
) -> MCPServerConfig:
    """Create configuration for API key authenticated MCP server.

    Args:
        name: Unique name for the MCP server
        url: Base URL of the MCP server
        api_key: API key for authentication
        header_name: Header name for the API key (default: "X-API-Key")
        use_bearer_prefix: If True, prepend "Bearer " to the API key value (default: False)
        **kwargs: Additional MCPServerConfig parameters

    Returns:
        MCPServerConfig instance
    """
    return create_http_mcp_server(
        name=name,
        url=url,
        auth_type="api_key",
        auth_config={
            "api_key": api_key,
            "header_name": header_name,
            "use_bearer_prefix": use_bearer_prefix
        },
        **kwargs
    )


def create_fireflies_mcp_server(
    *,
    api_key: str,
    api_base: str = "https://api.fireflies.ai/mcp",
    **kwargs
) -> MCPServerConfig:
    """Create configuration for Fireflies MCP server using stdio transport.

    Fireflies MCP requires using npx mcp-remote as a command-line proxy.

    Args:
        api_key: Fireflies API key
        api_base: Base URL of the Fireflies MCP endpoint
        **kwargs: Additional MCPServerConfig parameters

    Returns:
        MCPServerConfig instance configured for stdio transport
    """
    return MCPServerConfig(
        name="fireflies",
        command="npx",
        args=[
            "mcp-remote",
            api_base,
            "--header",
            f"Authorization: Bearer {api_key}"
        ],
        transport="stdio",
        **kwargs
    )


def create_perplexity_mcp_server(
    api_key: str,
    *,
    name: str = "perplexity",
    timeout_ms: int = 600000,
    **kwargs
) -> MCPServerConfig:
    """Create configuration for Perplexity MCP server.

    The Perplexity MCP server provides 4 tools:
    - perplexity_search: Direct web search via Search API
    - perplexity_ask: Conversational AI with sonar-pro model
    - perplexity_research: Deep research with sonar-deep-research
    - perplexity_reason: Advanced reasoning with sonar-reasoning-pro

    Args:
        api_key: Perplexity API key (get from perplexity.ai/account/api)
        name: Server name for tool prefixing
        timeout_ms: Request timeout (default 600000ms for deep research)
        **kwargs: Additional MCPServerConfig parameters

    Returns:
        MCPServerConfig configured for Perplexity

    Example:
        >>> config = create_perplexity_mcp_server(
        ...     api_key=os.environ["PERPLEXITY_API_KEY"]
        ... )
        >>> await agent.add_mcp_server(config)
    """
    return MCPServerConfig(
        name=name,
        transport="stdio",
        command="npx",
        args=["-y", "@perplexity-ai/mcp-server"],
        env={
            "PERPLEXITY_API_KEY": api_key or os.environ.get("PERPLEXITY_API_KEY"),
            "PERPLEXITY_TIMEOUT_MS": str(timeout_ms),
        },
        startup_delay=3.0,  # npx needs time to fetch/start
        **kwargs
    )

def create_quic_mcp_server(
    name: str,
    host: str,
    port: int,
    cert_path: Optional[str] = None,
    serialization: str = "msgpack",
    **kwargs
) -> MCPServerConfig:
    """Create configuration for QUIC MCP server.

    Args:
        name: Server name
        host: Server hostname
        port: Server port
        cert_path: Path to TLS certificate (optional for client if trusted)
        serialization: Serialization format ("msgpack" or "json")
        **kwargs: Additional MCPServerConfig parameters

    Returns:
        MCPServerConfig configured for QUIC transport
    """
    quic_fmt = SerializationFormat.MSGPACK
    if serialization.lower() == "json":
        quic_fmt = SerializationFormat.JSON

    quic_conf = QuicMCPConfig(
        host=host,
        port=port,
        cert_path=cert_path,
        serialization=quic_fmt,
        # Default efficient settings
        enable_0rtt=True,
        enable_webtransport=True
    )

    return MCPServerConfig(
        name=name,
        transport="quic",
        quic_config=quic_conf,
        **kwargs
    )

# Extension for BaseAgent
class MCPEnabledMixin:
    """Mixin to add complete MCP capabilities to agents."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mcp_manager = MCPToolManager(self.tool_manager)

    async def add_mcp_server(self, config: MCPServerConfig) -> List[str]:
        """Add an MCP server with full feature support."""
        return await self.mcp_manager.add_mcp_server(config)

    async def add_local_mcp_server(
        self,
        name: str,
        script_path: Union[str, Path],
        interpreter: str = "python",
        **kwargs
    ) -> List[str]:
        """Add a local stdio MCP server."""
        config = create_local_mcp_server(name, script_path, interpreter, **kwargs)
        return await self.add_mcp_server(config)

    async def add_http_mcp_server(
        self,
        name: str,
        url: str,
        auth_type: Optional[str] = None,
        auth_config: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        **kwargs
    ) -> List[str]:
        """Add an HTTP MCP server."""
        config = create_http_mcp_server(name, url, auth_type, auth_config, headers, **kwargs)
        return await self.add_mcp_server(config)

    async def add_perplexity_mcp_server(
        self,
        api_key: str,
        name: str = "perplexity",
        **kwargs
    ) -> List[str]:
        """Add a Perplexity MCP server capability."""
        config = create_perplexity_mcp_server(api_key, name=name, **kwargs)
        return await self.add_mcp_server(config)

    async def add_fireflies_mcp_server(
        self,
        api_key: str,
        **kwargs
    ) -> List[str]:
        """Add Fireflies.ai MCP server capability.

        Args:
            api_key: Fireflies API key from Settings > Developer Settings
            **kwargs: Additional MCPServerConfig parameters

        Returns:
            List of registered tool names

        Example:
            >>> tools = await agent.add_fireflies_mcp_server(
            ...     api_key="your-fireflies-api-key"
            ... )
        """
        config = create_fireflies_mcp_server(api_key=api_key, **kwargs)
        return await self.add_mcp_server(config)

    async def add_quic_mcp_server(
        self,
        name: str,
        host: str,
        port: int,
        cert_path: Optional[str] = None,
        **kwargs
    ) -> List[str]:
        """Add a QUIC/HTTP3 MCP server connection."""
        config = create_quic_mcp_server(name, host, port, cert_path, **kwargs)
        return await self.add_mcp_server(config)

    async def add_websocket_mcp_server(
        self,
        name: str,
        url: str,
        auth_type: Optional[str] = None,
        auth_config: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        **kwargs
    ) -> List[str]:
        """Add a WebSocket MCP server connection.

        Args:
            name: Server name
            url: WebSocket URL (ws:// or wss://)
            auth_type: Authentication type ("bearer", "api_key", "oauth")
            auth_config: Authentication configuration
            headers: Additional headers for WebSocket upgrade
            **kwargs: Additional MCPServerConfig parameters

        Returns:
            List of registered tool names

        Example:
            >>> await agent.add_websocket_mcp_server(
            ...     "my-ws-server",
            ...     "ws://localhost:8766/mcp/ws",
            ...     auth_type="bearer",
            ...     auth_config={"token": "my-token"}
            ... )
        """
        config = create_websocket_mcp_server(
            name, url, auth_type, auth_config, headers, **kwargs
        )
        return await self.add_mcp_server(config)

    async def remove_mcp_server(self, server_name: str):
        await self.mcp_manager.remove_mcp_server(server_name)

    async def reconfigure_mcp_server(self, config: MCPServerConfig) -> List[str]:
        """Reconfigure an existing MCP server with new configuration.

        Args:
            config: New MCPServerConfig with updated parameters

        Returns:
            List of registered tool names
        """
        return await self.mcp_manager.reconfigure_mcp_server(config)

    async def reconfigure_fireflies_mcp_server(self, api_key: str, **kwargs) -> List[str]:
        """Reconfigure Fireflies MCP server with a new API key.

        This is useful in multi-user scenarios where each user provides their own
        Fireflies API key. The method will disconnect the existing connection and
        reconnect with the new credentials.

        Args:
            api_key: New Fireflies API key
            **kwargs: Additional MCPServerConfig parameters

        Returns:
            List of registered tool names

        Example:
            >>> # Initial setup with user 1's API key
            >>> await agent.add_fireflies_mcp_server(api_key="user1-api-key")

            >>> # Later, reconfigure with user 2's API key
            >>> await agent.reconfigure_fireflies_mcp_server(api_key="user2-api-key")
        """
        config = create_fireflies_mcp_server(api_key=api_key, **kwargs)
        return await self.reconfigure_mcp_server(config)

    async def reconfigure_perplexity_mcp_server(self, api_key: str, name: str = "perplexity", **kwargs) -> List[str]:
        """Reconfigure Perplexity MCP server with a new API key.

        Useful for updating the API key without restarting the agent.

        Args:
            api_key: New Perplexity API key
            name: Server name (default: "perplexity")
            **kwargs: Additional MCPServerConfig parameters

        Returns:
            List of registered tool names
        """
        config = create_perplexity_mcp_server(api_key, name=name, **kwargs)
        return await self.reconfigure_mcp_server(config)

    def list_mcp_servers(self) -> List[str]:
        return self.mcp_manager.list_mcp_servers()

    async def shutdown(self, **kwargs):
        if hasattr(self, 'mcp_manager'):
            await self.mcp_manager.disconnect_all()

        if hasattr(super(), 'shutdown'):
            await super().shutdown(**kwargs)
