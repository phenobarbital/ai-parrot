---
type: Wiki Entity
title: Metric
id: class:parrot.eval.evaluators.base.Metric
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Abstract base for a single evaluation metric.
---

# Metric

Defined in [`parrot.eval.evaluators.base`](../summaries/mod:parrot.eval.evaluators.base.md).

```python
class Metric(ABC)
```

Abstract base for a single evaluation metric.

A ``Metric`` computes a normalized score for one (task, trajectory) pair.
Concrete subclasses are registered via ``@register_metric(name)`` and
stored in the metric registry.

Attributes:
    name: Registry name of this metric (e.g. ``"state_match"``).

## Methods

- `async def score(self, task: EvalTask, trajectory: Trajectory, sandbox: Sandbox | None=None) -> MetricScore` — Compute a metric score for *trajectory* on *task*.
