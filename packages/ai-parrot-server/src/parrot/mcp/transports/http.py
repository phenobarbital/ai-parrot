import asyncio
import json
import logging
import ssl
import webbrowser
from typing import Dict, Any, Optional, Tuple
from aiohttp import web
import aiohttp

from parrot.mcp.config import MCPServerConfig
from parrot.mcp.transports.base import MCPServerBase
from parrot.mcp.oauth_server import OAuthRoutesMixin
from parrot.mcp.client import (
    MCPClientConfig,
    MCPConnectionError,
    MCPAuthHandler,
    MCPRateLimitError,
    parse_retry_after,
    raise_for_jsonrpc_error,
)

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
        # Determine strict router target
        # If we have a parent app and base_path is root (empty or /), we attach directly
        target_router = self.app.router
        use_direct_attach = False
        
        if self.parent_app:
            if not self.config.base_path or self.config.base_path == "/":
                target_router = self.parent_app.router
                use_direct_attach = True

        # Setup routes
        base_route = self.config.base_path
        if not base_route or base_route == "/":
            base_route = "/"
            
        target_router.add_post(base_route, self._handle_http_request)
        target_router.add_get(f"{base_route.rstrip('/')}/info", self._handle_info)

        if self.config.enable_oauth:
            self._add_oauth_routes(target_router)

        self.logger.info(
            "Starting HTTP MCP server on %s:%s", self.config.host, self.config.port
        )

        if self.parent_app:
            if not use_direct_attach:
                # If running as sub-app with prefix, register the sub-app
                self.parent_app.add_subapp(self.config.base_path, self.app)
                self.logger.info("Mounted at %s", self.config.base_path)
            else:
                self.logger.info("Mounted at / (merged)")
        else:
            # Run standalone
            self.runner = web.AppRunner(self.app)
            await self.runner.setup()

            ssl_context = None
            if self.config.ssl_cert_path and self.config.ssl_key_path:
                ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
                ssl_context.load_cert_chain(
                    certfile=self.config.ssl_cert_path,
                    keyfile=self.config.ssl_key_path
                )
                self.logger.info("Enabled SSL with cert: %s", self.config.ssl_cert_path)
            
            self.site = web.TCPSite(
                self.runner,
                self.config.host,
                self.config.port,
                ssl_context=ssl_context
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
            self.logger.error("HTTP request error: %s", e)
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
            elif method == "resources/list":
                result = await self.handle_resources_list(params)
            elif method == "resources/read":
                result = await self.handle_resources_read(params)
            elif method == "prompts/list":
                result = await self.handle_prompts_list(params)
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
        # OAuth2 provider (set when config.oauth2 is configured)
        self._oauth2_provider = None

    async def _setup_oauth2(self) -> None:
        """Set up MCP SDK OAuth2 provider when config.oauth2 is configured.

        For authorization_code grant: creates OAuthClientProvider with PKCE,
        registers a pending callback, and opens the browser for user auth.
        For client_credentials grant: creates ClientCredentialsOAuthProvider.

        The acquired access token is stored and injected into subsequent
        aiohttp requests as a Bearer Authorization header.
        """
        from parrot.mcp.oauth2_config import MCPOAuth2GrantType
        from parrot.mcp.oauth2_storage import VaultMCPTokenStorage
        from parrot.mcp.oauth2_state import register_pending_callback, deregister_pending_callback
        from mcp.shared.auth import OAuthClientMetadata

        oauth2 = self.config.oauth2
        # user_id is on MCPClientConfig (not MCPOAuth2Config) for per-user token scoping.
        user_id = getattr(self.config, "user_id", None) or "default"
        storage = VaultMCPTokenStorage(
            user_id=user_id,
            server_name=self.config.name,
        )

        if oauth2.grant_type == MCPOAuth2GrantType.CLIENT_CREDENTIALS:
            # Machine-to-machine flow — no browser needed
            from mcp.client.auth.extensions.client_credentials import (
                ClientCredentialsOAuthProvider,
            )
            self._oauth2_provider = ClientCredentialsOAuthProvider(
                server_url=self.config.url,
                storage=storage,
                client_id=oauth2.client_id or "",
                client_secret=oauth2.client_secret or "",
                scopes=" ".join(oauth2.scopes) if oauth2.scopes else None,
            )
            self.logger.debug(
                "OAuth2 client credentials provider configured for %s", self.config.name
            )
        else:
            # Authorization code + PKCE flow
            import secrets
            from mcp.client.auth.oauth2 import OAuthClientProvider

            oauth_state = secrets.token_urlsafe(24)
            callback_event, callback_result = register_pending_callback(oauth_state)

            # Resolve base URL: explicit field → env var → local default.
            import os
            _base = (
                oauth2.redirect_base_url
                or os.environ.get("NAVIGATOR_BASE_URL", "")
                or "http://127.0.0.1:8000"
            )
            redirect_uri = f"{_base.rstrip('/')}{oauth2.redirect_path}"

            async def redirect_handler(url: str) -> None:
                """Open the authorization URL in the user's browser."""
                self.logger.info("OAuth2: opening browser for authorization: %s", url)
                webbrowser.open(url)

            async def callback_handler() -> "Tuple[str, Optional[str]]":
                """Wait for the Navigator callback to receive the auth code."""
                self.logger.debug(
                    "OAuth2: waiting for callback (state=%s)", oauth_state
                )
                try:
                    await asyncio.wait_for(callback_event.wait(), timeout=300.0)
                except asyncio.TimeoutError:
                    # Clean up abandoned state to prevent memory leak in long-running servers.
                    deregister_pending_callback(oauth_state)
                    self.logger.warning(
                        "OAuth2 callback timed out after 300s (state=%s). "
                        "The user may not have completed the browser flow.",
                        oauth_state,
                    )
                    raise
                code = callback_result.get("code", "")
                state = callback_result.get("state")
                return code, state

            client_metadata = OAuthClientMetadata(
                redirect_uris=[redirect_uri],
                grant_types=["authorization_code"],
                response_types=["code"],
                scope=" ".join(oauth2.scopes) if oauth2.scopes else None,
            )

            self._oauth2_provider = OAuthClientProvider(
                server_url=self.config.url,
                client_metadata=client_metadata,
                storage=storage,
                redirect_handler=redirect_handler,
                callback_handler=callback_handler,
                timeout=300.0,
            )
            self.logger.debug(
                "OAuth2 authorization code provider configured for %s", self.config.name
            )

    async def _get_oauth2_token(self) -> Optional[str]:
        """Return the current OAuth2 access token, refreshing if needed.

        Returns:
            Bearer token string, or None if unavailable.
        """
        if self._oauth2_provider is None:
            return None
        try:
            ctx = self._oauth2_provider.context
            if ctx.is_token_valid():
                if ctx.current_tokens:
                    return ctx.current_tokens.access_token
        except Exception as exc:  # noqa: BLE001
            self.logger.debug("OAuth2 token check failed: %s", exc)
        return None

    async def connect(self):
        """Connect to MCP server via HTTP."""
        try:
            # Set up OAuth2 when configured (FEAT-262)
            if self.config.oauth2:
                await self._setup_oauth2()

            # Setup legacy authentication (skipped when OAuth2 is active)
            elif self.config.auth_type:
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
            self.logger.info("HTTP connection established to %s", self.config.name)

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
            self.logger.debug("HTTP sending: %s", json.dumps(request))

            # Build per-request headers, injecting OAuth2 token when available
            req_headers: Dict[str, str] = {
                "Content-Type": "application/json",
                "Accept": "application/json",
            }
            if self._oauth2_provider is not None:
                token = await self._get_oauth2_token()
                if token:
                    req_headers["Authorization"] = f"Bearer {token}"
            elif self.config.token_supplier:
                token = self.config.token_supplier()
                if token:
                    req_headers["Authorization"] = f"Bearer {token}"

            async with self._session.post(
                self.config.url,
                json=request,
                headers=req_headers,
            ) as response:

                if response.status == 429:
                    # Honour the standard HTTP Retry-After header (seconds or
                    # an HTTP-date is uncommon here; we parse the numeric form).
                    retry_after = parse_retry_after(response.headers.get("Retry-After"))
                    raise MCPRateLimitError(
                        "Rate limit exceeded (HTTP 429)"
                        + (f"; retry after {retry_after:.1f}s" if retry_after is not None else ""),
                        retry_after=retry_after,
                    )

                if response.status != 200:
                    raise MCPConnectionError(f"HTTP error: {response.status}")

                response_data = await response.json()
                self.logger.debug("HTTP received: %s", json.dumps(response_data))

                if "error" in response_data:
                    # Raises MCPRateLimitError for -32429 (with retry_after) or a
                    # generic MCPConnectionError otherwise.
                    raise_for_jsonrpc_error(response_data["error"])

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
            self.logger.debug("HTTP notification: %s", json.dumps(notification))

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
            self.logger.debug("Notification error (ignored): %s", e)

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
