---
type: Concept
title: create_sse_mcp_server()
id: func:parrot.mcp.server.create_sse_mcp_server
tags:
- concept
timestamp: '2026-07-16T08:34:12+00:00'
summary: Create an SSE MCP server.
---

# create_sse_mcp_server

```python
def create_sse_mcp_server(name: str='ai-parrot-tools', host: str='localhost', port: int=8080, tools: Optional[List[AbstractTool]]=None, parent_app: Optional[web.Application]=None, **kwargs) -> MCPServer
```

Create an SSE MCP server.
