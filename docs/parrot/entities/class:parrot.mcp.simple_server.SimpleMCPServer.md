---
type: Wiki Entity
title: SimpleMCPServer
id: class:parrot.mcp.simple_server.SimpleMCPServer
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: A simplified MCP Server implementation for exposing a single tool or function.
---

# SimpleMCPServer

Defined in [`parrot.mcp.simple_server`](../summaries/mod:parrot.mcp.simple_server.md).

```python
class SimpleMCPServer
```

A simplified MCP Server implementation for exposing a single tool or function.

This class handles the boilerplate of setting up an MCP server with a specific
transport (HTTP or SSE) and authentication method, serving a single capability.

Usage:
    # Define a tool function
    @tool()
    async def my_function(x: int) -> int:
        return x * 2
        
    # Or use a class-based tool
    my_tool = MyTool()
    
    # Start the server
    server = SimpleMCPServer(
        tool=my_function,
        transport="http",
        port=8080
    )
    server.run()

## Methods

- `def register_resource(self, resource: MCPResource, handler: Callable[[str], Awaitable[str | bytes]])` — Register a resource to be served.
- `def setup(self)` — Initialize the MCP server components.
- `def run(self)` — Run the server (blocking).
- `async def start(self)` — Start the server asynchronously (for embedding).
