from dataclasses import dataclass
from typing import List, Optional, Any, Dict
from enum import Enum


class AuthMethod(str, Enum):
    """Authentication method for MCP server."""
    NONE = "none"
    API_KEY = "api_key"  # Header-based API key validation
    OAUTH2_INTERNAL = "oauth2_internal"  # In-memory OAuthAuthorizationServer
    OAUTH2_EXTERNAL = "oauth2_external"  # External OAuth2 (Azure, Keycloak)
    BEARER = "bearer"  # navigator-auth session-based


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