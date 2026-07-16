---
type: Wiki Overview
title: 'Brainstorm: Structured Artifact Contract — chart alignment, config convergence
  & taxonomy'
id: doc:sdd-proposals-structured-artifact-contract-brainstorm-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The product direction (Jesus Lara) is that **agents return structured objects,
  and the
---

---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Brainstorm: Structured Artifact Contract — chart alignment, config convergence & taxonomy

**Date**: 2026-06-03
**Author**: Juan Ruffato
**Status**: accepted
**Recommended Option**: B (scope widened per Jesus — homologate the whole `structured_` family)

---

## Problem Statement

The product direction (Jesus Lara) is that **agents return structured objects, and the
presentation layer decides how to render them** — with a *data schema* and a *presentation
schema* — across a taxonomy of `chart, map, document, infographic, summary, table`. This
simplifies the ~15 library-specific `OutputMode`s and enables an output-side selector.

Much of this already exists, built piecemeal:
- `STRUCTURED_CHART` (FEAT-215, merged) and `STRUCTURED_TABLE` (FEAT-218) — agnostic config + shared envelope.
- `Artifact` model + `Canvas` (= "document") + persistence (FEAT-103).
- `InfographicResponse` structured blocks incl. `summary`/`chart`/`table` (infographic-html-output).
- Intent Router (FEAT-070) — but that routes **input** (which resource answers), not output kind.

Two concrete problems block the vision from cohering:

1. **The chart is represented three incompatible ways.** A "chart" exists as
   (a) `StructuredChartConfig` / frontend `AppChartConfig` (FEAT-215), (b) the
   `Artifact.definition` echarts-style `{"spec": {...}}` example (FEAT-103), and
   (c) the infographic `ChartBlock` with its own `ChartType` + `ChartDataSeries`.
   Three shapes for one concept → no single render path, no reuse.

2. **`STRUCTURED_CHART` lets the LLM own the data; `STRUCTURED_TABLE` does not — and the
   table approach is demonstrably more robust.** FEAT-218 makes the *deterministic layer*
   own rows + base column types and lets the LLM only refine ambiguous columns ("on
   conflict, deterministic wins"); it explicitly **rejected** "LLM owns the row set"
   (brainstorm Option A) because it "risks dropped/renamed columns and broken type
   fidelity". FEAT-215 took the rejected path — and in production that produced exactly
   those failures: invented columns (`category`), `data: [{}]`, `{columns, rows}`
   orientations, "No data", sign flips. We patched them with reconciliation, orientation
   normalization, a `chart_data` convention and inference preference — i.e. we rebuilt,
   reactively, what FEAT-218 designed in up front.

Secondary gaps: `ArtifactType` has no `map`; there is no output-side artifact selector;
the data/presentation split Jesus described is realized in `structured_table` but not
elsewhere.

## Constraints & Requirements

- Must NOT break the merged `STRUCTURED_CHART` (FEAT-215) or `STRUCTURED_TABLE` (FEAT-218).
- Must keep the shared response envelope (`output` without `data`, rows in `response.data`,
  explanation as `wrapped`, `output_mode`) — chart and table already share it.
- Backend stays render-library-free for structured kinds (no echarts/plotly server-side).
- Backward compatibility: library-specific `OutputMode`s (echarts/plotly/vega/...) and other
  frontends consuming ai-parrot can't be dropped abruptly.
- Align with, not fork, existing models: `Artifact`/`Canvas` (FEAT-103), `StructuredTableConfig`
  (FEAT-218), `StructuredChartConfig` (FEAT-215), infographic blocks.

---

## Options Explored

### Option A: Converge the chart config only

Pick ONE chart config (the agnostic `AppChartConfig`/`StructuredChartConfig`) and make all
three sites use it: `STRUCTURED_CHART`, the infographic `ChartBlock`, and `Artifact.definition`
for `ArtifactType.CHART`.

✅ **Pros:**
- Removes the 3-way fragmentation; one render path on the frontend.
- Low blast radius; no change to data-ownership philosophy.

❌ **Cons:**
- Leaves the real fragility (LLM owns chart data) untouched — the patches stay load-bearing.
- Doesn't address `map`, summary/document as kinds, or the output selector.

📊 **Effort:** Low

🔗 **Existing Code to Reuse:**
- `parrot/models/outputs.py` (`StructuredChartConfig`), `ai-parrot-visualizations/.../structured_chart.py`, infographic block models.

---

### Option B: Align chart to the table pattern (deterministic data + LLM presentation) + converge chart config + add `map`

Make `STRUCTURED_CHART` symmetric with `STRUCTURED_TABLE`: the **deterministic layer owns the
rows** (extracted from the agent's DataFrame/QueryResponse, exactly like table does via
`TableRenderer._extract_data` + `DatasetManager.categorize_columns`), and the **LLM owns only
the presentation** (chart type, which columns are x/y, palette/colorBySign). Converge the chart
config to one shape (Option A) as part of this, and add `MAP` to `ArtifactType`.

✅ **Pros:**
- Fixes the **root cause** of every FEAT-215 production bug, using the team's own *validated*
  FEAT-218 pattern → consistency the author (Jesus) already endorsed.
- Realizes the "data schema (deterministic) + presentation schema (LLM)" split for charts —
  symmetric with tables.
- Lets us retire the reactive patches (reconciliation/orientation-normalization/`chart_data`
  convention) as the data stops depending on the LLM.
- Converged chart config + `map` move the taxonomy materially forward.

❌ **Cons:**
- Refactor of the `STRUCTURED_CHART` data path (not just additive).
- Needs a deterministic "which columns to chart" step (the LLM still chooses x/y, but from
  the real schema, not from thin air).

📊 **Effort:** Medium

🔗 **Existing Code to Reuse:**
- FEAT-218 deterministic pipeline: `TableRenderer._extract_data` (`outputs/formats/table.py`),
  `DatasetManager.categorize_columns` (`tools/dataset_manager/tool.py`).
- `StructuredTableConfig` as the symmetry reference (`models/outputs.py`).
- Existing renderer/envelope contract in `ai-parrot-visualizations/.../structured_chart.py`.

---

### Option C: Full unified `Artifact{kind, data, presentation, meta}` + output intent-router

Define one discriminated `Artifact` envelope with explicit `data` (rows + json-schema) and
`presentation` (per-kind) sub-schemas for ALL kinds (chart, table, map, summary, document,
infographic), plus an **output-side selector** that picks `kind` from intent — collapsing the
library-specific `OutputMode`s.

✅ **Pros:**
- The complete vision: one contract, one router, fewer modes, frontend owns rendering.

❌ **Cons:**
- Largest refactor; touches `Artifact` (FEAT-103), every structured kind, the handler envelope,
  and the frontend dispatch. High coordination + regression risk.
- Overlaps/intersects FEAT-103 and FEAT-070 — needs cross-feature design with Jesus first.

📊 **Effort:** High

🔗 **Existing Code to Reuse:**
- `Artifact`/`ArtifactType`/`Canvas` (FEAT-103), all structured configs, infographic blocks.

---

## Recommendation

**Option B** is recommended.

It targets the highest-impact, most-defensible change: it **corrects `STRUCTURED_CHART` to the
deterministic-data pattern that FEAT-218 already validated and that Jesus explicitly chose for
tables** — so it's coherent with his own decision, not a new philosophy. It eliminates the root
cause of the chart bugs we patched reactively, makes chart/table symmetric under the shared
envelope, and folds in the chart-config convergence (A) plus the missing `map` type. It stops
short of the full Option C rewrite (which entangles FEAT-103/FEAT-070 and needs Jesus in the
room), while leaving a clean path toward C: once chart/table are symmetric deterministic-data
artifacts, generalizing to a unified `Artifact{kind, data, presentation}` and an output selector
is incremental.

What we trade off: Option B is a refactor of the chart data path rather than a purely additive
change, and it doesn't yet deliver the output-side router. Both are acceptable: the refactor
removes load-bearing patches (net simplification), and the router is better designed after the
artifacts are symmetric.

---

## Feature Description

### User-Facing Behavior
Same as today for the user: ask for a chart, get a chart. The difference is reliability — the
numbers shown come deterministically from the agent's computed data, so the same question yields
the same chart, and "No data"/blank/mismatch failures disappear. Charts, tables (and later maps)
behave symmetrically.

### Internal Behavior
- The producing agent sets `response.data` (DataFrame/QueryResponse) + `explanation`, as it does
  for tables today.
- The chart renderer extracts rows + base column types deterministically (reusing the table
  pipeline), then asks the LLM only for *presentation*: chart `type`, which existing columns map
  to `x`/`y[]`, and optional palette/colorBySign — chosen from the real schema, never invented.
- The renderer builds the converged chart config, routes rows to `response.data`, returns
  `(output_without_data, explanation)` — identical envelope to chart/table today.
- The same converged chart config is what the infographic `ChartBlock` and `Artifact.definition`
  (CHART) carry, so there is one render path.
- `ArtifactType.MAP` added with a `map` definition mirroring the chart contract.

### Edge Cases & Error Handling
- LLM picks an x/y not in the schema → deterministic layer rejects/falls back to a sensible
  default (first categorical = x, numerics = y), never crashes (graceful degradation already in
  the renderer + frontend boundary).
- No usable rows → explicit "no data" surfaced, not a blank chart.
- Library-specific modes remain available during migration.

---

## Capabilities

### New Capabilities
- `chart-deterministic-data`: chart rows owned by the deterministic layer (table-pattern parity).
- `chart-config-convergence`: one chart config shape across structured_chart / infographic / artifact.
- `map-artifact-type`: `MAP` added to `ArtifactType` + map definition.

### Modified Capabilities
- `structured-chart-output` (FEAT-215): data-ownership refactor + config convergence.
- `agent-artifact-persistency` (FEAT-103): `ArtifactType.MAP`; CHART definition = converged config.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `models/outputs.py` `StructuredChartConfig` | modifies | converge shape; align validation with table |
| `ai-parrot-visualizations/.../structured_chart.py` | modifies | deterministic rows (reuse table extract); LLM = presentation only |
| `outputs/formats/table.py` `_extract_data`, `tools/dataset_manager/tool.py` `categorize_columns` | depends on (reuse) | shared deterministic data layer |
| `models/outputs.py` `ArtifactType` (FEAT-103) | extends | add `MAP` |
| infographic `ChartBlock` (infographic-html-output) | modifies | use converged chart config |
| frontend `AppChart`/`chart-contract.ts` | aligns | already the agnostic target; minimal change |
| library-specific `OutputMode`s | none (this FEAT) | deprecation deferred to Option C |

---

## Code Context

### Verified References
- `STRUCTURED_CHART` config + renderer: `parrot/models/outputs.py` (`StructuredChartConfig`),
  `packages/ai-parrot-visualizations/src/parrot/outputs/formats/structured_chart.py`
  (`_resolve_rows`, `_reconcile_columns` — the reactive patches Option B would retire).
- `STRUCTURED_TABLE` (the pattern to mirror): `sdd/specs/structured-table.spec.md` (FEAT-218);
  `StructuredTableConfig`/`TableColumn` in `parrot/models/outputs.py`; deterministic layer
  `TableRenderer._extract_data` (`outputs/formats/table.py`) + `DatasetManager.categorize_columns`
  (`tools/dataset_manager/tool.py`).
- `Artifact`/`ArtifactType{CHART,CANVAS,INFOGRAPHIC,DATAFRAME,EXPORT}`/`CanvasDefinition`:
  `sdd/specs/agent-artifact-persistency.spec.md` (FEAT-103).
- Infographic blocks `BlockType{TITLE,HERO_CARD,SUMMARY,CHART,TABLE,IMAGE,...}` +
  `InfographicResponse`: `sdd/specs/infographic-html-output.spec.md`.
- Input router (distinct from output selection): `sdd/specs/intent-router.spec.md` (FEAT-070).
- Frontend agnostic target: `navigator-frontend-next` `src/lib/components/charts/AppChart.svelte`
  + `chart-contract.ts` (already consumes the agnostic config; LayerChart v2 2.0.0-next.64).

### Does NOT exist
- No `MAP` member in `ArtifactType`.
- No single chart config shared across the three sites (today: 3 shapes).
- No output-side artifact/kind selector (FEAT-070 is input-side).
- No formalized `data` + `presentation` split outside `structured_table`.

---

## Open Questions

### Resolved during brainstorm
- **Q2 — Converged chart config shape → RESOLVED:** reuse the existing agnostic
  `AppChartConfig` / `StructuredChartConfig` as the single canonical shape (it is already what
  the frontend renders). No new 4th model is introduced; the infographic `ChartBlock` and
  `Artifact.definition` (CHART) converge onto it.
- **Q3 — Is `map` in-scope → RESOLVED: yes, in scope.** Adding `ArtifactType.MAP` + a `map`
  definition mirroring the chart contract is small and keeps the taxonomy coherent (already
  reflected in Options, Capabilities and Impact above).

### Resolved by Jesus (2026-06-03)
- **Q1 → APPROVED, scope widened:** yes to the deterministic-data alignment, and **homologate
  the whole `structured_` family** under one common pattern — *"if we homologate all the
  `structured_` outputs it will be easier to incorporate new ones"*. So this FEAT delivers a
  homologated `structured_` contract (chart + table conform now; map/summary/document plug in
  later), not just a chart-only fix.
- **Q5 → RESOLVED:** keep the library-specific `OutputMode`s (echarts/plotly/vega/matplotlib/...)
  for **backward compatibility now; retire them in the next release** — *"not yet; it stays for
  backward compatibility and they will be retired in the next release"*.

### Deferred (Option C)
- **Q4:** Output-side artifact selector — agent proposes `kind`, a router validates, or both.
  Out of scope for this FEAT; noted for the unified-artifact follow-up (distinct from the
  input-side FEAT-070 Intent Router).

---

## Parallelism Assessment

- **Internal parallelism:** chart-config convergence (A) and `map`-type addition are independent
  of the deterministic-data refactor; could be separate worktrees/tasks within the spec.
- **Cross-feature:** intersects FEAT-103 (`ArtifactType`) and FEAT-218 (reuses its deterministic
  layer) — read-only reuse, no conflicting edits expected. Option C (not this FEAT) would need
  coordinated design with FEAT-070/FEAT-103.
- **Recommended isolation:** `mixed` — deterministic-data refactor sequential; config-convergence
  and `map` parallelizable.
