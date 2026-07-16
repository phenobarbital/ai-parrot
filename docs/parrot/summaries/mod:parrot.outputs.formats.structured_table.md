---
type: Wiki Summary
title: parrot.outputs.formats.structured_table
id: mod:parrot.outputs.formats.structured_table
tags:
- summary
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'FEAT-218: Structured Table Output Mode renderer.'
relates_to:
- concept: class:parrot.outputs.formats.structured_table.StructuredTableRenderer
  rel: defines
- concept: mod:parrot.models.outputs
  rel: references
- concept: mod:parrot.outputs.formats
  rel: references
- concept: mod:parrot.outputs.formats.chart
  rel: references
- concept: mod:parrot.outputs.formats.structured_base
  rel: references
- concept: mod:parrot.outputs.formats.table
  rel: references
- concept: mod:parrot.outputs.formats.table_types
  rel: references
---

# `parrot.outputs.formats.structured_table`

FEAT-218: Structured Table Output Mode renderer.

Deterministically converts an agent response (DataFrame in ``response.data`` or
``response.output``) into a :class:`~parrot.models.outputs.StructuredTableConfig`,
sets ``response.data`` to the canonical row list, and returns
``(out_without_data, explanation)`` so the HTTP envelope mirrors the
STRUCTURED_CHART shape.

Key design decisions (Option C from the brainstorm):
- The **deterministic layer owns data + base schema** — no LLM involvement for
  core types.
- An **optional LLM-refine pass** may annotate ambiguous (``string``/``integer``)
  columns with finer ``format`` hints (``currency``/``percent``/``id``/``code``).
  The LLM cannot change a hard base type; on conflict, **deterministic wins**.
- If the refine pass fails/times out, the renderer falls back to the
  deterministic-only schema and never raises.
- Renderer never raises — on any error it returns ``(None, error_message)``,
  mirroring ``StructuredChartRenderer``.

## Classes

- **`StructuredTableRenderer(StructuredOutputBase, BaseChart)`** — Library-agnostic table renderer for the STRUCTURED_TABLE output mode.
