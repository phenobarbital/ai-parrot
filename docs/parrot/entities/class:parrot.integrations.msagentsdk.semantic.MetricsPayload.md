---
type: Wiki Entity
title: MetricsPayload
id: class:parrot.integrations.msagentsdk.semantic.MetricsPayload
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: A metrics/KPI result payload.
---

# MetricsPayload

Defined in [`parrot.integrations.msagentsdk.semantic`](../summaries/mod:parrot.integrations.msagentsdk.semantic.md).

```python
class MetricsPayload(BaseModel)
```

A metrics/KPI result payload.

Attributes:
    result_type: Discriminator, always ``"metrics"``.
    metrics: The list of metrics to render.
