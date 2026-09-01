from dataclasses import dataclass
from typing import List, Optional, Any, Dict
from enum import Enum
from urllib.parse import urlparse

from pydantic import BaseModel, field_validator


class AuthMethod(str, Enum):
    """Authentication method for MCP server."""
    NONE = "none"
    API_KEY = "api_key"  # Header-based API key validation
    OAUTH2_INTERNAL = "oauth2_internal"  # In-memory OAuthAuthorizationServer
    OAUTH2_EXTERNAL = "oauth2_external"  # External OAuth2 (Azure, Keycloak)
    BEARER = "bearer"  # navigator-auth session-based


class AgentMCPMountConfig(BaseModel):
    """Configuration for mounting AI-Parrot agents as per-agent MCP servers.

    FEAT-477 §2 Data Models / §3 Module 2. One `AgentMCPMount` is built from
    one of these per `BotManager`; each configured agent gets its own
    Streamable HTTP endpoint at `{base_path}/{agent_name}`.

    Attributes:
        agents: Agent names to mount, resolved via `BotManager.get_bots()`.
        base_path: Route prefix under which each agent's endpoint is
            registered (`{base_path}/{agent_name}`).
        aggregate_enabled: Whether to also publish an optional aggregate
            `/mcp` endpoint exposing every agent's tools as
            `{agent}__{tool}`. The aggregate is naming sugar only — both
            name forms resolve to the same PBAC resource.
        default_tenant_id: Single-tenant fallback. This is the **only**
            live tenant-resolution path until navigator-auth (FEAT-095)
            emits a tenant claim (spec §8).
        resource_server_url: RFC 8707 audience URL for this mount. Must be
            an absolute URI.
        max_result_tokens: Per-mount default result-size cap, under the
            ~30,000-token connector ceiling.
        call_deadline_seconds: Per-call deadline, below the 300s client
            ceiling.
    """

    agents: list[str]
    base_path: str = "/mcp/agents"
    aggregate_enabled: bool = False
    default_tenant_id: str | None = None
    resource_server_url: str
    max_result_tokens: int = 25_000
    call_deadline_seconds: float = 240.0

    @field_validator("agents")
    @classmethod
    def _validate_agent_names(cls, value: list[str]) -> list[str]:
        """Reject agent names containing the aggregate separator.

        Args:
            value: Candidate list of agent names.

        Returns:
            The validated list of agent names.

        Raises:
            ValueError: If any agent name contains `__`, which is reserved
                as the aggregate endpoint's `{agent}__{tool}` separator.
        """
        for name in value:
            if "__" in name:
                raise ValueError(
                    f"agent name {name!r} must not contain the aggregate "
                    "separator '__'"
                )
        return value

    @field_validator("resource_server_url")
    @classmethod
    def _validate_absolute_url(cls, value: str) -> str:
        """Ensure `resource_server_url` is an absolute URI.

        Args:
            value: Candidate resource server URL.

        Returns:
            The validated absolute URL.

        Raises:
            ValueError: If `value` lacks a scheme and network location.
        """
        parsed = urlparse(value)
        if not (parsed.scheme and parsed.netloc):
            raise ValueError(
                f"resource_server_url must be an absolute URI, got {value!r}"
            )
        return value

    @field_validator("call_deadline_seconds")
    @classmethod
    def _validate_call_deadline(cls, value: float) -> float:
        """Ensure the per-call deadline stays below the client ceiling.

        Args:
            value: Candidate call deadline, in seconds.

        Returns:
            The validated call deadline.

        Raises:
            ValueError: If `value` is at or above the 300s client ceiling.
        """
        if value >= 300:
            raise ValueError(
                "call_deadline_seconds must be below the 300s client "
                f"ceiling, got {value}"
            )
        return value

    @field_validator("max_result_tokens")
    @classmethod
    def _validate_max_result_tokens(cls, value: int) -> int:
        """Ensure the result-size cap stays below the connector ceiling.

        Args:
            value: Candidate max-result-tokens cap.

        Returns:
            The validated cap.

        Raises:
            ValueError: If `value` is at or above the ~30,000-token
                connector ceiling.
        """
        if value >= 30_000:
            raise ValueError(
                "max_result_tokens must be below the ~30000-token "
                f"connector ceiling, got {value}"
            )
        return value


@dataclass
class MCPServerConfig:
    """Configuration for MCP server."""
    name: str = "ai-parrot-mcp-server"
    version: str = "1.0.0"
    description: str = "AI-Parrot Tools via MCP Protocol"

    # Server settings
    # "stdio", "http", "streamable-http", "sse", "unix" or "quic".
    # Use "streamable-http" for MCP Streamable HTTP (2025-03-26) clients
    # such as Claude.ai custom connectors.
    transport: str = "stdio"
    host: str = "localhost"
    port: int = 8080
    socket_path: Optional[str] = None  # For UNIX socket transport

    # Tool filtering
    allowed_tools: Optional[List[str]] = None
    blocked_tools: Optional[List[str]] = None

    # Logging
    log_level: str = "INFO"

    # Authentication method (replaces enable_oauth for new code)
    auth_method: AuthMethod = AuthMethod.NONE

    # API Key settings
    api_key_header: str = "X-API-Key"
    api_key_store: Optional[Any] = None  # APIKeyStore instance

    # External OAuth2 settings (for OAUTH2_EXTERNAL)
    oauth2_issuer_url: Optional[str] = None
    oauth2_introspection_endpoint: Optional[str] = None
    oauth2_client_id: Optional[str] = None
    oauth2_client_secret: Optional[str] = None
    oauth2_resource_server_url: Optional[str] = None

    # OAuth / Authorization (for OAUTH2_INTERNAL, backward compatible)
    enable_oauth: bool = False  # Deprecated: use auth_method instead
    oauth_scope: Optional[List[str]] = None
    oauth_token_ttl: int = 3600
    oauth_code_ttl: int = 600
    oauth_allow_dynamic_registration: bool = True
    oauth_static_clients: Optional[List[Dict[str, Any]]] = None

    # base path for HTTP transport
    base_path: str = "/mcp"
    # custom events path for SSE (optional)
    events_path: Optional[str] = None

    # Streamable HTTP transport settings
    # Browser origins allowed on the /mcp endpoint (DNS-rebinding
    # protection, mandatory per the MCP spec). Localhost is always allowed
    # and requests without an Origin header (server-to-server clients such
    # as Claude.ai) are unaffected; any other origin must be listed here.
    allowed_origins: Optional[List[str]] = None
    # Escape hatch: skip Origin validation entirely. Only for deployments
    # already fronted by a proxy that performs the same check.
    allow_any_origin: bool = False
    # Idle seconds before an Mcp-Session-Id session expires.
    session_ttl: int = 3600
    # Max buffered SSE events per stream (Last-Event-ID resumability window).
    event_buffer_size: int = 1000
    # Max concurrent sessions; further initialize calls are refused with 503
    # rather than growing memory without bound.
    max_sessions: int = 1000
    # Max SSE streams retained per session. Each request-bearing SSE POST
    # opens one; beyond the cap the least useful are evicted so a busy
    # session cannot accumulate buffers for the whole of its TTL.
    max_streams_per_session: int = 64
    
    # For Future gRPC implementation (expected)
    grpc_host: Optional[str] = None
    grpc_port: Optional[int] = None
    grpc_use_tls: bool = True
    grpc_cert_path: Optional[str] = None
    grpc_use_protobuf: bool = False  # Use native protobuf vs JSON-RPC wrapper

    # QUIC transport settings
    quic_cert_path: Optional[str] = None
    quic_key_path: Optional[str] = None
    quic_serialization: str = "msgpack"  # "json" or "msgpack"
    quic_enable_0rtt: bool = True
    quic_max_datagram_size: int = 65536
    quic_idle_timeout: float = 60.0
    quic_webtransport_path: str = "/mcp"

    # HTTPS / SSL settings
    ssl_cert_path: Optional[str] = None
    ssl_key_path: Optional[str] = None
    http_use_tls: bool = False

    # FEAT-477: agent-mount settings (exposed agents, aggregate on/off,
    # size caps, tenant). None keeps today's tool-only behavior unchanged
    # (G11) — set to enable AgentMCPMount alongside the tool-level server.
    agent_mount: Optional[AgentMCPMountConfig] = None


@dataclass
class TransportConfig:
    """Configuration for a single MCP transport (used by ParrotMCPServer)."""

    transport: str  # "stdio", "http", "streamable-http", "sse", "unix", "quic"
    enabled: bool = True
    host: Optional[str] = None  # Only for HTTP
    port: Optional[int] = None  # Only for HTTP
    url: Optional[str] = None  # Only for HTTP/SSE transport
    name_suffix: Optional[str] = None  # e.g., "local" or "remote"
    socket_path: Optional[str] = None  # Only for UNIX socket transport
    # Route prefix for HTTP-like transports on a shared app. Two HTTP-like
    # transports cannot share one; set distinct paths to run e.g. http and
    # streamable-http side by side. None = MCPServerConfig.base_path.
    base_path: Optional[str] = None