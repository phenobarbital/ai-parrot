from typing import Dict, Any, Optional, List, Callable, TYPE_CHECKING, Union
import asyncio
import base64
import logging
from enum import Enum
from dataclasses import dataclass, field
from pydantic import BaseModel, Field, model_validator

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

    # Authentication
    auth_credential: Optional[AuthCredential] = None
    auth_type: Optional[AuthScheme] = None  # "oauth", "bearer", "basic", "api_key", "none"
    auth_config: Dict[str, Any] = field(default_factory=dict)
    # A token supplier hook the HTTP client will call to add headers (set by OAuthManager)
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

    # Process management
    kill_timeout: float = 5.0

    # QUIC Configuration
    quic_config: Any = None

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

        # Add auth headers from auth_credential
        if self.auth_credential:
            auth_headers = self.auth_credential.get_auth_headers()
            result |= auth_headers

        # Add dynamic headers from provider
        if self.header_provider and context:
            dynamic = self.header_provider(context)
            # Support both sync and async header providers
            if asyncio.iscoroutine(dynamic):
                dynamic = await dynamic
            result.update(dynamic)

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
        """Get OAuth headers (simplified - assumes token is already available)."""
        if access_token := self.auth_config.get("access_token"):
            return {"Authorization": f"Bearer {access_token}"}

        # TODO: manage OAuth flow to get token if not present
        raise ValueError(
            "OAuth authentication requires 'access_token' in auth_config"
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
