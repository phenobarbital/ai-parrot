---
type: Concept
title: create_unix_mcp_server()
id: func:parrot.mcp.server.create_unix_mcp_server
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Create an Unix MCP server.
---

# create_unix_mcp_server

```python
def create_unix_mcp_server(name: str='ai-parrot-tools', socket_path: Optional[str]=None, tools: Optional[List[AbstractTool]]=None, **kwargs) -> MCPServer
```

Create an Unix MCP server.
