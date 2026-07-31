---
type: Wiki Entity
title: StructuredMapRenderer
id: class:parrot.outputs.formats.structured_map.StructuredMapRenderer
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Library-agnostic map renderer for the STRUCTURED_MAP output mode (FEAT-221).
relates_to:
- concept: class:parrot.outputs.formats.chart.BaseChart
  rel: extends
- concept: class:parrot.outputs.formats.structured_base.StructuredOutputBase
  rel: extends
---

# StructuredMapRenderer

Defined in [`parrot.outputs.formats.structured_map`](../summaries/mod:parrot.outputs.formats.structured_map.md).

```python
class StructuredMapRenderer(StructuredOutputBase, BaseChart)
```

Library-agnostic map renderer for the STRUCTURED_MAP output mode (FEAT-221).

Reads the per-dataset ``SpatialResult`` from ``response.data``, builds one
``MapLayer`` per dataset deterministically (columns from
``DatasetSpatialProfile.property_cols`` typed via
:func:`~parrot.outputs.formats.table_types.base_column_types`, tooltip from
the profile hints), optionally refines labels/format hints via a narrow LLM
pass (deterministic wins), computes the viewport from feature bounds, and
returns ``(out_without_data, explanation)``.

The renderer always:

- Sets ``response.data`` to the flat tabular rows (feature properties plus
  ``latitude``/``longitude`` for Point geometries, ``_geometry`` otherwise,
  and a ``layer`` discriminator when the result has multiple layers).
- Includes the per-layer payload list in the config's ``datasets`` key, so
  the GeoJSON travels in ``output``.
- Returns ``(out_without_data, explanation)`` — the structured-map config
  dict with the ``data`` key excluded, paired with the prose explanation.
- Returns ``(None, error_message)`` on any unrecoverable error — never raises.

## Methods

- `async def render(self, response: Any, *, environment: str='html', row_limit: Optional[int]=None, **kwargs: Any) -> Tuple[Any, Optional[Any]]` — Render a structured map configuration from the agent response.
