---
type: Concept
title: create_fireflies_mcp_server()
id: func:parrot.mcp.integration.create_fireflies_mcp_server
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Create configuration for Fireflies MCP server using stdio transport.
---

# create_fireflies_mcp_server

```python
def create_fireflies_mcp_server(*, api_key: Optional[str]=None, api_base: str='https://api.fireflies.ai/mcp', **kwargs) -> MCPServerConfig
```

Create configuration for Fireflies MCP server using stdio transport.

Fireflies MCP requires using npx mcp-remote as a command-line proxy.

The API key is resolved with the following precedence:
  1. Explicit ``api_key`` argument.
  2. ``FIREFLIES_API_KEY`` environment variable (via ``navconfig.config``).
  3. ``ValueError`` if neither is available.

Args:
    api_key: Fireflies API key (optional; falls back to FIREFLIES_API_KEY env var)
    api_base: Base URL of the Fireflies MCP endpoint
    **kwargs: Additional MCPServerConfig parameters

Returns:
    MCPServerConfig instance configured for stdio transport

Raises:
    ValueError: When no API key is available from argument or environment.
