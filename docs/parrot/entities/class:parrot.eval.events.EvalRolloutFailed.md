---
type: Wiki Entity
title: EvalRolloutFailed
id: class:parrot.eval.events.EvalRolloutFailed
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Emitted when a (task, attempt) rollout raises an exception.
relates_to:
- concept: class:parrot.core.events.lifecycle.base.LifecycleEvent
  rel: extends
---

# EvalRolloutFailed

Defined in [`parrot.eval.events`](../summaries/mod:parrot.eval.events.md).

```python
class EvalRolloutFailed(LifecycleEvent)
```

Emitted when a (task, attempt) rollout raises an exception.

The run continues (model-B isolation); the failed attempt is recorded
as a failed ``EvalResult``.

Attributes:
    run_id: The parent run identifier.
    task_id: The task that failed.
    attempt: Attempt index (1-based).
    error: String representation of the exception.
