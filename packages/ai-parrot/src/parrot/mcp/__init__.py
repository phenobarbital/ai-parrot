"""MCP integration for AI-Parrot."""
from pkgutil import extend_path
__path__ = extend_path(__path__, __name__)

# Consumer-side imports (stay in core, always available)
from .integration import (
    MCPEnabledMixin,
    MCPServerConfig,
    MCPClient,
    create_local_mcp_server,
    create_http_mcp_server,
    create_api_key_mcp_server,
    create_netsuite_m2m_mcp_server,
)
from .oauth import (
    NetSuiteM2MAuth,
    TokenStore,
    InMemoryTokenStore,
    RedisTokenStore,
    VaultTokenStore,
)
from .client import AuthScheme, AuthCredential
from .context import (
    ReadonlyContext,
    MCPSessionManager,
    TransientMCPError,
    retry_on_errors,
)
from .registry import (
    MCPServerRegistry,
    MCPServerDescriptor,
    MCPServerParam,
    MCPParamType,
    UserMCPServerConfig,
    ActivateMCPServerRequest,
    get_factory_map,
)

# Server-side exports (move to satellite in TASK-1369 — lazy via __getattr__)
# AuthMethod, MCPServerConfig(from config) — satellite: parrot.mcp.config
# APIKeyStore, ExternalOAuthValidator, APIKeyRecord — satellite: parrot.mcp.oauth_server
_SERVER_CLASSES = {
    "AuthMethod": ("parrot.mcp.config", "AuthMethod"),
    "APIKeyStore": ("parrot.mcp.oauth_server", "APIKeyStore"),
    "ExternalOAuthValidator": ("parrot.mcp.oauth_server", "ExternalOAuthValidator"),
    "APIKeyRecord": ("parrot.mcp.oauth_server", "APIKeyRecord"),
    "OAuthAuthorizationServer": ("parrot.mcp.oauth_server", "OAuthAuthorizationServer"),
    "OAuthRoutesMixin": ("parrot.mcp.oauth_server", "OAuthRoutesMixin"),
}


def __getattr__(name: str):
    if name in _SERVER_CLASSES:
        module_path, cls_name = _SERVER_CLASSES[name]
        try:
            import importlib
            mod = importlib.import_module(module_path)
            return getattr(mod, cls_name)
        except ImportError:
            raise ImportError(
                f"{name!r} requires the ai-parrot-server package. "
                f"Install it with: pip install ai-parrot-server"
            ) from None
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "MCPEnabledMixin",
    "MCPServerConfig",
    "MCPClient",
    "create_local_mcp_server",
    "create_http_mcp_server",
    "create_api_key_mcp_server",
    "create_netsuite_m2m_mcp_server",
    "NetSuiteM2MAuth",
    "AuthMethod",
    "APIKeyStore",
    "ExternalOAuthValidator",
    "APIKeyRecord",
    "OAuthAuthorizationServer",
    "OAuthRoutesMixin",
    "TokenStore",
    "InMemoryTokenStore",
    "RedisTokenStore",
    "VaultTokenStore",
    # New exports
    "AuthScheme",
    "AuthCredential",
    "ReadonlyContext",
    "MCPSessionManager",
    "TransientMCPError",
    "retry_on_errors",
    # MCP Server Registry
    "MCPServerRegistry",
    "MCPServerDescriptor",
    "MCPServerParam",
    "MCPParamType",
    "UserMCPServerConfig",
    "ActivateMCPServerRequest",
    "get_factory_map",
]
