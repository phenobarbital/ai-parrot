---
type: Wiki Entity
title: EphemeralRegistry
id: class:parrot.manager.ephemeral.EphemeralRegistry
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: In-memory registry of active ephemeral bots.
---

# EphemeralRegistry

Defined in [`parrot.manager.ephemeral`](../summaries/mod:parrot.manager.ephemeral.md).

```python
class EphemeralRegistry
```

In-memory registry of active ephemeral bots.

Thread-safe enough for a single asyncio event loop: mutations are
protected by a ``asyncio.Lock`` to prevent TOCTOU races between the
warm-up background task and concurrent HTTP requests.

The registry is intentionally not persistent — entries live only in
process memory and vanish on restart.

The lock is created lazily (FIX-5) so it is always initialised inside
a running event loop, avoiding deprecation warnings on Python 3.10+.

## Methods

- `async def register(self, status: EphemeralAgentStatus) -> None` — Insert or replace a status entry (keyed by chatbot_id).
- `def get(self, chatbot_id: str, user_id: Optional[int]=None, *, owner_id: Optional[str]=None) -> Optional[EphemeralAgentStatus]` — Return the status if it exists and belongs to the given owner.
- `def get_all_for_user(self, user_id: int) -> List[EphemeralAgentStatus]` — Return all entries owned by the human user *user_id*.
- `async def remove(self, chatbot_id: str) -> bool` — Delete the registry entry for *chatbot_id*.
- `def get_expired(self) -> List[str]` — Return chatbot_ids whose ``expires_at`` is in the past.
- `def snapshot(self) -> Dict[str, EphemeralAgentStatus]` — Return a shallow copy of the current store (safe for iteration).
