---
type: Wiki Entity
title: GrantStore
id: class:parrot.auth.grants.GrantStore
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Abstract interface for grant persistence.
---

# GrantStore

Defined in [`parrot.auth.grants`](../summaries/mod:parrot.auth.grants.md).

```python
class GrantStore(ABC)
```

Abstract interface for grant persistence.

Implementations must be thread-safe and support concurrent async access.
The in-memory implementation uses asyncio.Lock; a Redis backend can use
atomic operations.

## Methods

- `async def grant(self, owner_id: str, scope: str, *, granted_by: str, window_seconds: int) -> Grant` — Create and store a new grant.
- `async def is_allowed(self, owner_id: str, scope: str) -> bool` — Check whether there is an active grant covering (owner, scope).
- `async def revoke(self, grant_id: str) -> bool` — Revoke a grant immediately.
- `async def list_active(self, owner_id: str) -> list[Grant]` — List all active (non-expired, non-revoked) grants for an owner.
