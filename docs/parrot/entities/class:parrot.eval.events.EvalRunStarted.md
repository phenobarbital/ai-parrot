---
type: Wiki Entity
title: EvalRunStarted
id: class:parrot.eval.events.EvalRunStarted
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Emitted when ``EvalRunner.run()`` begins.
relates_to:
- concept: class:parrot.core.events.lifecycle.base.LifecycleEvent
  rel: extends
---

# EvalRunStarted

Defined in [`parrot.eval.events`](../summaries/mod:parrot.eval.events.md).

```python
class EvalRunStarted(LifecycleEvent)
```

Emitted when ``EvalRunner.run()`` begins.

Attributes:
    run_id: Unique identifier for the evaluation run.
    dataset_name: Name of the dataset being evaluated.
    k: Number of attempts configured per task.
    total_tasks: Number of tasks in the dataset.
