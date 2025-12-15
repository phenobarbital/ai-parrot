from dataclasses import dataclass, field
from typing import List, Optional, Any
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
    transport: str = "stdio"  # "stdio" or "http" or "unix"
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
    oauth_scopes: Optional[List[str]] = None
    oauth_token_ttl: int = 3600
    oauth_code_ttl: int = 600
    oauth_allow_dynamic_registration: bool = True

    # base path for HTTP transport
    base_path: str = "/mcp"
    # custom events path for SSE (optional)
    events_path: Optional[str] = None
    
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