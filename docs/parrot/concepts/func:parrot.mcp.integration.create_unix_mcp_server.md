---
type: Concept
title: create_unix_mcp_server()
id: func:parrot.mcp.integration.create_unix_mcp_server
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Create a Unix socket MCP server configuration.
---

# create_unix_mcp_server

```python
def create_unix_mcp_server(name: str, socket_path: str, **kwargs) -> MCPServerConfig
```

Create a Unix socket MCP server configuration.

Args:
    name: Server name
    socket_path: Path to Unix socket
    **kwargs: Additional MCPServerConfig parameters

Returns:
    MCPServerConfig configured for Unix socket transport

Example:
    >>> config = create_unix_mcp_server(
    ...     "workday",
    ...     "/tmp/parrot-mcp-workday.sock"
    ... )
    >>> async with MCPClient(config) as client:
    ...     tools = await client.list_tools()
