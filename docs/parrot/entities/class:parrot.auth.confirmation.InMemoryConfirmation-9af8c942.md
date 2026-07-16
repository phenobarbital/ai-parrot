---
type: Wiki Entity
title: InMemoryConfirmationWindowStore
id: class:parrot.auth.confirmation.InMemoryConfirmationWindowStore
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: asyncio.Lock-guarded dict-backed window store with TTL expiry.
relates_to:
- concept: class:parrot.auth.confirmation.ConfirmationWindowStore
  rel: extends
---

# InMemoryConfirmationWindowStore

Defined in [`parrot.auth.confirmation`](../summaries/mod:parrot.auth.confirmation.md).

```python
class InMemoryConfirmationWindowStore(ConfirmationWindowStore)
```

asyncio.Lock-guarded dict-backed window store with TTL expiry.

All mutations are protected by an :class:`asyncio.Lock` to prevent
TOCTOU races under concurrent tool calls.  Mirrors
:class:`InMemoryGrantStore` (grants.py:185).

Note:
    Windows are lost on process restart.  A Redis backend may follow
    (mirroring a future ``RedisGrantStore``).

## Methods

- `async def is_confirmed(self, owner_id: str, tool_name: str, args_hash: str) -> bool` — Return True only if a non-expired window exists for this call.
- `async def record(self, owner_id: str, tool_name: str, args_hash: str, *, window_seconds: int) -> None` — Record a confirmed call; noop when ``window_seconds == 0``.
