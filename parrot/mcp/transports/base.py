from abc import ABC, abstractmethod
import logging
import time
from typing import Dict, List, Optional, Any
from aiohttp import web

from parrot.tools.abstract import AbstractTool
from parrot.mcp.config import MCPServerConfig, AuthMethod
from parrot.mcp.adapter import MCPToolAdapter
from parrot.mcp.oauth import OAuthAuthorizationServer, APIKeyStore, ExternalOAuthValidator


class MCPServerBase(ABC):
    """Base class for MCP servers."""

    def __init__(self, config: MCPServerConfig):
        self.config = config
        self.tools: Dict[str, MCPToolAdapter] = {}
        self.logger = logging.getLogger(f"MCPServer.{config.name}")
        log_level = getattr(logging, config.log_level.upper(), logging.WARNING)
        self.logger.setLevel(log_level)

        # Authentication components
        self.oauth_server: Optional[OAuthAuthorizationServer] = None
        self.api_key_store: Optional[APIKeyStore] = None
        self.external_oauth: Optional[ExternalOAuthValidator] = None

        # Initialize authentication based on method
        self._init_authentication()

    def _init_authentication(self) -> None:
        """Initialize authentication based on config.auth_method."""
        auth_method = self.config.auth_method

        # Backward compatibility: enable_oauth maps to OAUTH2_INTERNAL
        if self.config.enable_oauth and auth_method == AuthMethod.NONE:
            auth_method = AuthMethod.OAUTH2_INTERNAL
            self.config.auth_method = auth_method

        if auth_method == AuthMethod.API_KEY:
            self.api_key_store = self.config.api_key_store or APIKeyStore()
            self.logger.info("Authentication: API Key enabled")

        elif auth_method == AuthMethod.OAUTH2_INTERNAL:
            self.oauth_server = OAuthAuthorizationServer(
                default_scopes=self.config.oauth_scopes,
                allow_dynamic_registration=self.config.oauth_allow_dynamic_registration,
                token_ttl=self.config.oauth_token_ttl,
                code_ttl=self.config.oauth_code_ttl,
            )
            self.logger.info("Authentication: OAuth2 (internal) enabled")

        elif auth_method == AuthMethod.OAUTH2_EXTERNAL:
            if not self.config.oauth2_introspection_endpoint:
                raise ValueError(
                    "oauth2_introspection_endpoint required for OAUTH2_EXTERNAL"
                )
            self.external_oauth = ExternalOAuthValidator(
                introspection_endpoint=self.config.oauth2_introspection_endpoint,
                client_id=self.config.oauth2_client_id or "",
                client_secret=self.config.oauth2_client_secret or "",
                resource_server_url=self.config.oauth2_resource_server_url,
            )
            self.logger.info(
                f"Authentication: OAuth2 (external) enabled - {self.config.oauth2_issuer_url}"
            )

        elif auth_method == AuthMethod.BEARER:
            self.logger.info("Authentication: Bearer (navigator-auth) enabled")

        else:
            self.logger.debug("Authentication: None (open access)")

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


    async def _authenticate_request(self, request: web.Request) -> Optional[web.Response]:
        """
        Authenticate request based on configured auth method.

        Returns None if authenticated, or a web.Response with error if not.
        """
        auth_method = self.config.auth_method

        if auth_method == AuthMethod.NONE:
            return None

        elif auth_method == AuthMethod.API_KEY:
            return await self._authenticate_api_key(request)

        elif auth_method == AuthMethod.OAUTH2_INTERNAL:
            return self._authenticate_oauth_internal(request)

        elif auth_method == AuthMethod.OAUTH2_EXTERNAL:
            return await self._authenticate_oauth_external(request)

        elif auth_method == AuthMethod.BEARER:
            return await self._authenticate_bearer(request)

        return None

    async def _authenticate_api_key(self, request: web.Request) -> Optional[web.Response]:
        """Validate API key from header."""
        api_key = request.headers.get(self.config.api_key_header)
        if not api_key:
            return self._unauthorized_response(
                "API key required",
                f'X-API-Key realm="mcp"'
            )

        record = self.api_key_store.validate_key(api_key)
        if not record:
            return self._unauthorized_response("Invalid or expired API key")

        # Log session start
        self.api_key_store.log_session_start(api_key, record.user_id, time.time())
        self.logger.debug(f"API key authenticated for user: {record.user_id}")

        # Store user info in request for downstream use
        request["mcp_user"] = {"user_id": record.user_id, "scopes": record.scopes}
        return None

    def _authenticate_oauth_internal(self, request: web.Request) -> Optional[web.Response]:
        """Validate OAuth access token from internal OAuth server."""
        if not self.oauth_server:
            return None

        token = self.oauth_server.bearer_token_from_header(
            request.headers.get("Authorization")
        )
        if not self.oauth_server.is_token_valid(token):
            return self._unauthorized_response("Valid Bearer token is required")

        return None

    async def _authenticate_oauth_external(self, request: web.Request) -> Optional[web.Response]:
        """Validate OAuth access token via external introspection."""
        if not self.external_oauth:
            return None

        token = self._extract_bearer_token(request.headers.get("Authorization"))
        if not token:
            return self._unauthorized_response("Bearer token required")

        token_info = await self.external_oauth.validate_token(token)
        if not token_info:
            return self._unauthorized_response("Invalid or expired token")

        # Store token info in request
        request["mcp_user"] = {
            "user_id": token_info.get("sub") or token_info.get("client_id"),
            "scopes": token_info.get("scope", "").split() if token_info.get("scope") else [],
            "token_info": token_info,
        }
        return None

    async def _authenticate_bearer(self, request: web.Request) -> Optional[web.Response]:
        """Validate bearer token via navigator-auth."""
        auth = request.app.get('auth')
        if not auth:
            self.logger.warning("navigator-auth not configured in app['auth']")
            # Fall through if auth not configured (development mode)
            return None

        try:
            userdata = await auth.get_session(request)
            if not userdata:
                return web.json_response(
                    {"error": "unauthorized", "error_description": "Session required"},
                    status=401,
                    headers={"WWW-Authenticate": 'Bearer realm="mcp"'}
                )

            # Store user info in request
            request["mcp_user"] = userdata
            return None

        except Exception as e:
            self.logger.error(f"navigator-auth error: {e}")
            return web.json_response(
                {"error": "unauthorized", "error_description": "Authentication failed"},
                status=401,
                headers={"WWW-Authenticate": 'Bearer realm="mcp"'}
            )

    def _extract_bearer_token(self, auth_header: Optional[str]) -> Optional[str]:
        """Extract bearer token from Authorization header."""
        if not auth_header:
            return None
        if not auth_header.lower().startswith("bearer "):
            return None
        return auth_header.split(" ", 1)[1].strip()

    def _unauthorized_response(
        self,
        message: str,
        www_authenticate: str = 'Bearer realm="mcp"'
    ) -> web.Response:
        """Create a 401 unauthorized response."""
        return web.json_response(
            {"error": "unauthorized", "error_description": message},
            status=401,
            headers={"WWW-Authenticate": www_authenticate}
        )


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
