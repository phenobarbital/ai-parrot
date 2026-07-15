---
type: Wiki Entity
title: JsonRpcResponse
id: class:parrot.interfaces.odoointerface.JsonRpcResponse
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: JSON-RPC 2.0 response payload.
---

# JsonRpcResponse

Defined in [`parrot.interfaces.odoointerface`](../summaries/mod:parrot.interfaces.odoointerface.md).

```python
class JsonRpcResponse(BaseModel)
```

JSON-RPC 2.0 response payload.

Attributes:
    jsonrpc: Protocol version.
    id: Request identifier matching the request.
    result: Successful result payload (None if error).
    error: Error details dict (None on success).
