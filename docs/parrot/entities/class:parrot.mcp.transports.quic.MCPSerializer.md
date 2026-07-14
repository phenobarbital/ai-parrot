---
type: Wiki Entity
title: MCPSerializer
id: class:parrot.mcp.transports.quic.MCPSerializer
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Handles serialization/deserialization of MCP messages.
---

# MCPSerializer

Defined in [`parrot.mcp.transports.quic`](../summaries/mod:parrot.mcp.transports.quic.md).

```python
class MCPSerializer
```

Handles serialization/deserialization of MCP messages.

## Methods

- `def serialize(self, message: Dict[str, Any]) -> bytes` — Serialize MCP message to bytes.
- `def deserialize(self, data: bytes) -> Dict[str, Any]` — Deserialize bytes to MCP message.
- `def content_type(self) -> str` — MIME type for the serialization format.
