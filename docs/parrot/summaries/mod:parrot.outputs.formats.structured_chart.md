---
type: Wiki Summary
title: parrot.outputs.formats.structured_chart
id: mod:parrot.outputs.formats.structured_chart
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'FEAT-215 (FEAT-223 Module 2 / FEAT-224 Module 2): Structured Chart Output
  Mode renderer.'
relates_to:
- concept: class:parrot.outputs.formats.structured_chart.StructuredChartRenderer
  rel: defines
- concept: mod:parrot.models.outputs
  rel: references
- concept: mod:parrot.outputs.formats
  rel: references
- concept: mod:parrot.outputs.formats.chart
  rel: references
- concept: mod:parrot.outputs.formats.structured_base
  rel: references
- concept: mod:parrot.outputs.formats.table_types
  rel: references
---

# `parrot.outputs.formats.structured_chart`

FEAT-215 (FEAT-223 Module 2 / FEAT-224 Module 2): Structured Chart Output Mode renderer.

Validates LLM-emitted JSON into :class:`StructuredChartConfig`, sets
``response.output`` to the camelCase config dict **without the data key**, routes
data rows to ``response.data``, and leaves ``response.code`` untouched (null).

FEAT-223 deterministic refactor: rows come exclusively from the agent's DataFrame
(``response.data``), extracted via :class:`StructuredOutputBase._extract_rows`.
The LLM contributes **presentation only** (type, x, y, palette, color_by_sign, …);
it must NOT emit data rows.  If the LLM picks an absent x/y column, the renderer
applies a deterministic fallback so the frontend always receives a valid config.

FEAT-224 (Module 2 — G3): The renderer now reads its config from
``response.output`` / ``response.structured_output`` (where PandasAgent stores the
LLM's StructuredChartConfig) rather than from ``response.code``, which is reserved
for genuine interpretable Python/TS code.  ``response.code`` is no longer consulted
as a config source; a text-fallback path is retained for any client that sends
the raw JSON string in the response body.

## Classes

- **`StructuredChartRenderer(StructuredOutputBase, BaseChart)`** — Library-agnostic chart renderer for the STRUCTURED_CHART output mode.
