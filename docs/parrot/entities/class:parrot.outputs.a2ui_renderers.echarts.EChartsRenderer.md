---
type: Wiki Entity
title: EChartsRenderer
id: class:parrot.outputs.a2ui_renderers.echarts.EChartsRenderer
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Chart-component → ECharts option JSON renderer (+ optional vendored HTML
  wrap).
relates_to:
- concept: class:parrot.outputs.a2ui.renderers.AbstractA2UIRenderer
  rel: extends
---

# EChartsRenderer

Defined in [`parrot.outputs.a2ui_renderers.echarts`](../summaries/mod:parrot.outputs.a2ui_renderers.echarts.md).

```python
class EChartsRenderer(AbstractA2UIRenderer)
```

Chart-component → ECharts option JSON renderer (+ optional vendored HTML wrap).

## Methods

- `async def render(self, envelope: CreateSurface, *, bake: bool=True, wrap_html: bool=False) -> RenderedArtifact` — Render the first Chart component to an ECharts option (JSON or HTML wrap).
