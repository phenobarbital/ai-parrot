---
type: Wiki Entity
title: InMemoryGrantStore
id: class:parrot.auth.grants.InMemoryGrantStore
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Dict-backed grant store with TTL expiry and periodic cleanup.
relates_to:
- concept: class:parrot.auth.grants.GrantStore
  rel: extends
---

# InMemoryGrantStore

Defined in [`parrot.auth.grants`](../summaries/mod:parrot.auth.grants.md).

```python
class InMemoryGrantStore(GrantStore)
```

Dict-backed grant store with TTL expiry and periodic cleanup.

All mutations are protected by an asyncio.Lock to prevent TOCTOU races
under concurrent tool calls.

Note:
    Grants are lost on process restart. Persistence is a future concern
    tied to the event ledger (FEAT-212).

Note:
    ``cleanup()`` removes stale grants but has no built-in scheduler.
    Callers are responsible for invoking it periodically (e.g. on a
    background task or before long-running operations) to bound memory
    growth. A future Redis-backed store will use TTL natively and not
    require explicit cleanup.

## Methods

- `async def grant(self, owner_id: str, scope: str, *, granted_by: str, window_seconds: int) -> Grant` — Create and store a new grant with a fixed expiry window.
- `async def is_allowed(self, owner_id: str, scope: str) -> bool` — Check whether there is an active grant covering (owner, scope).
- `async def revoke(self, grant_id: str) -> bool` — Revoke a grant immediately by marking it revoked.
- `async def list_active(self, owner_id: str) -> list[Grant]` — List all active grants for an owner.
- `async def cleanup(self) -> int` — Remove expired and revoked grants from memory.
