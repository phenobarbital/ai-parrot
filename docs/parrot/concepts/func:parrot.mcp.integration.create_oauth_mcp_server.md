---
type: Concept
title: create_oauth_mcp_server()
id: func:parrot.mcp.integration.create_oauth_mcp_server
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Create an MCP server configuration with OAuth2 authorization code flow.
---

# create_oauth_mcp_server

```python
def create_oauth_mcp_server(*, name: str, url: str, user_id: str, oauth2: Optional[MCPOAuth2Config]=None, client_id: Optional[str]=None, auth_url: Optional[str]=None, token_url: Optional[str]=None, scopes: Optional[list]=None, client_secret: Optional[str]=None, headers: Optional[dict]=None, **kwargs) -> MCPServerConfig
```

Create an MCP server configuration with OAuth2 authorization code flow.

Accepts either a ready-built :class:`~parrot.mcp.oauth2_config.MCPOAuth2Config`
or individual legacy parameters for backward compatibility.

Args:
    name: Server name / registry key.
    url: MCP server base URL.
    user_id: User identifier for token storage scoping.
    oauth2: Pre-built OAuth2 configuration.  When ``None``, a config is
        constructed from the legacy ``client_id`` / ``auth_url`` / etc. params.
    client_id: OAuth2 client ID (used when ``oauth2`` is ``None``).
    auth_url: Authorization endpoint (used when ``oauth2`` is ``None``).
    token_url: Token endpoint (used when ``oauth2`` is ``None``).
    scopes: OAuth2 scopes (used when ``oauth2`` is ``None``).
    client_secret: OAuth2 client secret (used when ``oauth2`` is ``None``).
    headers: Extra HTTP headers for every MCP request.
    **kwargs: Additional :class:`~parrot.mcp.client.MCPClientConfig` fields.

Returns:
    :class:`~parrot.mcp.client.MCPClientConfig` ready for use with
    :class:`~parrot.mcp.transports.http.HttpMCPSession`.
