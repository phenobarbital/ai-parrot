---
type: Wiki Entity
title: EvalDataset
id: class:parrot.eval.models.EvalDataset
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: A named collection of evaluation tasks.
---

# EvalDataset

Defined in [`parrot.eval.models`](../summaries/mod:parrot.eval.models.md).

```python
class EvalDataset(BaseModel)
```

A named collection of evaluation tasks.

Attributes:
    name: Human-readable dataset name (used in reports and baselines).
    tasks: Ordered list of tasks to evaluate.
