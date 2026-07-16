---
type: Wiki Entity
title: RedisTokenStore
id: class:parrot.mcp.oauth.RedisTokenStore
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Redis-based token store.
relates_to:
- concept: class:parrot.mcp.oauth.TokenStore
  rel: extends
---

# RedisTokenStore

Defined in [`parrot.mcp.oauth`](../summaries/mod:parrot.mcp.oauth.md).

```python
class RedisTokenStore(TokenStore)
```

Redis-based token store.

## Methods

- `async def get(self, user_id, server_name)`
- `async def set(self, user_id, server_name, token)`
- `async def delete(self, user_id, server_name)`
