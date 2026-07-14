---
type: Wiki Entity
title: DatasetInfo
id: class:parrot.tools.dataset_manager.tool.DatasetInfo
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Schema for dataset information exposed to LLM.
---

# DatasetInfo

Defined in [`parrot.tools.dataset_manager.tool`](../summaries/mod:parrot.tools.dataset_manager.tool.md).

```python
class DatasetInfo(BaseModel)
```

Schema for dataset information exposed to LLM.

Schema fields (columns, column_types) are available even when the dataset
is not yet loaded — for TableSource entries whose schema was prefetched.
