---
type: Wiki Summary
title: parrot.mcp.server
id: mod:parrot.mcp.server
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: MCP Server Implementation - Expose AI-Parrot Tools via MCP Protocol
relates_to:
- concept: class:parrot.mcp.server.MCPServer
  rel: defines
- concept: func:parrot.mcp.server.create_http_mcp_server
  rel: defines
- concept: func:parrot.mcp.server.create_sse_mcp_server
  rel: defines
- concept: func:parrot.mcp.server.create_stdio_mcp_server
  rel: defines
- concept: func:parrot.mcp.server.create_unix_mcp_server
  rel: defines
- concept: func:parrot.mcp.server.main
  rel: defines
- concept: mod:parrot.mcp.config
  rel: references
- concept: mod:parrot.mcp.transports.http
  rel: references
- concept: mod:parrot.mcp.transports.quic
  rel: references
- concept: mod:parrot.mcp.transports.sse
  rel: references
- concept: mod:parrot.mcp.transports.stdio
  rel: references
- concept: mod:parrot.mcp.transports.unix
  rel: references
- concept: mod:parrot.tools.abstract
  rel: references
---

# `parrot.mcp.server`

MCP Server Implementation - Expose AI-Parrot Tools via MCP Protocol
=================================================================
This creates an MCP server that exposes your existing AbstractTool instances
as MCP tools that can be consumed by any MCP client.

## Classes

- **`MCPServer`** — Main MCP server class that chooses transport.

## Functions

- `def create_stdio_mcp_server(name: str='ai-parrot-tools', tools: Optional[List[AbstractTool]]=None, **kwargs) -> MCPServer` — Create a stdio MCP server.
- `def create_http_mcp_server(name: str='ai-parrot-tools', host: str='localhost', port: int=8080, tools: Optional[List[AbstractTool]]=None, parent_app: Optional[web.Application]=None, **kwargs) -> MCPServer` — Create an HTTP MCP server.
- `def create_sse_mcp_server(name: str='ai-parrot-tools', host: str='localhost', port: int=8080, tools: Optional[List[AbstractTool]]=None, parent_app: Optional[web.Application]=None, **kwargs) -> MCPServer` — Create an SSE MCP server.
- `def create_unix_mcp_server(name: str='ai-parrot-tools', socket_path: Optional[str]=None, tools: Optional[List[AbstractTool]]=None, **kwargs) -> MCPServer` — Create an Unix MCP server.
- `async def main()` — Main CLI entry point.
