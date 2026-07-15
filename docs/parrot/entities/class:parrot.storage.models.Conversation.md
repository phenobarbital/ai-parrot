---
type: Wiki Entity
title: Conversation
id: class:parrot.storage.models.Conversation
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Conversation metadata — one document per session in DocumentDB.
---

# Conversation

Defined in [`parrot.storage.models`](../summaries/mod:parrot.storage.models.md).

```python
class Conversation
```

Conversation metadata — one document per session in DocumentDB.

Tracks the lifecycle of a conversation session: when it started,
when the last message was sent, token counts, title, etc.

## Methods

- `def to_dict(self) -> Dict[str, Any]` — Serialize to dictionary suitable for DocumentDB storage.
- `def from_dict(cls, data: Dict[str, Any]) -> 'Conversation'` — Deserialize from dictionary.
