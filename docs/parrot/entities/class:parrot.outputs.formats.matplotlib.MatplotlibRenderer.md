---
type: Wiki Entity
title: MatplotlibRenderer
id: class:parrot.outputs.formats.matplotlib.MatplotlibRenderer
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Renderer for Matplotlib charts
relates_to:
- concept: class:parrot.outputs.formats.chart.BaseChart
  rel: extends
---

# MatplotlibRenderer

Defined in [`parrot.outputs.formats.matplotlib`](../summaries/mod:parrot.outputs.formats.matplotlib.md).

```python
class MatplotlibRenderer(BaseChart)
```

Renderer for Matplotlib charts

## Methods

- `def execute_code(self, code: str, pandas_tool: Any=None, execution_state: Optional[Dict[str, Any]]=None, **kwargs) -> Tuple[Any, Optional[str]]` — Execute Matplotlib code within the shared Python environment.
- `def to_html(self, chart_obj: Any, mode: str='partial', **kwargs) -> str` — Convert Matplotlib chart to HTML.
- `def to_json(self, chart_obj: Any) -> Optional[Dict]` — Matplotlib figures don't have a standard native JSON representation.
- `async def render(self, response: Any, theme: str='monokai', environment: str='html', include_code: bool=False, html_mode: str='partial', **kwargs) -> Tuple[Any, Optional[Any]]` — Render Matplotlib chart.
