---
type: Concept
title: validate_mcp_http()
id: func:parrot.mcp.integration.validate_mcp_http
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Validate that an MCP HTTP server is reachable and lists its tools.
---

# validate_mcp_http

```python
async def validate_mcp_http(config: 'MCPServerConfig') -> None
```

Validate that an MCP HTTP server is reachable and lists its tools.

Connects to the MCP server described by *config*, retrieves the tool
listing once, then disconnects.  On any failure the client is always
disconnected before the exception propagates.

Args:
    config: An :class:`MCPServerConfig` (``MCPClientConfig``) instance
        describing the target MCP HTTP server (URL, auth, etc.).

Raises:
    MCPValidationError: When the server is unreachable, times out, or
        returns an unexpected tool-listing response.
