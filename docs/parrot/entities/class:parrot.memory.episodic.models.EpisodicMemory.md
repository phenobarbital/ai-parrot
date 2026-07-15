---
type: Wiki Entity
title: EpisodicMemory
id: class:parrot.memory.episodic.models.EpisodicMemory
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: A single episodic memory record.
---

# EpisodicMemory

Defined in [`parrot.memory.episodic.models`](../summaries/mod:parrot.memory.episodic.models.md).

```python
class EpisodicMemory(BaseModel)
```

A single episodic memory record.

Captures what the agent did, what happened, and what it learned,
with dimensional namespace fields for scoped retrieval.

## Methods

- `def searchable_text(self) -> str` — Build text for embedding generation.
- `def to_dict(self) -> dict[str, Any]` — Serialize to dict for storage.
- `def from_dict(cls, data: dict[str, Any]) -> EpisodicMemory` — Deserialize from a storage dict.
