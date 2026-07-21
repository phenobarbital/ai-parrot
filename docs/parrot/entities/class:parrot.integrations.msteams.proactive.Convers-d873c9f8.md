---
type: Wiki Entity
title: ConversationReferenceStore
id: class:parrot.integrations.msteams.proactive.ConversationReferenceStore
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Redis-backed store for Bot Framework ``ConversationReference`` objects.
---

# ConversationReferenceStore

Defined in [`parrot.integrations.msteams.proactive`](../summaries/mod:parrot.integrations.msteams.proactive.md).

```python
class ConversationReferenceStore
```

Redis-backed store for Bot Framework ``ConversationReference`` objects.

Keys: ``hitl:teams:convref:{email}`` → JSON-serialised
``ConversationReference``.

The TTL is refreshed on every inbound activity (cache-on-contact, OQ-4)
and the ``service_url`` is updated at the same time so proactive sends
always use a fresh, trusted URL.

Args:
    redis: An async Redis client (e.g. ``redis.asyncio.Redis``).
    ttl: Cache TTL in seconds (default: 30 days).

## Methods

- `async def get(self, email: str) -> Optional[ConversationReference]` — Return a cached ``ConversationReference``, or ``None`` on miss.
- `async def set(self, email: str, ref: ConversationReference, service_url: Optional[str]=None) -> None` — Store (or refresh) a ``ConversationReference``.
- `async def refresh(self, email: str, service_url: Optional[str]=None) -> None` — Refresh TTL (and optionally service_url) for an existing entry.
