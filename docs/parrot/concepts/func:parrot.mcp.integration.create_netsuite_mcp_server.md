---
type: Concept
title: create_netsuite_mcp_server()
id: func:parrot.mcp.integration.create_netsuite_mcp_server
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Create a NetSuite MCP server configuration using OAuth2 Authorization Code
  + PKCE.
---

# create_netsuite_mcp_server

```python
def create_netsuite_mcp_server(*, account_id: str, client_id: str, user_id: str, name: str='netsuite', headers: Optional[Dict[str, Any]]=None) -> MCPServerConfig
```

Create a NetSuite MCP server configuration using OAuth2 Authorization Code + PKCE.

Constructs NetSuite-specific auth/token URLs from the given ``account_id``
and uses the NetSuite preset from :mod:`parrot.mcp.oauth2_config` for the
full OAuth2 flow.  Scope is fixed to ``["mcp"]`` as required by the
NetSuite AI Connector.

Args:
    account_id: NetSuite account ID (e.g. ``"4984231"``).
    client_id: OAuth2 client ID from the NetSuite integration record.
    user_id: Caller's user identifier used to scope token storage.
    name: Server name used as the registry key (default ``"netsuite"``).
        Override when connecting two NetSuite accounts simultaneously
        (e.g. ``"netsuite-sandbox"``).
    headers: Extra HTTP headers to include with every MCP request.

Returns:
    :class:`~parrot.mcp.client.MCPClientConfig` configured for NetSuite.

Example:
    >>> from parrot.mcp.integration import create_netsuite_mcp_server
    >>> cfg = create_netsuite_mcp_server(
    ...     account_id="4984231",
    ...     client_id="my-client-id",
    ...     user_id="user@co.com",
    ... )
