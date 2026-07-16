---
type: Wiki Entity
title: ClientRegistry
id: class:parrot.mcp.oauth_server.ClientRegistry
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Minimal in-memory Dynamic Client Registration (RFC 7591) registry.
---

# ClientRegistry

Defined in [`parrot.mcp.oauth_server`](../summaries/mod:parrot.mcp.oauth_server.md).

```python
class ClientRegistry
```

Minimal in-memory Dynamic Client Registration (RFC 7591) registry.
Suitable for local development / proxy-style OAuth flows.

## Methods

- `def register(self, metadata: Dict[str, Any]) -> OAuthClient`
- `def get(self, client_id: str) -> Optional[OAuthClient]`
