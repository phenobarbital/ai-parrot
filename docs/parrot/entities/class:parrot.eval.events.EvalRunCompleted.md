---
type: Wiki Entity
title: EvalRunCompleted
id: class:parrot.eval.events.EvalRunCompleted
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Emitted when ``EvalRunner.run()`` finishes (whether or not all tasks
relates_to:
- concept: class:parrot.core.events.lifecycle.base.LifecycleEvent
  rel: extends
---

# EvalRunCompleted

Defined in [`parrot.eval.events`](../summaries/mod:parrot.eval.events.md).

```python
class EvalRunCompleted(LifecycleEvent)
```

Emitted when ``EvalRunner.run()`` finishes (whether or not all tasks
passed).

Attributes:
    run_id: Unique identifier for the evaluation run.
    dataset_name: Name of the evaluated dataset.
    pass_k: ``pass^k`` headline metric (fraction of tasks where all k
        attempts passed).  ``None`` if no tasks were evaluated.
    pass_at_1: Mean of attempt-1 pass flags.  ``None`` if no results.
    total_tasks: Total number of tasks.
    total_attempts: Total number of (task, attempt) pairs executed.
