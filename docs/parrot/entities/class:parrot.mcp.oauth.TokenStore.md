---
type: Wiki Entity
title: TokenStore
id: class:parrot.mcp.oauth.TokenStore
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Abstract token store interface.
---

# TokenStore

Defined in [`parrot.mcp.oauth`](../summaries/mod:parrot.mcp.oauth.md).

```python
class TokenStore
```

Abstract token store interface.

## Methods

- `async def get(self, user_id: str, server_name: str) -> Optional[Dict[str, Any]]`
- `async def set(self, user_id: str, server_name: str, token: Dict[str, Any]) -> None`
- `async def delete(self, user_id: str, server_name: str) -> None`
