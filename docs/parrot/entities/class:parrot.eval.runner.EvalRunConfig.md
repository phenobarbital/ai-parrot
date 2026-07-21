---
type: Wiki Entity
title: EvalRunConfig
id: class:parrot.eval.runner.EvalRunConfig
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Configuration for a single evaluation run.
---

# EvalRunConfig

Defined in [`parrot.eval.runner`](../summaries/mod:parrot.eval.runner.md).

```python
class EvalRunConfig(BaseModel)
```

Configuration for a single evaluation run.

Attributes:
    k: Number of attempts per task.  ``pass^k`` = all-k-pass fraction.
        Use ``k=1`` locally; ``k=4`` for CI release gates.
    max_concurrency: Maximum concurrent (task, attempt) pairs.
    sandbox_pool_size: Pool size for pooled sandboxes (e.g. Docker).
        Not used for ``InMemoryStateSandbox`` (always fresh per attempt).
    fail_fast: Stop the run on the first failed task.
    seed: Optional RNG seed for task ordering and user simulator.
        Best-effort; does not guarantee agent output determinism.
