---
type: Wiki Entity
title: InfographicHTMLRenderer
id: class:parrot.outputs.formats.infographic_html.InfographicHTMLRenderer
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Renders InfographicResponse as a self-contained HTML5 document.
relates_to:
- concept: class:parrot.outputs.formats.base.BaseRenderer
  rel: extends
---

# InfographicHTMLRenderer

Defined in [`parrot.outputs.formats.infographic_html`](../summaries/mod:parrot.outputs.formats.infographic_html.md).

```python
class InfographicHTMLRenderer(BaseRenderer)
```

Renders InfographicResponse as a self-contained HTML5 document.

Produces a complete HTML page with inline CSS (themed via CSS custom
properties) and optional inline ECharts JS for chart blocks.

Usage::

    renderer = InfographicHTMLRenderer()
    html = renderer.render_to_html(infographic_response, theme="dark")

## Methods

- `async def render(self, response: Any, environment: str='terminal', export_format: str='html', include_code: bool=False, **kwargs) -> Tuple[str, Optional[Any]]` — Render an AIMessage containing InfographicResponse as HTML.
- `def render_to_html(self, data: Union[InfographicResponse, dict], theme: Optional[str]=None) -> str` — Convert InfographicResponse to a complete HTML document.
