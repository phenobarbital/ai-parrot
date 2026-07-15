---
type: Wiki Summary
title: parrot.outputs.formats.structured_map
id: mod:parrot.outputs.formats.structured_map
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: 'FEAT-221: Structured Map Output Mode renderer.'
relates_to:
- concept: class:parrot.outputs.formats.structured_map.StructuredMapRenderer
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
- concept: mod:parrot.tools.dataset_manager.spatial.contracts
  rel: references
- concept: mod:parrot.tools.dataset_manager.spatial.registry
  rel: references
---

# `parrot.outputs.formats.structured_map`

FEAT-221: Structured Map Output Mode renderer.

Deterministically converts a per-dataset ``SpatialResult`` (in ``response.data``)
into a :class:`~parrot.models.outputs.StructuredMapConfig` whose ``datasets`` key
carries the per-layer GeoJSON/rows payloads, sets ``response.data`` to the flat
tabular rows the payloads were built from, and returns
``(out_without_data, explanation)`` so the HTTP envelope mirrors the
STRUCTURED_TABLE / STRUCTURED_CHART shape (``data`` = tabular rows,
``output`` = full presentation spec including the GeoJSON).

Key design decisions (mirroring StructuredTableRenderer):
- The **deterministic layer owns data + base schema** — no LLM involvement for
  core column types.
- Presentation metadata (columns, tooltip, label) derives from ``DatasetSpatialProfile``
  registry (deterministic wins).
- An **optional LLM-refine pass** may annotate ambiguous (``string``/``integer``)
  columns with finer ``format`` hints.  Hard types (``number``, ``datetime``,
  ``boolean``) are NEVER changed by the LLM.
- If the refine pass fails/times out, the renderer falls back to the deterministic-only
  schema and never raises.
- Renderer never raises — on any error it returns ``(None, error_message)``.
- Empty layer (zero features) is still emitted as a ``MapLayer`` with an empty payload.
- Both ``data_shape="geojson"`` and ``data_shape="rows"`` are supported per-layer.

## Classes

- **`StructuredMapRenderer(StructuredOutputBase, BaseChart)`** — Library-agnostic map renderer for the STRUCTURED_MAP output mode (FEAT-221).
