---
type: Wiki Entity
title: ConfirmationWindowStore
id: class:parrot.auth.confirmation.ConfirmationWindowStore
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Abstract window persistence for the confirmation subsystem.
---

# ConfirmationWindowStore

Defined in [`parrot.auth.confirmation`](../summaries/mod:parrot.auth.confirmation.md).

```python
class ConfirmationWindowStore(ABC)
```

Abstract window persistence for the confirmation subsystem.

Mirrors :class:`GrantStore` (grants.py:114).

Key = (owner_id, tool_name, args_hash).  Implementations must be
thread-safe and support concurrent async access.

## Methods

- `async def is_confirmed(self, owner_id: str, tool_name: str, args_hash: str) -> bool` — Return True if a non-expired confirmation window covers this call.
- `async def record(self, owner_id: str, tool_name: str, args_hash: str, *, window_seconds: int) -> None` — Record a confirmed call in the window store.
