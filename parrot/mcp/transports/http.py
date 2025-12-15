import json
import logging
from typing import Dict, Any, Optional
from aiohttp import web
import aiohttp

from parrot.mcp.config import MCPServerConfig
from parrot.mcp.transports.base import MCPServerBase
from parrot.mcp.oauth import OAuthRoutesMixin
from parrot.mcp.client import MCPClientConfig, MCPConnectionError, MCPAuthHandler

class HttpMCPServer(OAuthRoutesMixin, MCPServerBase):
    """MCP server using HTTP transport."""

    def __init__(self, config: MCPServerConfig, parent_app: Optional[web.Application] = None):
        super().__init__(config)
        self.app = web.Application()
        self.runner = None
        self.site = None
        self.parent_app = parent_app

        if config.enable_oauth:
            self._init_oauth_support()

    async def start(self):
        """Start the HTTP server."""
        # Setup routes
        self.app.router.add_post("/mcp", self._handle_http_request)
        self.app.router.add_get("/mcp/info", self._handle_info)

        if self.config.enable_oauth:
            self._add_oauth_routes(self.app.router)

        self.logger.info(
            f"Starting HTTP MCP server on {self.config.host}:{self.config.port}"
        )

        if self.parent_app:
            # If running as sub-app, just register the sub-app
            self.parent_app.add_subapp(self.config.base_path, self.app)
            self.logger.info(f"Mounted at {self.config.base_path}")
        else:
            # Run standalone
            self.runner = web.AppRunner(self.app)
            await self.runner.setup()
            self.site = web.TCPSite(
                self.runner,
                self.config.host,
                self.config.port
            )
            await self.site.start()

    async def stop(self):
        """Stop the HTTP server."""
        if self.runner:
            await self.runner.cleanup()

    async def _handle_http_request(self, request: web.Request) -> web.Response:
        """Handle incoming JSON-RPC over HTTP."""
        try:
            # Check authentication (async to support all auth methods)
            auth_response = await self._authenticate_request(request)
            if auth_response:
                return auth_response

            data = await request.json()
            response = await self._handle_request(data)

            if response:
                # Convert tools to Anthropic format if needed
                if "result" in response and "tools" in response["result"]:
                    # Check User-Agent or header for Anthropic
                    if "Anthropic" in request.headers.get("User-Agent", ""):
                        response["result"] = self._convert_tools_to_anthropic(response["result"])

                return web.json_response(response)
            else:
                return web.Response(status=204)  # No content

        except json.JSONDecodeError:
            return web.json_response(
                {"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}, "id": None},
                status=400
            )
        except Exception as e:
            self.logger.error(f"HTTP request error: {e}")
            return web.json_response(
                {"jsonrpc": "2.0", "error": {"code": -32603, "message": str(e)}, "id": None},
                status=500
            )

    def _convert_tools_to_anthropic(self, mcp_result: Dict[str, Any]) -> Dict[str, Any]:
        """Convert standard MCP tool list to Anthropic-compatible format."""
        # Anthropic expects specific structure, this is a placeholder for logic
        # For now, just return as is or adapt lightly
        return mcp_result

    async def _handle_info(self, request: web.Request) -> web.Response:
        """Return server info."""
        return web.json_response({
            "name": self.config.name,
            "version": self.config.version,
            "transport": "http",
            "tools_count": len(self.tools)
        })

    async def _handle_request(self, request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Handle JSON-RPC request."""
        # This reuses the logic from stdio but returns dict instead of printing
        method = request.get("method")
        params = request.get("params", {})
        request_id = request.get("id")

        try:
            if method == "initialize":
                result = await self.handle_initialize(params)
            elif method == "tools/list":
                result = await self.handle_tools_list(params)
            elif method == "tools/call":
                result = await self.handle_tools_call(params)
            elif method == "notifications/initialized":
                return None
            else:
                raise RuntimeError(f"Unknown method: {method}")

            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": result
            }

        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "code": -32603,
                    "message": str(e)
                }
            }


class HttpMCPSession:
    """MCP session for HTTP/SSE transport using aiohttp."""

    def __init__(self, config: MCPClientConfig, logger):
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

            print('THIS > ', self._base_headers)

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
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json"
                }
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
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json"
                }
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
