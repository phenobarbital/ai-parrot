---
type: Wiki Entity
title: FilterCondition
id: class:parrot.tools.dataset_manager.filtering.contracts.FilterCondition
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: A single applied condition within a filter request.
---

# FilterCondition

Defined in [`parrot.tools.dataset_manager.filtering.contracts`](../summaries/mod:parrot.tools.dataset_manager.filtering.contracts.md).

```python
class FilterCondition(BaseModel)
```

A single applied condition within a filter request.

Attributes:
    op: The filter operator to apply.
    value: The operand — scalar, list, ``{"min": ..., "max": ...}`` dict
        for ``range``, or radius specification for ``radius``.
