---
type: Wiki Entity
title: PlotlyRenderer
id: class:parrot.outputs.formats.plotly.PlotlyRenderer
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Renderer for Plotly charts
relates_to:
- concept: class:parrot.outputs.formats.chart.BaseChart
  rel: extends
---

# PlotlyRenderer

Defined in [`parrot.outputs.formats.plotly`](../summaries/mod:parrot.outputs.formats.plotly.md).

```python
class PlotlyRenderer(BaseChart)
```

Renderer for Plotly charts

## Methods

- `def execute_code(self, code: str, pandas_tool: Any=None, execution_state: Optional[Dict[str, Any]]=None, **kwargs) -> Tuple[Any, Optional[str]]` — Execute Plotly code within the shared Python environment.
- `def to_html(self, chart_obj: Any, mode: str='partial', **kwargs) -> str` — Convert Plotly chart(s) to HTML.
- `def to_json(self, chart_obj: Any) -> Optional[Any]` — Export Plotly JSON specification (returns list if multiple).
- `async def render(self, response: Any, theme: str='monokai', environment: str='html', include_code: bool=False, html_mode: str='partial', **kwargs) -> Tuple[Any, Optional[Any]]` — Render Plotly chart.
