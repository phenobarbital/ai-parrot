---
type: Wiki Entity
title: JoinSpec
id: class:parrot.tools.dataset_manager.sources.composite.JoinSpec
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Specification for joining two datasets.
---

# JoinSpec

Defined in [`parrot.tools.dataset_manager.sources.composite`](../summaries/mod:parrot.tools.dataset_manager.sources.composite.md).

```python
class JoinSpec(BaseModel)
```

Specification for joining two datasets.

Attributes:
    left: Left dataset name (must be registered in DatasetManager).
    right: Right dataset name (must be registered in DatasetManager).
    on: Column name(s) used as join key(s).
    how: Join type — one of ``"inner"``, ``"left"``, ``"right"``,
        ``"outer"``.
    suffixes: Tuple of suffixes appended to overlapping columns from
        left and right respectively.
