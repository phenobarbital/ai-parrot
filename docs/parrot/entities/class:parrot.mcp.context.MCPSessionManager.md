---
type: Wiki Entity
title: MCPSessionManager
id: class:parrot.mcp.context.MCPSessionManager
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Manages session lifecycle and retry logic for MCP connections.
---

# MCPSessionManager

Defined in [`parrot.mcp.context`](../summaries/mod:parrot.mcp.context.md).

```python
class MCPSessionManager
```

Manages session lifecycle and retry logic for MCP connections.

Features:
- Session caching keyed by headers (for multi-user scenarios)
- Automatic retry with exponential backoff on transient failures
- Configurable max retries

Example:
    >>> manager = MCPSessionManager(config, max_retries=3)
    >>> session = await manager.create_session(headers={"X-User-ID": "123"})
    >>> # Session is cached - same headers return same session
    >>> same_session = await manager.create_session(headers={"X-User-ID": "123"})

## Methods

- `async def create_session(self, headers: Optional[Dict[str, str]]=None, force_new: bool=False) -> Any` — Create or retrieve cached session with retry.
- `async def invalidate_session(self, headers: Optional[Dict[str, str]]=None) -> None` — Invalidate a cached session.
- `async def invalidate_all(self) -> None` — Invalidate all cached sessions.
