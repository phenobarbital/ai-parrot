---
type: Wiki Entity
title: DatasetQueryRequest
id: class:parrot.models.datasets.DatasetQueryRequest
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Request model for POST /datasets/{agent_id} (add query).
---

# DatasetQueryRequest

Defined in [`parrot.models.datasets`](../summaries/mod:parrot.models.datasets.md).

```python
class DatasetQueryRequest(BaseModel)
```

Request model for POST /datasets/{agent_id} (add query).

Used to add a new dataset based on a SQL query or a predefined query slug.
Exactly one of `query` or `query_slug` must be provided.

## Methods

- `def validate_query_source(self) -> None` — Ensure exactly one of query, query_slug, or datasource is provided.
