---
type: Wiki Entity
title: ChatMessage
id: class:parrot.storage.models.ChatMessage
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: 'Represents a single chat message (one direction: user OR assistant).'
---

# ChatMessage

Defined in [`parrot.storage.models`](../summaries/mod:parrot.storage.models.md).

```python
class ChatMessage
```

Represents a single chat message (one direction: user OR assistant).

This is the atomic persistence unit — one document per message in
DocumentDB and one entry per message in the Redis turn list.

## Methods

- `def to_dict(self) -> Dict[str, Any]` — Serialize to dictionary suitable for DocumentDB storage.
- `def from_dict(cls, data: Dict[str, Any]) -> 'ChatMessage'` — Deserialize from dictionary.
