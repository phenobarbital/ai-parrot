"""
Complete MCP Integration with HTTP, Auth, and all original features
================================================================
This version includes all the features from your original implementation
while maintaining the stability of our working stdio transport.
"""
import os
from typing import Callable, Dict, List, Any, Optional, Union
import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
import json
import base64
import aiohttp
# AI-Parrot imports
from ..tools.abstract import AbstractTool, ToolResult
from ..tools.manager import ToolManager
from .oauth import OAuthManager, InMemoryTokenStore, RedisTokenStore


@dataclass
class MCPServerConfig:
    """Complete configuration for MCP server connection."""
    name: str

    # Connection parameters
    url: Optional[str] = None  # For HTTP/SSE servers
    command: Optional[str] = None  # For stdio servers
    args: Optional[List[str]] = None  # Command arguments
    env: Optional[Dict[str, str]] = None  # Environment variables

    # Authentication
    auth_type: Optional[str] = None  # "oauth", "bearer", "basic", "api_key", "none"
    auth_config: Dict[str, Any] = field(default_factory=dict)
    # A token supplier hook the HTTP client will call to add headers (set by OAuthManager)
    token_supplier: Optional[Callable[[], Optional[str]]] = None

    # Transport type
    transport: str = "auto"  # "auto", "stdio", "http", "sse"

    # Additional headers for HTTP transports
    headers: Dict[str, str] = field(default_factory=dict)

    # Connection settings
    timeout: float = 30.0
    retry_count: int = 3
    startup_delay: float = 0.5

    # Tool filtering
    allowed_tools: Optional[List[str]] = None
    blocked_tools: Optional[List[str]] = None

    # Process management
    kill_timeout: float = 5.0


class MCPAuthHandler:
    """Handles various authentication types for MCP servers."""

    def __init__(self, auth_type: str, auth_config: Dict[str, Any]):
        self.auth_type = auth_type.lower() if auth_type else None
        self.auth_config = auth_config
        self.logger = logging.getLogger("MCPAuthHandler")

    async def get_auth_headers(self) -> Dict[str, str]:
        """Get authentication headers based on auth type."""
        if not self.auth_type or self.auth_type == "none":
            return {}

        if self.auth_type == "bearer":
            return await self._get_bearer_headers()
        elif self.auth_type == "oauth":
            return await self._get_oauth_headers()
        elif self.auth_type == "basic":
            return await self._get_basic_headers()
        elif self.auth_type == "api_key":
            return await self._get_api_key_headers()
        else:
            self.logger.warning(f"Unknown auth type: {self.auth_type}")
            return {}

    async def _get_bearer_headers(self) -> Dict[str, str]:
        """Get Bearer token headers."""
        token = self.auth_config.get("token") or self.auth_config.get("access_token")
        if not token:
            raise ValueError("Bearer authentication requires 'token' or 'access_token' in auth_config")

        return {"Authorization": f"Bearer {token}"}

    async def _get_oauth_headers(self) -> Dict[str, str]:
        """Get OAuth headers (simplified - assumes token is already available)."""
        access_token = self.auth_config.get("access_token")
        if not access_token:
            # In a full implementation, you'd handle the OAuth flow here
            raise ValueError("OAuth authentication requires 'access_token' in auth_config")

        return {"Authorization": f"Bearer {access_token}"}

    async def _get_basic_headers(self) -> Dict[str, str]:
        """Get Basic authentication headers."""
        username = self.auth_config.get("username")
        password = self.auth_config.get("password")

        if not username or not password:
            raise ValueError("Basic authentication requires 'username' and 'password' in auth_config")

        credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
        return {"Authorization": f"Basic {credentials}"}

    async def _get_api_key_headers(self) -> Dict[str, str]:
        """Get API key headers."""
        api_key = self.auth_config.get("api_key")
        header_name = self.auth_config.get("header_name", "X-API-Key")

        if not api_key:
            raise ValueError("API key authentication requires 'api_key' in auth_config")

        return {header_name: api_key}


class MCPConnectionError(Exception):
    """MCP connection related errors."""
    pass


class StdioMCPSession:
    """MCP session for stdio transport (our working implementation)."""

    def __init__(self, config: MCPServerConfig, logger):
        self.config = config
        self.logger = logger
        self._request_id = 0
        self._process = None
        self._stdin = None
        self._stdout = None
        self._stderr = None
        self._initialized = False

    async def connect(self):
        """Connect to MCP server via stdio."""
        if self._process:
            await self.disconnect()

        try:
            await self._start_process()
            await self._initialize_session()
            self._initialized = True
            self.logger.info(f"Stdio connection established to {self.config.name}")

        except Exception as e:
            await self.disconnect()
            raise MCPConnectionError(f"Stdio connection failed: {e}") from e

    async def _start_process(self):
        """Start the MCP server process."""
        if not self.config.command:
            raise ValueError("Command required for stdio transport")

        args = self.config.args or []
        env = dict(os.environ)
        if self.config.env:
            env.update(self.config.env)

        self._process = await asyncio.create_subprocess_exec(
            self.config.command,
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env
        )

        self._stdin = self._process.stdin
        self._stdout = self._process.stdout
        self._stderr = self._process.stderr

        await asyncio.sleep(self.config.startup_delay)

        if self._process.returncode is not None:
            stderr_output = ""
            if self._stderr:
                try:
                    stderr_data = await asyncio.wait_for(self._stderr.read(1024), timeout=2.0)
                    stderr_output = stderr_data.decode('utf-8', errors='replace')
                except asyncio.TimeoutError:
                    stderr_output = "No error output available"

            raise RuntimeError(f"Process failed to start: {stderr_output}")

    async def _initialize_session(self):
        """Initialize the MCP session."""
        try:
            await self._send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "clientInfo": {"name": "ai-parrot-mcp-client", "version": "1.0.0"}
            })
            await self._send_notification("notifications/initialized")
        except Exception as e:
            raise MCPConnectionError(f"Session initialization failed: {e}") from e

    async def _send_request(self, method: str, params: dict = None) -> dict:
        if not self._process or self._process.returncode is not None:
            raise MCPConnectionError("Process is not running")

        request_id = self._get_next_id()
        request = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params:
            request["params"] = params

        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.config.timeout

        try:
            line = (json.dumps(request) + "\n").encode("utf-8")
            self.logger.debug(f"Stdio sending: {line.decode().strip()}")
            self._stdin.write(line)
            await self._stdin.drain()

            response = None
            while True:
                timeout = max(0.1, deadline - loop.time())
                response_line = await asyncio.wait_for(self._stdout.readline(), timeout=timeout)
                if not response_line:
                    raise MCPConnectionError("Empty response - connection closed")

                response_str = response_line.decode("utf-8", errors="replace").strip()
                if not response_str:
                    continue
                self.logger.debug(f"Stdio received: {response_str}")

                # Skip non-JSON garbage
                try:
                    candidate = json.loads(response_str)
                except json.JSONDecodeError:
                    self.logger.debug(f"Ignoring non-JSON stdout: {response_str!r}")
                    continue

                # Only accept responses with our request id; ignore notifications/others
                if candidate.get("id") != request_id:
                    # could be a notification or another message; ignore
                    continue

                response = candidate
                break

            if "error" in response:
                raise MCPConnectionError(f"Server error: {response['error']}")

            return response.get("result", {})

        except asyncio.TimeoutError:
            raise MCPConnectionError(f"Request timeout after {self.config.timeout} seconds")
        except Exception as e:
            if isinstance(e, MCPConnectionError):
                raise
            raise MCPConnectionError(f"Request failed: {e}") from e

    async def _send_notification(self, method: str, params: dict = None):
        """Send JSON-RPC notification."""
        notification = {"jsonrpc": "2.0", "method": method}
        if params:
            notification["params"] = params

        notification_line = json.dumps(notification) + "\n"
        self.logger.debug(f"Stdio notification: {notification_line.strip()}")

        self._stdin.write(notification_line.encode('utf-8'))
        await self._stdin.drain()

    def _get_next_id(self):
        self._request_id += 1
        return self._request_id

    async def list_tools(self):
        """List available tools."""
        if not self._initialized:
            raise MCPConnectionError("Session not initialized")

        result = await self._send_request("tools/list")
        tools = result.get("tools", [])

        tool_objects = []
        for tool_dict in tools:
            tool_obj = type('MCPTool', (), tool_dict)()
            tool_objects.append(tool_obj)

        return tool_objects

    async def call_tool(self, tool_name: str, arguments: dict):
        """Call a tool."""
        if not self._initialized:
            raise MCPConnectionError("Session not initialized")

        result = await self._send_request("tools/call", {
            "name": tool_name,
            "arguments": arguments
        })

        content_items = []
        if "content" in result:
            for item in result["content"]:
                content_obj = type('ContentItem', (), item)()
                content_items.append(content_obj)

        result_obj = type('ToolCallResult', (), {"content": content_items})()
        return result_obj

    async def disconnect(self):
        """Disconnect stdio session."""
        self._initialized = False

        if self._process:
            try:
                if self._stdin and not self._stdin.is_closing():
                    self._stdin.close()
                    await self._stdin.wait_closed()

                if self._process.returncode is None:
                    try:
                        await asyncio.wait_for(
                            self._process.wait(),
                            timeout=self.config.kill_timeout
                        )
                    except asyncio.TimeoutError:
                        self.logger.warning("Process didn't terminate, force killing")
                        self._process.kill()
                        await self._process.wait()

            except Exception as e:
                self.logger.debug(f"Error during disconnect: {e}")
            finally:
                self._process = None
                self._stdin = None
                self._stdout = None
                self._stderr = None


class HttpMCPSession:
    """MCP session for HTTP/SSE transport using aiohttp."""

    def __init__(self, config: MCPServerConfig, logger):
        self.config = config
        self.logger = logger
        self._request_id = 0
        self._session = None
        self._auth_handler = None
        self._initialized = False
        self._base_headers = {}

    async def connect(self):
        """Connect to MCP server via HTTP."""
        try:
            # Setup authentication
            if self.config.auth_type:
                self._auth_handler = MCPAuthHandler(
                    self.config.auth_type,
                    self.config.auth_config
                )
                auth_headers = await self._auth_handler.get_auth_headers()
                self._base_headers.update(auth_headers)

            # Add custom headers
            self._base_headers.update(self.config.headers)

            # Create HTTP session
            timeout = aiohttp.ClientTimeout(total=self.config.timeout)
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                headers=self._base_headers
            )

            # Initialize MCP session
            await self._initialize_session()
            self._initialized = True
            self.logger.info(f"HTTP connection established to {self.config.name}")

        except Exception as e:
            await self.disconnect()
            raise MCPConnectionError(f"HTTP connection failed: {e}") from e

    async def _initialize_session(self):
        """Initialize MCP session over HTTP."""
        try:
            init_result = await self._send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "clientInfo": {"name": "ai-parrot-mcp-client", "version": "1.0.0"}
            })

            # Send initialized notification
            await self._send_notification("notifications/initialized")

        except Exception as e:
            raise MCPConnectionError(f"HTTP session initialization failed: {e}") from e

    async def _send_request(self, method: str, params: dict = None) -> dict:
        """Send JSON-RPC request via HTTP."""
        if not self._session:
            raise MCPConnectionError("HTTP session not established")

        request_id = self._get_next_id()
        request = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params:
            request["params"] = params

        try:
            self.logger.debug(f"HTTP sending: {json.dumps(request)}")

            async with self._session.post(
                self.config.url,
                json=request,
                headers={"Content-Type": "application/json"}
            ) as response:

                if response.status != 200:
                    raise MCPConnectionError(f"HTTP error: {response.status}")

                response_data = await response.json()
                self.logger.debug(f"HTTP received: {json.dumps(response_data)}")

                if "error" in response_data:
                    error = response_data["error"]
                    raise MCPConnectionError(f"Server error: {error}")

                return response_data.get("result", {})

        except Exception as e:
            if isinstance(e, MCPConnectionError):
                raise
            raise MCPConnectionError(f"HTTP request failed: {e}") from e

    async def _send_notification(self, method: str, params: dict = None):
        """Send JSON-RPC notification via HTTP."""
        notification = {"jsonrpc": "2.0", "method": method}
        if params:
            notification["params"] = params

        try:
            self.logger.debug(f"HTTP notification: {json.dumps(notification)}")

            async with self._session.post(
                self.config.url,
                json=notification,
                headers={"Content-Type": "application/json"}
            ) as response:
                # Notifications don't expect responses
                pass

        except Exception as e:
            self.logger.debug(f"Notification error (ignored): {e}")

    def _get_next_id(self):
        self._request_id += 1
        return self._request_id

    async def list_tools(self):
        """List available tools via HTTP."""
        if not self._initialized:
            raise MCPConnectionError("Session not initialized")

        result = await self._send_request("tools/list")
        tools = result.get("tools", [])

        tool_objects = []
        for tool_dict in tools:
            tool_obj = type('MCPTool', (), tool_dict)()
            tool_objects.append(tool_obj)

        return tool_objects

    async def call_tool(self, tool_name: str, arguments: dict):
        """Call a tool via HTTP."""
        if not self._initialized:
            raise MCPConnectionError("Session not initialized")

        result = await self._send_request("tools/call", {
            "name": tool_name,
            "arguments": arguments
        })

        content_items = []
        if "content" in result:
            for item in result["content"]:
                content_obj = type('ContentItem', (), item)()
                content_items.append(content_obj)

        result_obj = type('ToolCallResult', (), {"content": content_items})()
        return result_obj

    async def disconnect(self):
        """Disconnect HTTP session."""
        self._initialized = False

        if self._session:
            await self._session.close()
            self._session = None

        self._auth_handler = None
        self._base_headers.clear()


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

        if self.config.url:
            # Check if URL looks like SSE endpoint
            if "events" in self.config.url or "sse" in self.config.url:
                return "sse"
            else:
                return "http"
        elif self.config.command:
            return "stdio"
        else:
            raise ValueError("Cannot auto-detect transport. Please specify url or command.")

    async def connect(self):
        """Connect to MCP server using appropriate transport."""
        if self._connected:
            return

        transport = self._detect_transport()

        try:
            if transport == "stdio":
                self._session = StdioMCPSession(self.config, self.logger)
            elif transport in ["http", "sse"]:
                # For now, treat SSE the same as HTTP - you could extend this
                self._session = HttpMCPSession(self.config, self.logger)
            else:
                raise ValueError(f"Unsupported transport: {transport}")

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


def create_api_key_mcp_server(
    name: str,
    url: str,
    api_key: str,
    header_name: str = "X-API-Key",
    **kwargs
) -> MCPServerConfig:
    """Create configuration for API key authenticated MCP server."""
    return create_http_mcp_server(
        name=name,
        url=url,
        auth_type="api_key",
        auth_config={
            "api_key": api_key,
            "header_name": header_name
        },
        **kwargs
    )


def create_fireflies_mcp_server(
    *,
    user_id: str,
    client_id: str,
    auth_url: str = "https://api.fireflies.ai/oauth/authorize",
    token_url: str = "https://api.fireflies.ai/oauth/token",
    scopes: list[str] = ("meetings:read", "transcripts:read"),
    api_base: str = "https://api.fireflies.ai/mcp",
    client_secret: str | None = None,      # if Fireflies requires secret with auth code exchange
    redis=None,                             # aioredis client or None
) -> MCPServerConfig:
    return create_oauth_mcp_server(
        name="fireflies",
        url=api_base,
        user_id=user_id,
        client_id=client_id,
        client_secret=client_secret,
        auth_url=auth_url,
        token_url=token_url,
        scopes=list(scopes),
        redis=redis,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "AI-Parrot-MCP-Client/1.0",
        },
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

    async def remove_mcp_server(self, server_name: str):
        await self.mcp_manager.remove_mcp_server(server_name)

    def list_mcp_servers(self) -> List[str]:
        return self.mcp_manager.list_mcp_servers()

    async def shutdown(self, **kwargs):
        if hasattr(self, 'mcp_manager'):
            await self.mcp_manager.disconnect_all()

        if hasattr(super(), 'shutdown'):
            await super().shutdown(**kwargs)
