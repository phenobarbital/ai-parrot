---
type: Wiki Entity
title: ChartData
id: class:parrot.integrations.parser.ChartData
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Metadata for a generated chart.
---

# ChartData

Defined in [`parrot.integrations.parser`](../summaries/mod:parrot.integrations.parser.md).

```python
class ChartData
```

Metadata for a generated chart.

Attributes:
    path: Path to the chart image file
    title: Chart title
    chart_type: Type of chart (bar, line, pie, etc.)
    format: Output format (png, svg, pdf)
    base64_data: Base64-encoded image data (for inline embedding)
    public_url: Public URL if uploaded to cloud storage

## Methods

- `def to_base64(self) -> str` — Convert the chart image to base64-encoded string.
- `def to_data_uri(self) -> str` — Convert the chart to a data URI for inline embedding.
