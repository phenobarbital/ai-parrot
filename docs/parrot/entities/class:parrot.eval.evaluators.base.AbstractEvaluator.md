---
type: Wiki Entity
title: AbstractEvaluator
id: class:parrot.eval.evaluators.base.AbstractEvaluator
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Abstract base for evaluators that combine one or more metrics.
---

# AbstractEvaluator

Defined in [`parrot.eval.evaluators.base`](../summaries/mod:parrot.eval.evaluators.base.md).

```python
class AbstractEvaluator(ABC)
```

Abstract base for evaluators that combine one or more metrics.

An ``AbstractEvaluator`` aggregates metric scores into a single
``EvalResult``.  Concrete subclasses are registered via
``@register_evaluator(name)``.

## Methods

- `async def evaluate(self, task: EvalTask, trajectory: Trajectory, sandbox: Sandbox | None=None) -> EvalResult` — Evaluate *trajectory* against *task* and return a scored result.
