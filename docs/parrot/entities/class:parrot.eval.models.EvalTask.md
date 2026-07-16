---
type: Wiki Entity
title: EvalTask
id: class:parrot.eval.models.EvalTask
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: A single evaluation task (input + ground-truth expectation).
---

# EvalTask

Defined in [`parrot.eval.models`](../summaries/mod:parrot.eval.models.md).

```python
class EvalTask(BaseModel)
```

A single evaluation task (input + ground-truth expectation).

Frozen so that dataset records are immutable after construction.
``sandbox_spec`` uses a forward reference resolved once
``SandboxSpec`` is importable.

Attributes:
    task_id: Unique identifier for the task.
    inputs: Free-form input dict passed to the agent.
    expected: Gold answer / goal state / test command (eval-type specific).
    sandbox_spec: Optional sandbox configuration for this task.
    user_scenario: Natural language scenario for the LLM user simulator.
    tags: Grouping labels for per-tag aggregation in the report.
    metadata: Arbitrary metadata attached to the task record.
