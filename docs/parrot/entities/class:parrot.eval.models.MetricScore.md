---
type: Wiki Entity
title: MetricScore
id: class:parrot.eval.models.MetricScore
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Score for a single metric on one attempt.
---

# MetricScore

Defined in [`parrot.eval.models`](../summaries/mod:parrot.eval.models.md).

```python
class MetricScore(BaseModel)
```

Score for a single metric on one attempt.

Attributes:
    name: Metric name (e.g. ``"state_match"``).
    value: Normalized score in ``[0.0, 1.0]``; binary metrics use 0.0
        or 1.0.
    passed: Whether the metric threshold was met, when applicable.
    detail: Additional scoring detail (mismatches, forbidden entities, …).
