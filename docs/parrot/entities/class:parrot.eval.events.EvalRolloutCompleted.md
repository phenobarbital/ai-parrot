---
type: Wiki Entity
title: EvalRolloutCompleted
id: class:parrot.eval.events.EvalRolloutCompleted
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Emitted after a (task, attempt) rollout completes successfully.
relates_to:
- concept: class:parrot.core.events.lifecycle.base.LifecycleEvent
  rel: extends
---

# EvalRolloutCompleted

Defined in [`parrot.eval.events`](../summaries/mod:parrot.eval.events.md).

```python
class EvalRolloutCompleted(LifecycleEvent)
```

Emitted after a (task, attempt) rollout completes successfully.

Attributes:
    run_id: The parent run identifier.
    task_id: The evaluated task.
    attempt: Attempt index (1-based).
    passed: Whether the evaluator marked this attempt as passed.
    latency_ms: Rollout wall-clock time in milliseconds.
    setup_latency_ms: Agent setup time in milliseconds.
