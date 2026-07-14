---
type: Wiki Entity
title: BaseChart
id: class:parrot.outputs.formats.chart.BaseChart
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Base class for chart renderers - extends BaseRenderer with chart-specific
  methods
relates_to:
- concept: class:parrot.outputs.formats.base.BaseRenderer
  rel: extends
---

# BaseChart

Defined in [`parrot.outputs.formats.chart`](../summaries/mod:parrot.outputs.formats.chart.md).

```python
class BaseChart(BaseRenderer)
```

Base class for chart renderers - extends BaseRenderer with chart-specific methods

## Methods

- `def to_html(self, chart_obj: Any, mode: str='partial', include_code: bool=False, code: Optional[str]=None, theme: str='monokai', title: str='AI-Parrot Chart', **kwargs) -> str` — Convert chart object to HTML.
