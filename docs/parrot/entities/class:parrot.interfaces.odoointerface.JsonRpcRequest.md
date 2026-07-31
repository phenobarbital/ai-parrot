---
type: Wiki Entity
title: JsonRpcRequest
id: class:parrot.interfaces.odoointerface.JsonRpcRequest
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: JSON-RPC 2.0 request payload.
---

# JsonRpcRequest

Defined in [`parrot.interfaces.odoointerface`](../summaries/mod:parrot.interfaces.odoointerface.md).

```python
class JsonRpcRequest(BaseModel)
```

JSON-RPC 2.0 request payload.

Attributes:
    jsonrpc: Protocol version, always "2.0".
    method: RPC method, always "call" for Odoo.
    id: Request identifier.
    params: Service, method, and args to dispatch.
