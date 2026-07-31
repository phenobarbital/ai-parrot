---
type: Wiki Entity
title: AltairRenderer
id: class:parrot.outputs.formats.altair.AltairRenderer
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Renderer for Altair/Vega-Lite charts
relates_to:
- concept: class:parrot.outputs.formats.chart.BaseChart
  rel: extends
---

# AltairRenderer

Defined in [`parrot.outputs.formats.altair`](../summaries/mod:parrot.outputs.formats.altair.md).

```python
class AltairRenderer(BaseChart)
```

Renderer for Altair/Vega-Lite charts

## Methods

- `def execute_code(self, code: str, pandas_tool: Any=None, execution_state: Optional[Dict[str, Any]]=None, **kwargs) -> Tuple[Any, Optional[str]]` — Execute Altair code within the agent's Python environment.
- `def to_html(self, chart_obj: Any, mode: str='partial', **kwargs) -> str` — Convert Altair chart to HTML.
- `def to_json(self, chart_obj: Any) -> Optional[Dict]` — Export Vega-Lite JSON specification.
- `async def render(self, response: Any, theme: str='monokai', environment: str='html', include_code: bool=False, html_mode: str='partial', **kwargs) -> Tuple[Any, Optional[Any]]` — Render Altair chart.
