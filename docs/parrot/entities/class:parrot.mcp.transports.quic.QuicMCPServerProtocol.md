---
type: Wiki Entity
title: QuicMCPServerProtocol
id: class:parrot.mcp.transports.quic.QuicMCPServerProtocol
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: QUIC protocol handler for MCP server connections.
---

# QuicMCPServerProtocol

Defined in [`parrot.mcp.transports.quic`](../summaries/mod:parrot.mcp.transports.quic.md).

```python
class QuicMCPServerProtocol(QuicConnectionProtocol)
```

QUIC protocol handler for MCP server connections.

Handles:
- HTTP/3 requests
- WebTransport sessions
- Unreliable datagrams for telemetry

## Methods

- `def quic_event_received(self, event: QuicEvent) -> None` — Handle QUIC-level events.
