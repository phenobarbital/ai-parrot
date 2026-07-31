---
type: Wiki Entity
title: QuicMCPSession
id: class:parrot.mcp.transports.quic.QuicMCPSession
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: MCP session over QUIC/HTTP3 with WebTransport.
---

# QuicMCPSession

Defined in [`parrot.mcp.transports.quic`](../summaries/mod:parrot.mcp.transports.quic.md).

```python
class QuicMCPSession
```

MCP session over QUIC/HTTP3 with WebTransport.

Features:
- 0-RTT connection for minimal latency
- Multiplexed streams for concurrent tool calls
- Binary serialization (MessagePack) for efficiency
- Unreliable datagrams for telemetry
- Connection migration support

Example:
    >>> config = QuicMCPConfig(
    ...     host="tools.example.com",
    ...     port=4433,
    ...     serialization=SerializationFormat.MSGPACK,
    ... )
    >>> session = QuicMCPSession(mcp_config, logger)
    >>> await session.connect()
    >>> tools = await session.list_tools()
    >>> result = await session.call_tool("search", {"query": "AI agents"})

## Methods

- `async def connect(self)` — Establish QUIC connection to MCP server.
- `async def send_request(self, method: str, params: Optional[Dict]=None, timeout: float=30.0) -> Dict[str, Any]` — Send JSON-RPC request over QUIC stream.
- `async def send_notification(self, method: str, params: Optional[Dict]=None)` — Send one-way notification (no response expected).
- `def send_telemetry(self, data: bytes)` — Send unreliable telemetry via datagram.
- `async def list_tools(self) -> List[Dict]` — List available tools from MCP server.
- `async def call_tool(self, name: str, arguments: Dict) -> Dict` — Call a tool on the MCP server.
- `async def disconnect(self)` — Disconnect from MCP server.
- `def is_connected(self) -> bool`
