---
type: Wiki Entity
title: ActivateMCPServerRequest
id: class:parrot.mcp.registry.ActivateMCPServerRequest
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Request body for the POST (activate) endpoint.
---

# ActivateMCPServerRequest

Defined in [`parrot.mcp.registry`](../summaries/mod:parrot.mcp.registry.md).

```python
class ActivateMCPServerRequest(BaseModel)
```

Request body for the POST (activate) endpoint.

Attributes:
    server: Registry slug of the server to activate
        (e.g. ``"perplexity"``).
    params: All parameters, including secrets.  The handler separates
        secret params before storing them in the Vault.
