---
type: Wiki Entity
title: GrpcMCPSession
id: class:parrot.mcp.transports.grpc_session.GrpcMCPSession
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: MCP session for gRPC transport with optional protobuf messages.
---

# GrpcMCPSession

Defined in [`parrot.mcp.transports.grpc_session`](../summaries/mod:parrot.mcp.transports.grpc_session.md).

```python
class GrpcMCPSession
```

MCP session for gRPC transport with optional protobuf messages.

## Methods

- `async def connect(self)` — Connect to MCP server via gRPC.
- `async def send_request(self, method: str, params: Dict=None) -> Dict[str, Any]` — Send JSON-RPC request over gRPC.
- `async def list_tools(self) -> list` — List available tools.
- `async def call_tool(self, name: str, arguments: Dict) -> Dict` — Call a tool.
- `async def disconnect(self)` — Disconnect from gRPC server.
