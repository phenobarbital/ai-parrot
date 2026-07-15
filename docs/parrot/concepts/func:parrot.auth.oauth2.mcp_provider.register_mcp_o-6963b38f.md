---
type: Concept
title: register_mcp_oauth2_provider()
id: func:parrot.auth.oauth2.mcp_provider.register_mcp_oauth2_provider
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Create an :class:`MCPOAuth2Provider` and register it in the global registry.
---

# register_mcp_oauth2_provider

```python
def register_mcp_oauth2_provider(server_name: str, config: MCPOAuth2Config, storage: Optional['VaultMCPTokenStorage']=None) -> MCPOAuth2Provider
```

Create an :class:`MCPOAuth2Provider` and register it in the global registry.

Convenience wrapper for application startup.  Idempotent: registering
the same ``server_name`` twice overwrites the previous entry.

Args:
    server_name: MCP server slug (e.g. ``"netsuite"``).
    config: OAuth2 configuration for this server.
    storage: Optional token storage adapter.

Returns:
    The newly registered :class:`MCPOAuth2Provider` instance.

Example:
    >>> cfg = MCPOAuth2Config(client_id="my-id", scopes=["mcp"])
    >>> provider = register_mcp_oauth2_provider("netsuite", cfg)
    >>> OAuth2ProviderRegistry().get("mcp:netsuite") is provider
    True
