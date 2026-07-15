---
type: Wiki Entity
title: FoliumRenderer
id: class:parrot.outputs.formats.map.FoliumRenderer
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Renderer for Folium maps with support for DataFrames and GeoJSON
relates_to:
- concept: class:parrot.outputs.formats.chart.BaseChart
  rel: extends
---

# FoliumRenderer

Defined in [`parrot.outputs.formats.map`](../summaries/mod:parrot.outputs.formats.map.md).

```python
class FoliumRenderer(BaseChart)
```

Renderer for Folium maps with support for DataFrames and GeoJSON

## Methods

- `def get_expected_content_type(cls) -> type` — This renderer can work with both string (code) and DataFrame (data).
- `def execute_code(self, code: str, pandas_tool: Any=None, execution_state: Optional[Dict[str, Any]]=None, **kwargs) -> Tuple[Any, Optional[str]]` — Execute Folium map code and return map object.
- `def to_html(self, chart_obj: Any, mode: str='partial', **kwargs) -> str` — Convert Folium map to HTML using BaseChart's standard pipeline.
- `def to_json(self, chart_obj: Any) -> Optional[Dict]` — Export map metadata as JSON.
- `async def render(self, response: Any, theme: str='monokai', environment: str='html', include_code: bool=False, html_mode: str='partial', **kwargs) -> Tuple[Any, Optional[Any]]` — Render Folium map.
