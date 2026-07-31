---
type: Wiki Entity
title: ChartBlock
id: class:parrot.models.infographic.ChartBlock
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Chart specification block. Frontend renders using its preferred library.
---

# ChartBlock

Defined in [`parrot.models.infographic`](../summaries/mod:parrot.models.infographic.md).

```python
class ChartBlock(BaseModel)
```

Chart specification block. Frontend renders using its preferred library.

## Methods

- `def to_chart_config(self) -> Any` — Convert to the agnostic StructuredChartConfig shape.
- `def from_chart_config(cls, cfg: Any, **kwargs: Any) -> 'ChartBlock'` — Create a ChartBlock from an agnostic StructuredChartConfig.
