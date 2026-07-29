---
type: Wiki Entity
title: ThreadMetadata
id: class:parrot.storage.models.ThreadMetadata
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Conversation thread metadata stored in DynamoDB.
---

# ThreadMetadata

Defined in [`parrot.storage.models`](../summaries/mod:parrot.storage.models.md).

```python
class ThreadMetadata(BaseModel)
```

Conversation thread metadata stored in DynamoDB.

This is a *new* Pydantic model — it does NOT replace the existing
``Conversation`` dataclass which is used by the DocumentDB path.
