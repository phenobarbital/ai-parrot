---
type: Wiki Entity
title: StructuredTableRenderer
id: class:parrot.outputs.formats.structured_table.StructuredTableRenderer
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Library-agnostic table renderer for the STRUCTURED_TABLE output mode.
relates_to:
- concept: class:parrot.outputs.formats.chart.BaseChart
  rel: extends
- concept: class:parrot.outputs.formats.structured_base.StructuredOutputBase
  rel: extends
---

# StructuredTableRenderer

Defined in [`parrot.outputs.formats.structured_table`](../summaries/mod:parrot.outputs.formats.structured_table.md).

```python
class StructuredTableRenderer(StructuredOutputBase, BaseChart)
```

Library-agnostic table renderer for the STRUCTURED_TABLE output mode.

Extracts rows deterministically from ``response.data`` / ``response.output``
via :meth:`TableRenderer._extract_data`, derives per-column storage types via
:func:`~parrot.outputs.formats.table_types.base_column_types`, applies the
row-limit, reuses the producer's ``explanation`` from ``response.response``,
and optionally refines ambiguous column format hints via a narrow LLM pass.

The renderer always:

- Sets ``response.data`` to the canonical ``list[dict]`` rows.
- Returns ``(out_without_data, explanation)`` — the structured-table config
  dict with the ``data`` key excluded, paired with the prose explanation.
- Returns ``(None, error_message)`` on any unrecoverable error — never raises.

## Methods

- `async def render(self, response: Any, *, environment: str='html', row_limit: Optional[int]=None, **kwargs) -> Tuple[Any, Optional[Any]]` — Render a structured table configuration from the agent response.
