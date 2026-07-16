---
type: Wiki Entity
title: SeabornRenderer
id: class:parrot.outputs.formats.seaborn.SeabornRenderer
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Renderer for Seaborn charts (rendered as static images).
relates_to:
- concept: class:parrot.outputs.formats.chart.BaseChart
  rel: extends
---

# SeabornRenderer

Defined in [`parrot.outputs.formats.seaborn`](../summaries/mod:parrot.outputs.formats.seaborn.md).

```python
class SeabornRenderer(BaseChart)
```

Renderer for Seaborn charts (rendered as static images).

## Methods

- `def execute_code(self, code: str, pandas_tool: Any=None, execution_state: Optional[Dict[str, Any]]=None, **kwargs) -> Tuple[Any, Optional[str]]` — Execute Seaborn code and return all underlying Matplotlib figures.
- `def to_html(self, chart_obj: Any, mode: str='partial', **kwargs) -> str` — Convert Seaborn chart(s) to HTML.
- `def to_json(self, chart_obj: Any) -> Optional[Any]` — Return metadata noting Seaborn renders as static images.
- `async def render(self, response: Any, theme: str='monokai', environment: str='html', include_code: bool=False, html_mode: str='partial', **kwargs) -> Tuple[Any, Optional[Any]]` — Render Seaborn chart(s).
