---
type: Wiki Entity
title: UIMetric
id: class:parrot.integrations.msagentsdk.semantic.UIMetric
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: A single KPI/metric entry, used by :class:`MetricsPayload`.
---

# UIMetric

Defined in [`parrot.integrations.msagentsdk.semantic`](../summaries/mod:parrot.integrations.msagentsdk.semantic.md).

```python
class UIMetric(BaseModel)
```

A single KPI/metric entry, used by :class:`MetricsPayload`.

Attributes:
    label: The metric's display label.
    value: The metric's display value.
    delta: Optional trend/delta text (e.g. ``"+5% vs last week"``).
