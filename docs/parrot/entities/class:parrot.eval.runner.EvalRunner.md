---
type: Wiki Entity
title: EvalRunner
id: class:parrot.eval.runner.EvalRunner
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Orchestrates an evaluation run across all tasks in a dataset.
---

# EvalRunner

Defined in [`parrot.eval.runner`](../summaries/mod:parrot.eval.runner.md).

```python
class EvalRunner
```

Orchestrates an evaluation run across all tasks in a dataset.

Each (task, attempt) pair is executed under a ``asyncio.Semaphore``
with bound concurrency.  ``pass^k`` and ``pass@1`` are computed from
the aggregated results.

Args:
    dataset: The ``EvalDataset`` to evaluate.
    agent_factory: Callable that receives a ``Sandbox`` and returns a
        bound ``AbstractBot`` instance (fresh per attempt).
    rollout: ``RolloutStrategy`` to drive the agent.
    evaluator: ``AbstractEvaluator`` to score the trajectory.
    sandbox_provider: ``SandboxProvider`` that acquires sandboxes.
    config: ``EvalRunConfig`` controlling concurrency and ``k``.
    event_bus: Optional ``EventBus`` for lifecycle events (TASK-1426).
    sink: Optional ``EvalReportSink`` for persistence (TASK-1427).

## Methods

- `async def run(self) -> EvalReport` — Execute the full evaluation run.
