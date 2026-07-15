---
type: Wiki Entity
title: EChartsRenderer
id: class:parrot.outputs.formats.echarts.EChartsRenderer
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Renderer for Apache ECharts (JSON Configuration)
relates_to:
- concept: class:parrot.outputs.formats.chart.BaseChart
  rel: extends
- concept: class:parrot.outputs.formats.mixins.emaps.EChartsMapsMixin
  rel: extends
---

# EChartsRenderer

Defined in [`parrot.outputs.formats.echarts`](../summaries/mod:parrot.outputs.formats.echarts.md).

```python
class EChartsRenderer(EChartsMapsMixin, BaseChart)
```

Renderer for Apache ECharts (JSON Configuration)

## Methods

- `def execute_code(self, code: str, pandas_tool: Any=None, **kwargs) -> Tuple[Any, Optional[str]]` — Parse and validate ECharts JSON configuration.
- `def to_html(self, chart_obj: Any, mode: str='partial', **kwargs) -> str` — Convert ECharts to HTML.
- `async def render(self, response: Any, theme: str='monokai', environment: str='html', include_code: bool=False, html_mode: str='partial', **kwargs) -> Tuple[Any, Optional[Any]]` — Render ECharts visualization.
