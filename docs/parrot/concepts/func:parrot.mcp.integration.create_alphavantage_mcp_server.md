---
type: Concept
title: create_alphavantage_mcp_server()
id: func:parrot.mcp.integration.create_alphavantage_mcp_server
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Create configuration for AlphaVantage MCP server.
---

# create_alphavantage_mcp_server

```python
def create_alphavantage_mcp_server(api_key: Optional[str]=None, name: str='alphavantage', **kwargs) -> MCPServerConfig
```

Create configuration for AlphaVantage MCP server.

Args:
    api_key: AlphaVantage API key (defaults to ALPHAVANTAGE_API_KEY env var)
    name: Server name
    **kwargs: Additional MCPServerConfig parameters

Returns:
    MCPServerConfig for AlphaVantage
