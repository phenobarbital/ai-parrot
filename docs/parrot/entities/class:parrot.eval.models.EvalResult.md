---
type: Wiki Entity
title: EvalResult
id: class:parrot.eval.models.EvalResult
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Evaluation outcome for a single (task, attempt) pair.
---

# EvalResult

Defined in [`parrot.eval.models`](../summaries/mod:parrot.eval.models.md).

```python
class EvalResult(BaseModel)
```

Evaluation outcome for a single (task, attempt) pair.

Attributes:
    task_id: ID of the evaluated task.
    attempt: Attempt index this result covers.
    scores: Per-metric scores.
    passed: Aggregate pass/fail: ``True`` iff all metrics passed.
    trajectory: The trajectory used to produce this result.
