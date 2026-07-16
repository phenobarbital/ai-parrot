---
type: Wiki Entity
title: MetricAction
id: class:parrot.bots.flows.flow.actions.MetricAction
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Emit a metric.
---

# MetricAction

Defined in [`parrot.bots.flows.flow.actions`](../summaries/mod:parrot.bots.flows.flow.actions.md).

```python
class MetricAction(BaseAction)
```

Emit a metric.

This is an interface for metrics emission. The actual metric backend
(Prometheus, StatsD, etc.) is out of scope - this logs the metric.
