---
type: Wiki Entity
title: LoopResult
id: class:parrot_tools.computer.models.LoopResult
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Result of a loop execution.
---

# LoopResult

Defined in [`parrot_tools.computer.models`](../summaries/mod:parrot_tools.computer.models.md).

```python
class LoopResult(BaseModel)
```

Result of a loop execution.

Captures how many iterations completed, the reason the loop stopped,
per-iteration results, and any errors encountered.

Attributes:
    task_name: Name of the task that was looped.
    iterations_completed: Total number of iterations that ran.
    stop_reason: One of ``"count"``, ``"condition_met"``,
        ``"max_reached"``, ``"aborted"``, or ``"error"``.
    results: List of per-iteration TaskResult objects.
    errors: List of error messages from failed iterations.
