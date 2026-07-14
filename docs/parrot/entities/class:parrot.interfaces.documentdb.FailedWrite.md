---
type: Wiki Entity
title: FailedWrite
id: class:parrot.interfaces.documentdb.FailedWrite
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Represents a failed write operation for later retry or inspection.
---

# FailedWrite

Defined in [`parrot.interfaces.documentdb`](../summaries/mod:parrot.interfaces.documentdb.md).

```python
class FailedWrite
```

Represents a failed write operation for later retry or inspection.

Attributes:
    collection: Name of the target collection
    data: The document(s) that failed to write
    error: The exception that caused the failure
    timestamp: When the failure occurred (UTC)
    retries: Number of retry attempts made
