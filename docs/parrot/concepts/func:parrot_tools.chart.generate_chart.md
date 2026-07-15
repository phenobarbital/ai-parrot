---
type: Concept
title: generate_chart()
id: func:parrot_tools.chart.generate_chart
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Convenience function to generate a chart without instantiating the tool.
---

# generate_chart

```python
async def generate_chart(chart_type: str, title: str, data: Dict[str, Any], **kwargs) -> Path
```

Convenience function to generate a chart without instantiating the tool.

Args:
    chart_type: Type of chart (bar, line, pie, etc.)
    title: Chart title
    data: Chart data
    **kwargs: Additional options (x_label, y_label, output_format, etc.)

Returns:
    Path to the generated chart image
