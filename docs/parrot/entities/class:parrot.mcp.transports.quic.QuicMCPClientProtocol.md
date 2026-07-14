---
type: Wiki Entity
title: QuicMCPClientProtocol
id: class:parrot.mcp.transports.quic.QuicMCPClientProtocol
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: QUIC protocol handler for MCP client connections.
---

# QuicMCPClientProtocol

Defined in [`parrot.mcp.transports.quic`](../summaries/mod:parrot.mcp.transports.quic.md).

```python
class QuicMCPClientProtocol(QuicConnectionProtocol)
```

QUIC protocol handler for MCP client connections.

## Methods

- `def quic_event_received(self, event: QuicEvent)` — Handle QUIC-level events.
