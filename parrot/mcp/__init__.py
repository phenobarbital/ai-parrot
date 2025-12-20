"""MCP integration for AI-Parrot."""

from .integration import (
    MCPEnabledMixin,
    MCPServerConfig,
    MCPToolManager,
    MCPClient,
    create_local_mcp_server,
    create_http_mcp_server,
    create_api_key_mcp_server,
)
from .config import AuthMethod
from .oauth import APIKeyStore, ExternalOAuthValidator, APIKeyRecord
from .client import AuthScheme, AuthCredential
from .context import (
    ReadonlyContext,
    MCPSessionManager,
    TransientMCPError,
    retry_on_errors,
)

__all__ = [
    "MCPEnabledMixin",
    "MCPServerConfig",
    "MCPToolManager",
    "MCPClient",
    "create_local_mcp_server",
    "create_http_mcp_server",
    "create_api_key_mcp_server",
    "AuthMethod",
    "APIKeyStore",
    "ExternalOAuthValidator",
    "APIKeyRecord",
    # New exports
    "AuthScheme",
    "AuthCredential",
    "ReadonlyContext",
    "MCPSessionManager",
    "TransientMCPError",
    "retry_on_errors",
]
