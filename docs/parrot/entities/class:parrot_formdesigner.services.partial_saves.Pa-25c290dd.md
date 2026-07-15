---
type: Wiki Entity
title: PartialSaveStore
id: class:parrot_formdesigner.services.partial_saves.PartialSaveStore
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Redis-backed ephemeral storage for partial form answers.
---

# PartialSaveStore

Defined in [`parrot_formdesigner.services.partial_saves`](../summaries/mod:parrot_formdesigner.services.partial_saves.md).

```python
class PartialSaveStore
```

Redis-backed ephemeral storage for partial form answers.

Each save merges the new answers over any cached answers (last-write-wins)
and refreshes the TTL for the entire entry.  Different ``session_id`` values
produce independent cache entries, ensuring session isolation.

If no ``redis_url`` is provided (or Redis is unavailable), the service
operates in a no-op mode: ``save()`` returns the merged state without
persisting it, ``get()`` returns ``None``, and ``delete()`` returns
``False``.  This allows callers to handle graceful degradation.

Args:
    ttl_seconds: Time-to-live in seconds for cached entries. Default: 3600
        (1 hour). Each ``save()`` call refreshes the TTL.
    redis_url: Optional Redis connection URL, e.g.
        ``"redis://localhost:6379"``.  If ``None``, Redis is not used.

Example:
    store = PartialSaveStore(ttl_seconds=3600, redis_url="redis://localhost")
    partial = await store.save("my-form", "session-abc", {"name": "Alice"})
    cached = await store.get("my-form", "session-abc")
    await store.delete("my-form", "session-abc")
    await store.close()

## Methods

- `async def save(self, form_id: str, session_id: str, answers: dict[str, Any]) -> PartialFormData` — Merge answers into the cached partial and return the updated state.
- `async def get(self, form_id: str, session_id: str) -> PartialFormData | None` — Retrieve cached partial answers.
- `async def delete(self, form_id: str, session_id: str) -> bool` — Remove cached partial answers.
- `async def close(self) -> None` — Close the Redis connection if open.
