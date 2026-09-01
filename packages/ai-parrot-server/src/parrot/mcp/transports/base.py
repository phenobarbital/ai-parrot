import time
from collections.abc import Awaitable, Callable
from typing import Any

from aiohttp import web
from parrot.mcp.config import AuthMethod, MCPServerConfig
from parrot.mcp.oauth_server import (
    WELL_KNOWN_PRM_PATH,
    APIKeyStore,
    ExternalOAuthValidator,
    OAuthAuthorizationServer,
)
from parrot.mcp.resources import MCPResource
from parrot.mcp.server_base import LocalServerConfig
from parrot.mcp.server_base import MCPServerBase as _CoreMCPServerBase
from parrot.tools.abstract import AbstractTool


class RemoteMCPServerBase(_CoreMCPServerBase):
    """Base class for remote (network) MCP servers.

    Inherits tool registration and JSON-RPC handlers from core's
    ``MCPServerBase`` (FEAT-403) and adds the remote-only concerns:
    authentication, resources, and aiohttp-backed request handling.
    """

    def __init__(self, config: MCPServerConfig):
        # Core base only knows about LocalServerConfig — convert, then
        # override self.config with the full server-side config below.
        super().__init__(
            LocalServerConfig(
                name=config.name,
                version=config.version,
                description=config.description,
                log_level=config.log_level,
            )
        )
        self.config = config
        self.resources: dict[str, MCPResource] = {}
        self.resource_handlers: dict[str, Callable[[str], Awaitable[str | bytes]]] = {}

        # Authentication components
        self.oauth_server: OAuthAuthorizationServer | None = None
        self.api_key_store: APIKeyStore | None = None
        self.external_oauth: ExternalOAuthValidator | None = None

        # Initialize authentication based on method
        self._init_authentication()

    # ... (rest of simple init methods) ...

    def register_resource(self, resource: MCPResource, read_handler: Callable[[str], Awaitable[str | bytes]]):
        """
        Register a resource with the MCP server.

        Args:
            resource: The MCPResource definition
            read_handler: Async function that takes the URI and returns content
        """
        self.resources[resource.uri] = resource
        self.resource_handlers[resource.uri] = read_handler
        self.logger.info("Registered resource: %s (%s)", resource.name, resource.uri)

    def register_tool(self, tool: AbstractTool):
        """Register an AI-Parrot tool with the MCP server (with filtering)."""
        tool_name = tool.name

        # Apply filtering (remote-only — core's register_tool has none)
        if self.config.allowed_tools and tool_name not in self.config.allowed_tools:
            self.logger.info(f"Skipping tool {tool_name} (not in allowed_tools)")
            return

        if self.config.blocked_tools and tool_name in self.config.blocked_tools:
            self.logger.info(f"Skipping tool {tool_name} (in blocked_tools)")
            return

        super().register_tool(tool)

    # ... (tools registration) ...

    async def handle_resources_list(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle resources/list request."""
        # Pagination can be implemented later with cursor
        return {"resources": [res.to_dict() for res in self.resources.values()]}

    async def handle_resources_read(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle resources/read request."""
        uri = params.get("uri")
        if not uri:
            raise ValueError("Missing 'uri' parameter")

        if uri not in self.resources:
            raise ValueError(f"Resource not found: {uri}")

        handler = self.resource_handlers.get(uri)
        if not handler:
            raise RuntimeError(f"No handler registered for resource: {uri}")

        try:
            content = await handler(uri)

            # Auto-detect content type if simple string
            is_text = isinstance(content, str)

            return {
                "contents": [
                    {
                        "uri": uri,
                        "mimeType": self.resources[uri].mime_type
                        or ("text/plain" if is_text else "application/octet-stream"),
                        "text" if is_text else "blob": content,
                    }
                ]
            }
        except Exception as e:
            self.logger.error(f"Error reading resource {uri}: {e}")
            raise RuntimeError(f"Failed to read resource: {e}") from e

    async def handle_prompts_list(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle prompts/list request."""
        # By default, we don't have a prompt registry yet.
        return {"prompts": []}

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
                # MCPServerConfig spells this `oauth_scope`; the plural
                # raised AttributeError, making OAUTH2_INTERNAL unusable.
                default_scopes=self.config.oauth_scope,
                allow_dynamic_registration=self.config.oauth_allow_dynamic_registration,
                token_ttl=self.config.oauth_token_ttl,
                code_ttl=self.config.oauth_code_ttl,
            )
            # Register static clients
            if self.config.oauth_static_clients:
                for client_config in self.config.oauth_static_clients:
                    try:
                        client = self.oauth_server.registry.register(client_config)
                        self.logger.info(f"Registered static OAuth client: {client.client_id} ({client.client_name})")
                    except Exception as e:  # noqa: BLE001
                        self.logger.error("Failed to register static client: %s", e)

            self.logger.info("Authentication: OAuth2 (internal) enabled")

        elif auth_method == AuthMethod.OAUTH2_EXTERNAL:
            if not self.config.oauth2_introspection_endpoint:
                raise ValueError("oauth2_introspection_endpoint required for OAUTH2_EXTERNAL")
            self.external_oauth = ExternalOAuthValidator(
                introspection_endpoint=self.config.oauth2_introspection_endpoint,
                client_id=self.config.oauth2_client_id or "",
                client_secret=self.config.oauth2_client_secret or "",
                resource_server_url=self.config.oauth2_resource_server_url,
            )
            self.logger.info(f"Authentication: OAuth2 (external) enabled - {self.config.oauth2_issuer_url}")

        elif auth_method == AuthMethod.BEARER:
            self.logger.info("Authentication: Bearer (navigator-auth) enabled")

        else:
            self.logger.debug("Authentication: None (open access)")

    async def _authenticate_request(self, request: web.Request) -> web.Response | None:
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

    async def _authenticate_api_key(self, request: web.Request) -> web.Response | None:
        """Validate API key from header."""
        api_key = request.headers.get(self.config.api_key_header)
        if not api_key:
            return self._unauthorized_response(
                "API key required",
                'X-API-Key realm="mcp"',
                request=request,
            )

        record = self.api_key_store.validate_key(api_key)
        if not record:
            return self._unauthorized_response("Invalid or expired API key", request=request)

        # Log session start
        self.api_key_store.log_session_start(api_key, record.user_id, time.time())
        self.logger.debug("API key authenticated for user: %s", record.user_id)

        # Store user info in request for downstream use
        request["mcp_user"] = {"user_id": record.user_id, "scopes": record.scopes}
        return None

    def _authenticate_oauth_internal(self, request: web.Request) -> web.Response | None:
        """Validate OAuth access token from internal OAuth server."""
        if not self.oauth_server:
            return None

        token = self.oauth_server.bearer_token_from_header(request.headers.get("Authorization"))
        if not self.oauth_server.is_token_valid(token):
            return self._unauthorized_response("Valid Bearer token is required", request=request)

        return None

    async def _authenticate_oauth_external(self, request: web.Request) -> web.Response | None:
        """Validate OAuth access token via external introspection."""
        if not self.external_oauth:
            return None

        token = self._extract_bearer_token(request.headers.get("Authorization"))
        if not token:
            return self._unauthorized_response("Bearer token required", request=request)

        token_info = await self.external_oauth.validate_token(token)
        if not token_info:
            return self._unauthorized_response("Invalid or expired token", request=request)

        # Store token info in request
        request["mcp_user"] = {
            "user_id": token_info.get("sub") or token_info.get("client_id"),
            "scopes": token_info.get("scope", "").split() if token_info.get("scope") else [],
            "token_info": token_info,
        }
        return None

    async def _authenticate_bearer(self, request: web.Request) -> web.Response | None:
        """Validate bearer token via navigator-auth."""
        auth = request.app.get("auth")
        if not auth:
            self.logger.warning("navigator-auth not configured in app['auth']")
            # Fall through if auth not configured (development mode)
            return None

        try:
            userdata = await auth.get_session(request)
            if not userdata:
                return self._unauthorized_response("Session required", request=request)

            # Store user info in request
            request["mcp_user"] = userdata
            return None

        except Exception as e:  # noqa: BLE001
            self.logger.error("navigator-auth error: %s", e)
            return self._unauthorized_response("Authentication failed", request=request)

    def _extract_bearer_token(self, auth_header: str | None) -> str | None:
        """Extract bearer token from Authorization header."""
        if not auth_header:
            return None
        if not auth_header.lower().startswith("bearer "):
            return None
        return auth_header.split(" ", 1)[1].strip()

    def _resource_metadata_url(self, request: web.Request) -> str:
        """Build the absolute RFC 9728 protected-resource metadata URL.

        FEAT-477 TASK-2608 (G4): lets a 401'd client re-discover the
        authorization server via the `resource_metadata` challenge
        parameter.

        Args:
            request: The inbound request (used for scheme/host).

        Returns:
            The mixin's own `_oauth_paths()["protected_resource"]`
            (base_path-prefixed) when `OAuthRoutesMixin` is present on
            this instance — true for every HTTP-like transport — else the
            bare well-known path (Unix/QUIC transports register no OAuth
            routes to prefix).
        """
        base_url = f"{request.scheme}://{request.host}"
        oauth_paths = getattr(self, "_oauth_paths", None)
        path = oauth_paths()["protected_resource"] if oauth_paths else WELL_KNOWN_PRM_PATH
        return f"{base_url}{path}"

    def _unauthorized_response(
        self,
        message: str,
        www_authenticate: str = 'Bearer realm="mcp"',
        *,
        request: "web.Request | None" = None,
    ) -> web.Response:
        """Create a 401 unauthorized response.

        Args:
            message: Human-readable, non-sensitive error description.
            www_authenticate: Base challenge value.
            request: The inbound request. When given, `resource_metadata=
                "<PRM URL>"` (RFC 9728) is appended to the challenge so the
                client can re-discover the AS (FEAT-477 TASK-2608, G4).
                `None` (default) omits it — callers with no request
                context at hand (none exist today; kept optional for
                forward compatibility) fall back to the bare challenge.

        Returns:
            A 401 `web.Response`.
        """
        challenge = www_authenticate
        if request is not None:
            challenge = f"{www_authenticate}, resource_metadata=" f'"{self._resource_metadata_url(request)}"'
        return web.json_response(
            {"error": "unauthorized", "error_description": message}, status=401, headers={"WWW-Authenticate": challenge}
        )


# Backward-compat alias (FEAT-403): existing code importing
# ``from parrot.mcp.transports.base import MCPServerBase`` keeps working —
# it now resolves to RemoteMCPServerBase, which inherits core's
# MCPServerBase (parrot.mcp.server_base.MCPServerBase).
MCPServerBase = RemoteMCPServerBase
