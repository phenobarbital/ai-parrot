"""MCP integration for AI-Parrot."""
from pkgutil import extend_path
__path__ = extend_path(__path__, __name__)

# FEAT-403: local MCP server hierarchy (tool adapter, resources, JSON-RPC
# server base, and the stdio transport) — zero external deps, always
# available in core, and always imported eagerly (unlike everything below).
from .adapter import MCPToolAdapter
from .resources import MCPResource
from .server_base import MCPServerBase, LocalServerConfig
from .local_server import LocalMCPServerBase, StdioMCPServer

# FEAT-477: agent-method MCP exposure declaration + reification. Core-only
# (G9) — zero ai-parrot-server deps, so eager alongside the other zero-dep
# modules above.
from .agent_tools import (
    MCP_TOOL_ATTR,
    AgentMethodTool,
    MCPToolDeclaration,
    build_exposure_set,
    mcp_tool,
)

# Consumer-side classes (stay in core) — resolved lazily via __getattr__
# below. `.integration` imports `navconfig` (which chdir()s to the
# installed package root and prints diagnostics to stdout as a side
# effect) plus `parrot.mcp.transports.*` (only present when
# ai-parrot-server is installed) — eagerly importing it here used to mean
# ANY import touching this package (including the zero-dep modules above)
# paid that cost, and core-only consumers (e.g. `wikitoolkit mcp`, whose
# stdout IS the JSON-RPC channel) had to work around it themselves. Lazy
# resolution means importing `parrot.mcp.server_base`/`local_server`/
# `adapter`/`resources` alone no longer pulls any of this in.
_CORE_CLASSES = {
    "MCPEnabledMixin": ".integration",
    "MCPServerConfig": ".integration",
    "MCPClient": ".integration",
    "create_local_mcp_server": ".integration",
    "create_http_mcp_server": ".integration",
    "create_api_key_mcp_server": ".integration",
    "create_netsuite_m2m_mcp_server": ".integration",
    "NetSuiteM2MAuth": ".oauth",
    "TokenStore": ".oauth",
    "InMemoryTokenStore": ".oauth",
    "RedisTokenStore": ".oauth",
    "VaultTokenStore": ".oauth",
    "AuthScheme": ".client",
    "AuthCredential": ".client",
    "ReadonlyContext": ".context",
    "MCPSessionManager": ".context",
    "TransientMCPError": ".context",
    "retry_on_errors": ".context",
    "MCPServerRegistry": ".registry",
    "MCPServerDescriptor": ".registry",
    "MCPServerParam": ".registry",
    "MCPParamType": ".registry",
    "UserMCPServerConfig": ".registry",
    "ActivateMCPServerRequest": ".registry",
    "get_factory_map": ".registry",
}

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
    if name in _CORE_CLASSES:
        import importlib
        mod = importlib.import_module(_CORE_CLASSES[name], package=__name__)
        return getattr(mod, name)
    if name in _SERVER_CLASSES:
        from parrot._imports import load_satellite_attr

        module_path, cls_name = _SERVER_CLASSES[name]
        return load_satellite_attr(
            name, module_path, install="ai-parrot-server", attr=cls_name
        )
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # FEAT-403: local MCP server hierarchy
    "MCPToolAdapter",
    "MCPResource",
    "MCPServerBase",
    "LocalServerConfig",
    "LocalMCPServerBase",
    "StdioMCPServer",
    # FEAT-477: agent-method MCP exposure declaration + reification
    "MCP_TOOL_ATTR",
    "MCPToolDeclaration",
    "mcp_tool",
    "AgentMethodTool",
    "build_exposure_set",
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
