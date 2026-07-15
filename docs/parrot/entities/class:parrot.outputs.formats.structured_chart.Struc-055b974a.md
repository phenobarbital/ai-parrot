---
type: Wiki Entity
title: StructuredChartRenderer
id: class:parrot.outputs.formats.structured_chart.StructuredChartRenderer
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Library-agnostic chart renderer for the STRUCTURED_CHART output mode.
relates_to:
- concept: class:parrot.outputs.formats.chart.BaseChart
  rel: extends
- concept: class:parrot.outputs.formats.structured_base.StructuredOutputBase
  rel: extends
---

# StructuredChartRenderer

Defined in [`parrot.outputs.formats.structured_chart`](../summaries/mod:parrot.outputs.formats.structured_chart.md).

```python
class StructuredChartRenderer(StructuredOutputBase, BaseChart)
```

Library-agnostic chart renderer for the STRUCTURED_CHART output mode.

Rows come **deterministically** from the agent's DataFrame injected into
``response.data`` (extracted via :meth:`StructuredOutputBase._extract_rows`).
The LLM is responsible for presentation only: chart type, x/y column names,
palette, color_by_sign, title, and description.  If the LLM picks a column
absent from the real data, :meth:`_safe_x` / :meth:`_safe_y` apply a
deterministic fallback so the frontend never receives an invalid config.

The renderer always:

- Sets ``response.data`` to the canonical ``list[dict]`` rows.
- Returns ``(out_without_data, wrapped)`` — the config dict with ``data``
  excluded, paired with the chart description or prose explanation.
- Returns ``(None, error_message)`` on any unrecoverable error — never raises.

## Methods

- `async def render(self, response: Any, *, environment: str='html', **kwargs) -> Tuple[Any, Optional[Any]]` — Render a structured chart configuration from the LLM response.
