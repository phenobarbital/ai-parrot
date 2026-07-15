---
type: Wiki Entity
title: StructuredTableConfig
id: class:parrot.models.outputs.StructuredTableConfig
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Framework-agnostic table configuration for FEAT-218.
---

# StructuredTableConfig

Defined in [`parrot.models.outputs`](../summaries/mod:parrot.models.outputs.md).

```python
class StructuredTableConfig(BaseModel)
```

Framework-agnostic table configuration for FEAT-218.

Accepts data rows on input (for column-name validation), but the renderer
excludes the ``data`` field from the serialized output — rows are routed
to ``response.data`` instead (mirroring ``StructuredChartConfig``).

Attributes:
    columns: Per-column contract list (name / type / title / optional format).
    data: Flat row list — INPUT-ONLY; excluded from ``output``,
        routed to ``response.data`` by the renderer.
    explanation: Optional prose description of how the table was derived
        (reused from the producing agent; absent → omitted).
    total_rows: Total number of rows before truncation (set when data
        originates from a larger dataset).
    truncated: ``True`` when the dataset was capped at ``row_limit``
        and rows were dropped.
