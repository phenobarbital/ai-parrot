---
type: Concept
title: create_websocket_mcp_server()
id: func:parrot.mcp.integration.create_websocket_mcp_server
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Create a WebSocket MCP server configuration.
---

# create_websocket_mcp_server

```python
def create_websocket_mcp_server(name: str, url: str, auth_type: Optional[str]=None, auth_config: Optional[Dict[str, Any]]=None, headers: Optional[Dict[str, str]]=None, **kwargs) -> MCPServerConfig
```

Create a WebSocket MCP server configuration.

Args:
    name: Server name
    url: WebSocket URL (ws:// or wss://)
    auth_type: Authentication type ("bearer", "api_key", "oauth", or None)
    auth_config: Authentication configuration dict
    headers: Additional HTTP headers for WebSocket upgrade
    **kwargs: Additional MCPServerConfig parameters

Returns:
    MCPServerConfig configured for WebSocket transport

Example:
    >>> config = create_websocket_mcp_server(
    ...     "my-ws-server",
    ...     "ws://localhost:8766/mcp/ws",
    ...     auth_type="bearer",
    ...     auth_config={"token": "my-secret-token"}
    ... )
    >>> async with MCPClient(config) as client:
    ...     tools = await client.list_tools()
