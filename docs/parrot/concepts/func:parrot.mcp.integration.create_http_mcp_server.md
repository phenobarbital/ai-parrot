---
type: Concept
title: create_http_mcp_server()
id: func:parrot.mcp.integration.create_http_mcp_server
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Create configuration for HTTP MCP server.
---

# create_http_mcp_server

```python
def create_http_mcp_server(name: str, url: str, auth_type: Optional[str]=None, auth_config: Optional[Dict[str, Any]]=None, headers: Optional[Dict[str, str]]=None, **kwargs) -> MCPServerConfig
```

Create configuration for HTTP MCP server.
