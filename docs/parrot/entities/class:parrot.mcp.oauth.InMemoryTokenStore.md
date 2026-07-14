---
type: Wiki Entity
title: InMemoryTokenStore
id: class:parrot.mcp.oauth.InMemoryTokenStore
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Simple in-memory token store (not persistent).
relates_to:
- concept: class:parrot.mcp.oauth.TokenStore
  rel: extends
---

# InMemoryTokenStore

Defined in [`parrot.mcp.oauth`](../summaries/mod:parrot.mcp.oauth.md).

```python
class InMemoryTokenStore(TokenStore)
```

Simple in-memory token store (not persistent).

## Methods

- `async def get(self, user_id, server_name)`
- `async def set(self, user_id, server_name, token)`
- `async def delete(self, user_id, server_name)`
