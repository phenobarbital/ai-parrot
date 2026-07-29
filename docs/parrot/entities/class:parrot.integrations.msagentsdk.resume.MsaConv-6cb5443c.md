---
type: Wiki Entity
title: MsaConversationRefStore
id: class:parrot.integrations.msagentsdk.resume.MsaConversationRefStore
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Async store for :class:`MsaConversationReference` records.
---

# MsaConversationRefStore

Defined in [`parrot.integrations.msagentsdk.resume`](../summaries/mod:parrot.integrations.msagentsdk.resume.md).

```python
class MsaConversationRefStore
```

Async store for :class:`MsaConversationReference` records.

Supports lookup by **nonce** (for static-key capture callback) and by
**user_id** (for OAuth/OBO signin invokes where no nonce is available).

Redis key format:
    - ``msasdk:convref:nonce:{nonce}``  → JSON-serialised reference
    - ``msasdk:convref:user:{user_id}`` → nonce string (pointer)

Falls back to an in-memory dict when ``redis=None`` (unit tests / local dev).

Args:
    redis: An async Redis client with ``setex`` / ``get`` / ``delete``
        coroutine methods. Pass ``None`` for the in-memory fallback.

## Methods

- `async def save(self, ref: MsaConversationReference, ttl: int=_DEFAULT_TTL) -> None` — Persist a conversation reference under both nonce and user_id keys.
- `async def load_by_nonce(self, nonce: str) -> Optional[MsaConversationReference]` — Load a conversation reference by nonce.
- `async def load_by_user(self, user_id: str) -> Optional[MsaConversationReference]` — Load a conversation reference by canonical user_id.
- `async def delete(self, ref: MsaConversationReference) -> None` — Remove both keys for a conversation reference.
