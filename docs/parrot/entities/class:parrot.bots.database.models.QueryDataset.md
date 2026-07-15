---
type: Wiki Entity
title: QueryDataset
id: class:parrot.bots.database.models.QueryDataset
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Result dataset for a single executed query.
---

# QueryDataset

Defined in [`parrot.bots.database.models`](../summaries/mod:parrot.bots.database.models.md).

```python
class QueryDataset(BaseModel)
```

Result dataset for a single executed query.

Wraps PandasTable with DB-specific metadata so consumers can
distinguish a 'no results' empty table from a non-tabular response.
