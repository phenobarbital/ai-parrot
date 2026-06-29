from typing import Dict, Any, Optional, List, Callable, TYPE_CHECKING, Union
import asyncio
import base64
import logging
import time
from enum import Enum
from dataclasses import dataclass, field
from pydantic import BaseModel, Field, model_validator

from parrot.mcp.oauth2_config import MCPOAuth2Config, get_mcp_oauth2_preset

if TYPE_CHECKING:
    from .context import ReadonlyContext
    from .filtering import ToolPredicate


class AuthScheme(str, Enum):
    """Type-safe authentication schemes."""
    NONE = "none"
    BEARER = "bearer"
    API_KEY = "api_key"
    BASIC = "basic"
    OAUTH2 = "oauth2"
    MTLS = "mtls"
    AWS_SIG_V4 = "aws_sig_v4"


class AuthCredential(BaseModel):
    """Type-safe credential container with validation.

    Validates that required fields are present based on the chosen scheme.

    Example:
        >>> # Bearer token
        >>> cred = AuthCredential(scheme=AuthScheme.BEARER, token="my-token")

        >>> # API Key with custom header
        >>> cred = AuthCredential(
        ...     scheme=AuthScheme.API_KEY,
        ...     api_key="secret",
        ...     api_key_header="X-Custom-Key"
        ... )

        >>> # Get headers
        >>> headers = cred.get_auth_headers()
    """

    scheme: AuthScheme = Field(..., description="Authentication scheme")

    # Bearer token
    token: Optional[str] = Field(None, description="Bearer/OAuth2 token")

    # API Key
    api_key: Optional[str] = Field(None, description="API key")
    api_key_header: Optional[str] = Field(
        default="X-API-Key",
        description="Header name for API key"
    )
    use_bearer_prefix: bool = Field(
        default=False,
        description="If True, prepend 'Bearer ' to API key value"
    )

    # Basic auth
    username: Optional[str] = Field(None, description="Username for basic auth")
    password: Optional[str] = Field(None, description="Password for basic auth")

    # mTLS
    cert_path: Optional[str] = Field(None, description="Path to client certificate")
    key_path: Optional[str] = Field(None, description="Path to client key")
    ca_cert_path: Optional[str] = Field(None, description="Path to CA certificate")

    # AWS Signature V4
    aws_access_key: Optional[str] = Field(None, description="AWS access key")
    aws_secret_key: Optional[str] = Field(None, description="AWS secret key")
    aws_region: Optional[str] = Field(default="us-east-1", description="AWS region")
    aws_service: Optional[str] = Field(default="execute-api", description="AWS service name")

    class Config:
        validate_assignment = True

    @model_validator(mode="after")
    def validate_scheme_requirements(self):
        """Validate that required fields are set for chosen scheme."""
        scheme = self.scheme

        if scheme == AuthScheme.BEARER and not self.token:
            raise ValueError("Bearer scheme requires 'token' field")
        if scheme == AuthScheme.API_KEY and not self.api_key:
            raise ValueError("API Key scheme requires 'api_key' field")
        if scheme == AuthScheme.BASIC and (not self.username or not self.password):
            raise ValueError("Basic auth requires 'username' and 'password'")
        if scheme == AuthScheme.MTLS and (not self.cert_path or not self.key_path):
            raise ValueError("mTLS requires 'cert_path' and 'key_path'")
        if scheme == AuthScheme.AWS_SIG_V4 and (not self.aws_access_key or not self.aws_secret_key):
            raise ValueError("AWS Sig V4 requires 'aws_access_key' and 'aws_secret_key'")
        if scheme == AuthScheme.OAUTH2 and not self.token:
            raise ValueError("OAuth2 scheme requires 'token' field")

        return self

    def get_auth_headers(self) -> Dict[str, str]:
        """Generate appropriate auth headers based on scheme.

        Returns:
            Dictionary of authentication headers

        Note:
            AWS Sig V4 and mTLS require special handling at the transport level
            and are not returned as simple headers.
        """
        if self.scheme == AuthScheme.NONE or self.scheme is None:
            return {}
        elif self.scheme == AuthScheme.BEARER:
            return {"Authorization": f"Bearer {self.token}"}
        elif self.scheme == AuthScheme.API_KEY:
            value = f"Bearer {self.api_key}" if self.use_bearer_prefix else self.api_key
            return {self.api_key_header: value}
        elif self.scheme == AuthScheme.BASIC:
            creds = base64.b64encode(
                f"{self.username}:{self.password}".encode()
            ).decode()
            return {"Authorization": f"Basic {creds}"}
        elif self.scheme == AuthScheme.OAUTH2:
            return {"Authorization": f"Bearer {self.token}"}
        # AWS Sig V4 and mTLS are handled at transport level
        elif self.scheme in (AuthScheme.MTLS, AuthScheme.AWS_SIG_V4):
            return {}
        return {}


@dataclass
class MCPClientConfig:
    """Complete configuration for external MCP server connection.

    Supports both static configuration and dynamic behavior through
    header_provider and token_supplier callbacks.

    Example:
        >>> # Static config
        >>> config = MCPClientConfig(
        ...     name="my-server",
        ...     url="http://localhost:8080/mcp",
        ...     transport="http",
        ...     headers={"X-API-Key": "secret"}
        ... )

        >>> # Dynamic headers based on context
        >>> def my_header_provider(ctx):
        ...     return {"X-User-ID": ctx.user_id} if ctx else {}
        >>> config = MCPClientConfig(
        ...     name="my-server",
        ...     url="http://localhost:8080/mcp",
        ...     header_provider=my_header_provider
        ... )
    """
    name: str

    # Connection parameters
    url: Optional[str] = None  # For HTTP/SSE servers
    command: Optional[str] = None  # For stdio servers
    args: Optional[List[str]] = None  # Command arguments
    env: Optional[Dict[str, str]] = None  # Environment variables

    # Metadata
    description: Optional[str] = None  # For OpenAI MCP definitions

    # Authentication
    auth_credential: Optional[AuthCredential] = None
    auth_type: Optional[AuthScheme] = None  # "oauth", "bearer", "basic", "api_key", "none"
    auth_config: Dict[str, Any] = field(default_factory=dict)
    # A token supplier hook the HTTP client will call to add headers.
    # Used by NetSuiteM2MAuth and similar M2M token providers.
    token_supplier: Optional[Callable[[], Optional[str]]] = None

    # Transport type
    transport: str = "auto"  # "auto", "stdio", "http", "sse" or "unix"
    base_path: Optional[str] = None  # Base path for HTTP/SSE endpoints
    events_path: Optional[str] = None  # SSE events path
    # URL for Unix socket (for unix transport)
    socket_path: Optional[str] = None

    # Additional headers for HTTP transports
    headers: Dict[str, str] = field(default_factory=dict)
    # Dynamic header provider - called at tool execution time with context
    header_provider: Optional[Callable[['ReadonlyContext'], Dict[str, str]]] = None

    # NEW: Dynamic tool filtering
    # Can be:
    #  - None: Allow all tools
    #  - List[str]: Allow only these tool names (simple allowlist)
    #  - Callable: Custom predicate function(tool, context) -> bool
    tool_filter: Optional[Union[List[str], Callable[['ToolPredicate'], bool]]] = None
    allowed_tools: Optional[List[str]] = None
    blocked_tools: Optional[List[str]] = None

    # NEW: Tool confirmation
    # Can be:
    #  - False: No confirmation needed (default)
    #  - True: Always require confirmation
    #  - Callable: Dynamic logic function(tool_name, args) -> bool
    require_confirmation: Union[bool, Callable[[str, Dict[str, Any]], bool]] = False

    # Tool prefix (optional)
    tool_name_prefix: Optional[str] = None

    # Connection settings
    timeout: float = 30.0
    retry_count: int = 3
    startup_delay: float = 0.5

    # Rate-limit backoff (for -32429 "Rate limit exceeded" responses).
    # On a rate-limit error the client waits the server-suggested retryAfter
    # (or an exponential fallback) and retries, up to rate_limit_max_retries.
    # If the suggested wait exceeds rate_limit_max_wait it fails fast instead
    # of blocking the agent for minutes/hours.
    rate_limit_max_retries: int = 2
    rate_limit_max_wait: float = 60.0
    rate_limit_base_delay: float = 1.0

    # Process management
    kill_timeout: float = 5.0

    # QUIC Configuration
    quic_config: Any = None

    # OAuth2 configuration (FEAT-262)
    # When set, the transport layer uses the MCP SDK OAuth2 flow instead of
    # static auth_credential headers.
    oauth2: Optional[MCPOAuth2Config] = field(default=None)
    # Preset name for the OAuth2 configuration (resolved in from_yaml_config)
    auth_preset: Optional[str] = field(default=None)
    # User identifier used to scope OAuth2 token storage per user + per server.
    # Maps to VaultTokenStore key: mcp_oauth_{server}_{user_id}.
    # When None, token storage falls back to "default" (shared, non-user-scoped).
    user_id: Optional[str] = field(default=None)

    # FEAT-264: When True, read the per-call CredentialBroker-resolved token from
    # the ``current_credential()`` ContextVar and inject it as
    # ``Authorization: Bearer <token>`` at call time (not connect time).
    # Set this on MCP servers whose provider has auth="mcp" in the broker config.
    inject_broker_credential: bool = False

    async def get_headers(self, context: Optional['ReadonlyContext'] = None) -> Dict[str, str]:
        """Get merged static, auth, and dynamic headers.

        Order of precedence (later overrides earlier):
        1. Static headers from self.headers
        2. Auth headers from auth_credential.get_auth_headers()
        3. Dynamic headers from header_provider(context)

        Args:
            context: Optional ReadonlyContext for dynamic header generation

        Returns:
            Merged dictionary of all headers

        Example:
            >>> headers = await config.get_headers(ctx)
            >>> # Returns: {"X-API-Key": "...", "Authorization": "Bearer ...", "X-User-ID": "123"}
        """
        result = dict(self.headers)

        # Add auth headers from auth_credential only when oauth2 is NOT configured.
        # When oauth2 is set the MCP SDK handles authentication at the transport layer.
        if self.auth_credential and not self.oauth2:
            auth_headers = self.auth_credential.get_auth_headers()
            result |= auth_headers

        # Add dynamic headers from provider
        if self.header_provider and context:
            dynamic = self.header_provider(context)
            # Support both sync and async header providers
            if asyncio.iscoroutine(dynamic):
                dynamic = await dynamic
            result.update(dynamic)

        # FEAT-264: Inject the CredentialBroker-resolved per-user bearer token
        # when inject_broker_credential=True.  The token lives in the per-call
        # ContextVar set by the tool-loop seam (AbstractTool.execute) so this
        # path is only active during a credentialed tool invocation.
        if self.inject_broker_credential:
            try:
                from parrot.tools.abstract import current_credential
                cred = current_credential()
                if cred is not None:
                    # Never overwrite an existing Authorization header that was
                    # set by a higher-priority source (auth_credential, header_provider).
                    result.setdefault("Authorization", f"Bearer {cred}")
            except ImportError:
                pass  # parrot.tools.abstract not importable in edge environments

        return result

    def validate_transport(self) -> None:
        """Validate transport-specific configuration.

        Raises:
            ValueError: If configuration is invalid for the specified transport
        """
        if self.transport == "stdio" and not self.command:
            raise ValueError("stdio transport requires 'command' field")
        if self.transport == "http" and not self.url:
            raise ValueError("http transport requires 'url' field")
        if self.transport == "sse" and not self.url:
            raise ValueError("sse transport requires 'url' field")
        if self.transport == "unix" and not self.socket_path:
            raise ValueError("unix transport requires 'socket_path' field")
        if self.transport == "websocket" and not self.url:
            raise ValueError("websocket transport requires 'url' field")

    @classmethod
    def from_yaml_config(
        cls,
        config_dict: Dict[str, Any],
        config_abs_path: str = ""
    ) -> 'MCPClientConfig':
        """Load from YAML configuration with validation.

        Args:
            config_dict: Dictionary loaded from YAML file
            config_abs_path: Absolute path to YAML file (for error messages)

        Returns:
            MCPClientConfig instance

        Raises:
            ValueError: If configuration is invalid

        Example:
            >>> import yaml
            >>> with open("mcp_servers.yaml") as f:
            ...     config = yaml.safe_load(f)
            >>> mcp_config = MCPClientConfig.from_yaml_config(
            ...     config['servers']['my-server'],
            ...     "/path/to/mcp_servers.yaml"
            ... )
        """
        # Validate transport selection - exactly one transport indicator must be set
        transport_fields = {
            'command': config_dict.get('command'),
            'url': config_dict.get('url'),
            'socket_path': config_dict.get('socket_path'),
        }
        populated = [k for k, v in transport_fields.items() if v is not None]

        if not populated:
            raise ValueError(
                f"At least one of [command, url, socket_path] must be set in {config_abs_path}"
            )
        if len(populated) > 1 and config_dict.get('transport', 'auto') == 'auto':
            raise ValueError(
                f"Exactly one of [command, url, socket_path] should be set for auto transport. "
                f"Got: {populated}. Set 'transport' explicitly to override."
            )

        # Handle auth_credential if present as dict
        if 'auth_credential' in config_dict and isinstance(config_dict['auth_credential'], dict):
            config_dict['auth_credential'] = AuthCredential(**config_dict['auth_credential'])

        # Handle OAuth2 preset and inline oauth2 config (FEAT-262)
        auth_preset = config_dict.pop('auth_preset', None)
        oauth2_dict = config_dict.pop('oauth2', None)

        if auth_preset:
            preset = get_mcp_oauth2_preset(auth_preset)
            if not preset:
                raise ValueError(
                    f"Unknown MCP OAuth2 preset: '{auth_preset}' in {config_abs_path}"
                )
            base = preset.model_dump(
                exclude_none=True,
                exclude={'name', 'display_name', 'url_template', 'required_params'},
            )
            if oauth2_dict:
                base.update(oauth2_dict)  # inline oauth2 dict overrides preset defaults
            config_dict['oauth2'] = MCPOAuth2Config(**base)
        elif oauth2_dict:
            config_dict['oauth2'] = MCPOAuth2Config(**oauth2_dict)

        config_dict['auth_preset'] = auth_preset

        # Filter to only known fields
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}  # pylint: disable=no-member
        filtered = {k: v for k, v in config_dict.items() if k in known_fields}

        instance = cls(**filtered)
        instance.validate_transport()
        return instance


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
        if token := self.auth_config.get("token") or self.auth_config.get("access_token"):
            return {"Authorization": f"Bearer {token}"}

        raise ValueError(
            "Bearer authentication requires 'token' or 'access_token' in auth_config"
        )

    async def _get_oauth_headers(self) -> Dict[str, str]:
        """Get OAuth headers from a pre-acquired access token.

        This method handles the ``auth_type="oauth"`` path on MCPAuthHandler,
        which expects an already-acquired ``access_token`` in ``auth_config``.
        For fully managed OAuth2 flows (PKCE, client credentials, token refresh)
        set ``MCPClientConfig.oauth2`` instead — the MCP SDK handles the flow
        at the transport layer and this method is not called.
        """
        if access_token := self.auth_config.get("access_token"):
            return {"Authorization": f"Bearer {access_token}"}

        raise ValueError(
            "OAuth authentication via auth_config requires a pre-acquired "
            "'access_token'. For managed OAuth2 flows (PKCE, client credentials) "
            "use MCPClientConfig.oauth2 with an MCPOAuth2Config instead."
        )

    async def _get_basic_headers(self) -> Dict[str, str]:
        """Get Basic authentication headers."""
        username = self.auth_config.get("username")
        password = self.auth_config.get("password")

        if not username or not password:
            raise ValueError(
                "Basic authentication requires 'username' and 'password' in auth_config"
            )

        credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
        return {"Authorization": f"Basic {credentials}"}

    async def _get_api_key_headers(self) -> Dict[str, str]:
        """Get API key headers."""
        api_key = self.auth_config.get("api_key")
        header_name = self.auth_config.get("header_name", "X-API-Key")
        use_bearer_prefix = self.auth_config.get("use_bearer_prefix", False)

        if not api_key:
            raise ValueError("API key authentication requires 'api_key' in auth_config")

        # Add Bearer prefix if requested (e.g., for Fireflies API)
        value = f"Bearer {api_key}" if use_bearer_prefix else api_key
        return {header_name: value}


class MCPConnectionError(Exception):
    """MCP connection related errors."""
    pass


# JSON-RPC error code servers use to signal rate limiting (mirrors HTTP 429).
RATE_LIMIT_ERROR_CODE = -32429


class MCPRateLimitError(MCPConnectionError):
    """Raised when an MCP server rejects a request with a rate-limit error.

    Subclasses :class:`MCPConnectionError` so existing ``except`` blocks keep
    working, while callers that want backoff can catch this type specifically
    and honour ``retry_after``.

    Attributes:
        retry_after: Suggested seconds to wait before retrying, already
            normalized to a delay relative to *now* (absolute epoch hints are
            converted). ``None`` when the server gave no usable hint.
        code: The JSON-RPC error code (usually ``-32429``).
        raw_error: The original JSON-RPC ``error`` object from the server.
    """

    def __init__(
        self,
        message: str,
        *,
        retry_after: Optional[float] = None,
        code: int = RATE_LIMIT_ERROR_CODE,
        raw_error: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.retry_after = retry_after
        self.code = code
        self.raw_error = raw_error


def parse_retry_after(value: Any, *, now: Optional[float] = None) -> Optional[float]:
    """Normalize a server-provided retry hint into seconds-from-now.

    Servers are inconsistent about how they express ``retryAfter``. This
    accepts the three common forms and always returns a non-negative delay in
    seconds (or ``None`` when the value is missing/uninterpretable):

      * plain delay in seconds (HTTP ``Retry-After`` style): ``5``, ``2.5``
      * absolute epoch **seconds**: ``1782259200``
      * absolute epoch **milliseconds**: ``1782259200009`` (e.g. Fireflies)

    Args:
        value: The raw ``retryAfter`` value from the error payload.
        now: Override for the current epoch seconds (testing hook).

    Returns:
        Seconds to wait before retrying, clamped to ``>= 0``, or ``None``.
    """
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v < 0:
        return None

    now = now if now is not None else time.time()
    if v >= 1e12:          # epoch milliseconds
        return max(0.0, v / 1000.0 - now)
    if v >= 1e9:           # epoch seconds (a >31-year delay is implausible)
        return max(0.0, v - now)
    return v               # plain delay in seconds


def raise_for_jsonrpc_error(error: Dict[str, Any]) -> None:
    """Translate a JSON-RPC ``error`` object into the right exception.

    Rate-limit errors (code ``-32429`` or ``data.type == 'rate_limit_exceeded'``)
    become :class:`MCPRateLimitError` carrying a normalized ``retry_after``;
    everything else becomes a generic :class:`MCPConnectionError`.

    Always raises — never returns normally.
    """
    code = error.get("code")
    data = error.get("data") or {}
    is_rate_limit = (
        code == RATE_LIMIT_ERROR_CODE
        or (isinstance(data, dict) and data.get("type") == "rate_limit_exceeded")
    )
    if is_rate_limit:
        retry_after = parse_retry_after(data.get("retryAfter")) if isinstance(data, dict) else None
        base_msg = error.get("message") or "Rate limit exceeded"
        if retry_after is not None:
            base_msg = f"{base_msg}; retry after {retry_after:.1f}s"
        raise MCPRateLimitError(
            base_msg,
            retry_after=retry_after,
            code=code if isinstance(code, int) else RATE_LIMIT_ERROR_CODE,
            raw_error=error,
        )
    raise MCPConnectionError(f"Server error: {error}")
