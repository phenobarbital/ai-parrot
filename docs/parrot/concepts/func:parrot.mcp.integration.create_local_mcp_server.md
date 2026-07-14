---
type: Concept
title: create_local_mcp_server()
id: func:parrot.mcp.integration.create_local_mcp_server
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Create configuration for local stdio MCP server.
---

# create_local_mcp_server

```python
def create_local_mcp_server(name: str, script_path: Union[str, Path], interpreter: str='python', **kwargs) -> MCPServerConfig
```

Create configuration for local stdio MCP server.
