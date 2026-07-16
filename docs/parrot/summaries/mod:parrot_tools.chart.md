---
type: Wiki Summary
title: parrot_tools.chart
id: mod:parrot_tools.chart
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: Chart Generation Tool for AI-Parrot Agents.
relates_to:
- concept: class:parrot_tools.chart.ChartFormat
  rel: defines
- concept: class:parrot_tools.chart.ChartStyle
  rel: defines
- concept: class:parrot_tools.chart.ChartTool
  rel: defines
- concept: class:parrot_tools.chart.ChartType
  rel: defines
- concept: class:parrot_tools.chart.GenerateChartInput
  rel: defines
- concept: func:parrot_tools.chart.generate_chart
  rel: defines
- concept: mod:parrot_tools.abstract
  rel: references
- concept: mod:parrot_tools.decorators
  rel: references
---

# `parrot_tools.chart`

Chart Generation Tool for AI-Parrot Agents.

Generates visualizations (bar charts, line charts, pie charts, etc.)
from structured data returned by agents.

Supports multiple backends:
- matplotlib (default, most compatible)
- plotly (interactive HTML exports)

Example usage:
    from parrot_tools.chart import ChartTool

    chart_tool = ChartTool(backend="matplotlib")
    agent.add_tool(chart_tool)

    # Agent can then use:
    # generate_chart(chart_type="bar", title="Revenue", data={...})

## Classes

- **`ChartType(str, Enum)`** — Supported chart types.
- **`ChartFormat(str, Enum)`** — Output format for charts.
- **`ChartStyle`** — Visual styling configuration for charts.
- **`GenerateChartInput(BaseModel)`** — Input schema for chart generation.
- **`ChartTool(AbstractTool)`** — Tool for generating charts from structured data.

## Functions

- `async def generate_chart(chart_type: str, title: str, data: Dict[str, Any], **kwargs) -> Path` — Convenience function to generate a chart without instantiating the tool.
