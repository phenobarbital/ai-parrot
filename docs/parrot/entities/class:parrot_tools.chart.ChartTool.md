---
type: Wiki Entity
title: ChartTool
id: class:parrot_tools.chart.ChartTool
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Tool for generating charts from structured data.
relates_to:
- concept: class:parrot.tools.abstract.AbstractTool
  rel: extends
---

# ChartTool

Defined in [`parrot_tools.chart`](../summaries/mod:parrot_tools.chart.md).

```python
class ChartTool(AbstractTool)
```

Tool for generating charts from structured data.

Designed to work with integration wrappers (Teams, Telegram) that can
send images inline in messages.

Attributes:
    backend: Chart generation library (matplotlib, plotly)
    output_dir: Directory for saving generated charts
    style: Default visual styling
    auto_cleanup: Whether to cleanup old charts
