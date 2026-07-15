---
type: Wiki Entity
title: PaginatedResponse
id: class:parrot.handlers.crew.models.PaginatedResponse
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Paginated list response.
---

# PaginatedResponse

Defined in [`parrot.handlers.crew.models`](../summaries/mod:parrot.handlers.crew.models.md).

```python
class PaginatedResponse(BaseModel)
```

Paginated list response.

Attributes:
    items: Page of execution summaries.
    total: Total number of matching records (ignoring pagination).
    limit: Page size used for this response.
    offset: Number of records skipped before this page.
