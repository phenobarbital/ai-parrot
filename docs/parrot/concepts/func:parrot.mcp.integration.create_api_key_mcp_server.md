---
type: Concept
title: create_api_key_mcp_server()
id: func:parrot.mcp.integration.create_api_key_mcp_server
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Create configuration for API key authenticated MCP server.
---

# create_api_key_mcp_server

```python
def create_api_key_mcp_server(name: str, url: str, api_key: str, header_name: str='X-API-Key', use_bearer_prefix: bool=False, **kwargs) -> MCPServerConfig
```

Create configuration for API key authenticated MCP server.

Args:
    name: Unique name for the MCP server
    url: Base URL of the MCP server
    api_key: API key for authentication
    header_name: Header name for the API key (default: "X-API-Key")
    use_bearer_prefix: If True, prepend "Bearer " to the API key value (default: False)
    **kwargs: Additional MCPServerConfig parameters

Returns:
    MCPServerConfig instance
