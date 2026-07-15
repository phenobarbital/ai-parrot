---
type: Wiki Entity
title: EvalRolloutStarted
id: class:parrot.eval.events.EvalRolloutStarted
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Emitted just before a (task, attempt) rollout begins.
relates_to:
- concept: class:parrot.core.events.lifecycle.base.LifecycleEvent
  rel: extends
---

# EvalRolloutStarted

Defined in [`parrot.eval.events`](../summaries/mod:parrot.eval.events.md).

```python
class EvalRolloutStarted(LifecycleEvent)
```

Emitted just before a (task, attempt) rollout begins.

Attributes:
    run_id: The parent run identifier.
    task_id: The task being evaluated.
    attempt: Attempt index (1-based).
