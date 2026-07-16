---
type: Wiki Overview
title: 'FEAT-223 — Structured Artifact Contract: Migration Guide'
id: doc:docs-migration-feat-223-structured-artifact-contract-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: FEAT-223 homologates the three structured-output renderers
relates_to:
- concept: mod:parrot.models.outputs
  rel: mentions
- concept: mod:parrot.outputs.formats.structured_base
  rel: mentions
---

# FEAT-223 — Structured Artifact Contract: Migration Guide

## Summary

FEAT-223 homologates the three structured-output renderers
(`STRUCTURED_TABLE`, `STRUCTURED_CHART`, `STRUCTURED_MAP`) under a single,
shared `StructuredOutputBase` mixin and converges the chart config model
(`StructuredChartConfig`) as the canonical chart shape across renderers,
infographic blocks, and artifact storage.

---

## What Changed

### 1. Shared base: `StructuredOutputBase` (Module 1 — FEAT-223/TASK-1454)

A new mixin at `parrot.outputs.formats.structured_base.StructuredOutputBase`
provides:

- `_extract_rows(response)` — deterministic DataFrame extraction (delegates to
  `TableRenderer._extract_data`); never raises.
- `_route_envelope(response, cfg, explanation)` — shared envelope contract:
  `data` excluded from output, rows routed to `response.data`, explanation
  returned as `wrapped`.
- `_extract_json_code(content)` — shared static JSON-extraction helper
  (replaces three identical copies that previously lived in each renderer).

All three structured renderers now inherit `(StructuredOutputBase, BaseChart)`.

### 2. Deterministic chart rows (Module 2 — FEAT-223/TASK-1455)

`StructuredChartRenderer` now obtains rows **exclusively** from
`response.data` (the agent's DataFrame) via `_extract_rows`.  The LLM
contributes **presentation only**: chart type, x/y column names, palette,
`colorBySign`, title, and description.

**Removed from `StructuredChartRenderer`**: `_resolve_rows`, `_reconcile_columns`.

**Added**: `_safe_x` / `_safe_y` — deterministic fallback when the LLM picks
a column absent from the real data.

**Updated system prompt**: LLM is instructed to set `data: []` and reference
only column names visible in its tool output.

### 3. Converged chart config (Module 3 — FEAT-223/TASK-1456)

`StructuredChartConfig` (`parrot.models.outputs`) is the canonical chart shape
for all consumers.  Three fields added to close the gap with `ChartBlock`:

| New field | Alias | Purpose |
|---|---|---|
| `positive_color` | `positiveColor` | Positive-value colour for `colorBySign` charts |
| `x_axis_label` | `xAxisLabel` | Human-readable x-axis display label |
| `y_axis_label` | `yAxisLabel` | Human-readable y-axis display label |

`ChartBlock` (infographic) gains two methods:
- `to_chart_config()` → `StructuredChartConfig` (labels+series → x/y/data)
- `ChartBlock.from_chart_config(cfg, **kwargs)` (inverse)

`Artifact` (storage) gains:
- `Artifact.from_chart_config(cfg, ...)` classmethod — creates a CHART
  `Artifact` whose `definition` carries a `StructuredChartConfig` dump
  (camelCase, `data` excluded).
- `Artifact.as_chart_config()` — parses `definition` back to
  `StructuredChartConfig`.

`ArtifactType.MAP = "map"` added to the enum.

### 4. Map conformance (Module 4 — FEAT-223/TASK-1457)

`StructuredMapRenderer` now inherits `StructuredOutputBase` and uses
`_route_envelope` for its output step.  `_extract_json_code` removed
(inherited from base).  Per-layer `all_payloads` routing is done explicitly
after `_route_envelope` because `cfg.data = []` by design (payloads live
outside the Pydantic model).

---

## What Did NOT Change (Non-Goals)

### Library-specific `OutputMode`s remain

The library-specific renderers — `ALTAIR`, `ECHARTS`, `BOKEH`, `PLOTLY`,
`MATPLOTLIB`, `D3`, `SEABORN`, `HOLOVIEWS`, `TABLE` — are **not removed**
in this release.  They continue to resolve their renderer classes via
`get_renderer()`.

**Retirement plan**: these modes will be deprecated and retired in the next
major release after downstream consumers have migrated to the structured
output modes.

---

## Upgrade Actions

| If you use … | Action |
|---|---|
| `StructuredChartRenderer` with `response.data = None` | Ensure the agent populates `response.data` with a DataFrame **before** the renderer runs. The renderer no longer falls back to `cfg.data`. |
| `ChartBlock` | No breaking change. `labels`/`series` fields preserved. Use `.to_chart_config()` to obtain the agnostic config when needed. |
| `Artifact.definition` (CHART type) | No breaking change if `definition` was already a `Dict`; use `Artifact.from_chart_config()` to create new CHART artifacts with the converged schema. |
| Library-specific `OutputMode`s | No action required yet. Migration to structured modes is voluntary this release. |
