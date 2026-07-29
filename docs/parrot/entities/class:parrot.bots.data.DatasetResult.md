---
type: Wiki Entity
title: DatasetResult
id: class:parrot.bots.data.DatasetResult
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: A single named dataset in a multi-dataset response.
---

# DatasetResult

Defined in [`parrot.bots.data`](../summaries/mod:parrot.bots.data.md).

```python
class DatasetResult(BaseModel)
```

A single named dataset in a multi-dataset response.

Used when a query involves multiple datasources and ``PandasAgentResponse``
needs to return more than one result table.
