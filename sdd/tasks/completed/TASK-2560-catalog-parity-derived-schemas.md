# TASK-2560: Catalog parity — derived schemas, extended lowering, LLM-origin inline-data guard

**Feature**: FEAT-473 — A2UI v1.0 for STRUCTURED_CHART / STRUCTURED_TABLE / STRUCTURED_MAP
**Spec**: `sdd/specs/a2ui-v1-structured-outputs.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none *(hard external gate: FEAT-470 PR merged into `dev` — do NOT start before)*
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 1. FEAT-470's `catalog/parrot/{chart,datatable,map}.py` hand-write
`CHART_SCHEMA` / `MAP_SCHEMA` covering only a subset of the structured config
fields (spec §1 "Schema parity gap"). This task makes the three parrot-catalog
schemas **derived from** the `StructuredXConfig` Pydantic models (G2 — parity by
construction, brainstorm Option D), extends `INSTRUCTIONS`/`lower()` for the new
fields, and adds the G8 LLM-origin guard: `validate_envelope(origin=LLM)` must
reject inline `data` arrays on Chart/DataTable/Map.

---

## Scope

- Create `parrot/outputs/a2ui/catalog/parrot/_derive.py` with
  `derive_schema(model, *, binding_fields, required=()) -> dict`:
  `model.model_json_schema(by_alias=True)`, replace each field in
  `binding_fields` (`data`, `datasets`) with the binding descriptor used by
  FEAT-470 schemas, strip Pydantic `title` keys, KEEP `$defs`.
- Rewrite `CHART_SCHEMA` / `DATATABLE_SCHEMA` / `MAP_SCHEMA` in
  `catalog/parrot/{chart,datatable,map}.py` as import-time
  `derive_schema(...)` calls on `StructuredChartConfig` /
  `StructuredTableConfig` / `StructuredMapConfig`.
- Extend `INSTRUCTIONS` strings to mention the newly exposed props
  (Chart: trendline, splitSeries, colorBySign/negativeColor/positiveColor,
  xAxisLabel/yAxisLabel, mapName, description, dataVariable; Map: full
  `MapLayer` fields, viewport, query).
- Extend `lower()`: Chart renders axis labels/trendline as caption `Text`
  nodes; Map renders per-layer `labelField`/`markerColor`/`totalCount`/`capped`
  in the titled layer summary (stays a summary — no GeoJSON lowering).
- Add the origin-keyed rule in `catalog/__init__.py::validate_envelope`:
  for components Chart/DataTable/Map, `origin=LLM` + inline list under `data`
  → `CatalogValidationError`; `{"path": ...}` passes; `origin=TOOL` accepts both.
- Re-validate `export_catalog_definition()` output against the vendored
  `catalog_definition.json` (with `$defs` present).
- Unit tests (spec §4 Module-1 rows).

**NOT in scope**: adapter/builders (TASK-2561), compat shim (TASK-2562),
renderer prop fidelity (TASK-2564).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/_derive.py` | CREATE | `derive_schema()` helper |
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/chart.py` | MODIFY | derived schema, INSTRUCTIONS, lower() |
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/datatable.py` | MODIFY | derived schema (parity already ⊇ hand-written) |
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/parrot/map.py` | MODIFY | derived schema, INSTRUCTIONS, lower() |
| `packages/ai-parrot/src/parrot/outputs/a2ui/catalog/__init__.py` | MODIFY | LLM-origin inline-`data` rejection in `validate_envelope` |
| `packages/ai-parrot/tests/outputs/a2ui/test_catalog_parity.py` | CREATE | derivation + guard + export tests |

---

## Codebase Contract (Anti-Hallucination)

> References below marked **[470-wt]** were verified on branch
> `feat-470-a2ui-v1-dialect` @ `0da976674` (2026-08-29) while TASK-2546–2548
> were still in progress. **Re-verify each one against `dev` after the
> FEAT-470 merge before writing code** — `catalog/__init__.py` and the
> conformance tests are exactly what those tasks touch.

### Verified Imports
```python
# core dev @ 8b40e0c (2026-08-29)
from parrot.models.outputs import StructuredChartConfig, StructuredTableConfig, StructuredMapConfig, MapLayer, MapViewport, MapQuery, TableColumn
# models/outputs.py:319/530/746/640/706/729/493
# [470-wt]
from parrot.outputs.a2ui.catalog import register_component, validate_envelope, validate_message  # catalog/__init__.py:97/324/281
from parrot.outputs.a2ui.catalog.base import DEFAULT_CATALOG_ID, ProducerOrigin, CatalogValidationError  # base.py:52/80/294
from parrot.outputs.a2ui.catalog.export import export_catalog_definition  # export.py:32
```

### Existing Signatures to Use
```python
# [470-wt] catalog/parrot/chart.py: CHART_SCHEMA :22 (title,type[bar/line/area/scatter/pie/map],x,y,stacked,showLegend,xAxisMode,palette,data)
#   @register_component("Chart") class ChartComponent :57 (requires_actions=False); lower() :63 → Card{Column[Text ...]}
# [470-wt] catalog/parrot/datatable.py: DATATABLE_SCHEMA :21; DataTableComponent :56; lower() :62 (header Row + ChildTemplate)
# [470-wt] catalog/parrot/map.py: MAP_SCHEMA :22; MapComponent :60; lower() :66 (titled layer summary)
# [470-wt] catalog/__init__.py
def validate_envelope(envelope, *, origin: ProducerOrigin = ProducerOrigin.TOOL, surface_catalog_id: str | None = None) -> None  # :324, reports ALL problems
def validate_message(message) -> None  # :281 jsonschema against vendored spec
# [470-wt] export.py: export_catalog_definition copies definition.schema_ verbatim; $defs verified OK (spike 2026-08-29)
# dev models/outputs.py — config fields (camelCase aliases, by_alias dumps in use):
#   StructuredChartConfig :319  type,x,y,stacked,trendline,split_series,show_legend,x_axis_mode,palette,color_by_sign,
#     negative_color,positive_color,x_axis_label,y_axis_label,map_name,title,description,data,data_variable
#   StructuredTableConfig :530  columns,data,explanation,total_rows,truncated
#   MapLayer :640  layer,columns,tooltip_template,label_field,data_shape,total_count,capped,geodesic,marker_color
#   StructuredMapConfig :746  layers,data,datasets,viewport,query,base_layer,title,description,explanation
```

### Does NOT Exist
- ~~`catalog/parrot/_derive.py`~~ / ~~`derive_schema`~~ — this task creates them.
- ~~`catalog/parrot/` on `dev` today~~ — dev still has `catalog/components/`;
  the `parrot/` layout arrives with the FEAT-470 merge (its TASK-2539). Gate.
- ~~CHART_SCHEMA fields `trendline/splitSeries/colorBySign/xAxisLabel/yAxisLabel/mapName`~~ — not in FEAT-470.
- ~~MAP_SCHEMA MapLayer fields beyond `name`/`type`~~ — not in FEAT-470.

---

## Implementation Notes

### Key Constraints
- Derivation is **import-time** (module constants), not per-call.
- Strip `title` keys (Pydantic noise), keep `$defs` (`MapLayer`, `MapViewport`,
  `MapQuery`, `MapColumn`) — export validation is the gate (AC-3).
- Pydantic may emit `anyOf: [{type}, {type: "null"}]` for optionals — leave
  as-is unless export validation rejects it.
- The inline-`data` rule MUST be keyed on `origin` so TOOL-origin surfaces from
  the TASK-2561 adapter pass (spec §7 gotcha).
- `Map.lower()` remains a titled layer summary (AC-12; brainstorm R2c).

### References in Codebase
- `catalog/parrot/*.py` [470-wt] — current hand-written schemas to supersede
- `catalog/export.py:32` — verbatim `schema_` copy, `$defs` tolerated

---

## Acceptance Criteria

- [ ] Every `StructuredChartConfig` alias except `data` is a property of `CHART_SCHEMA`; same for Table (`data`) and Map (`data`, `datasets`) (AC-3)
- [ ] `MAP_SCHEMA` keeps `$defs`; `export_catalog_definition()` validates against vendored `catalog_definition.json` (AC-3)
- [ ] Derived `DATATABLE_SCHEMA` ⊇ previous hand-written schema
- [ ] `validate_envelope(origin=LLM)` rejects inline `data` list on Chart/DataTable/Map, accepts `{"path"}`; `origin=TOOL` accepts both (AC-9)
- [ ] Chart `lower()` emits caption Text for axis labels/trendline; Map `lower()` shows per-layer labelField/markerColor/totalCount/capped
- [ ] Tests pass: `pytest packages/ai-parrot/tests/outputs/a2ui/test_catalog_parity.py -v`; ruff clean on changed files

---

## Test Specification

```python
# packages/ai-parrot/tests/outputs/a2ui/test_catalog_parity.py
def test_derived_chart_schema_has_all_config_fields(): ...
def test_derived_map_schema_keeps_defs_and_validates_export(): ...
def test_datatable_schema_parity_unchanged(): ...
def test_llm_origin_rejects_inline_rows(): ...
def test_tool_origin_allows_inline_rows(): ...
def test_chart_lower_renders_axis_labels_and_trendline(): ...
```

---

## Agent Instructions

1. **Verify the FEAT-470 merge landed on `dev`** (`catalog/parrot/` exists) — abort if not.
2. Re-verify every **[470-wt]** contract line against merged `dev`; update this contract first if drifted.
3. Implement per scope; run tests; move this file to `sdd/tasks/completed/`; update the per-spec index; fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-08-29
**Notes**: FEAT-470 confirmed merged into `dev` (PR #1263, `catalog/parrot/`
present) before starting. Implemented `derive_schema()` in a new
`catalog/parrot/_derive.py` (strips Pydantic `title` annotations, keeps
`$defs`, replaces `data`/`datasets` with the binding descriptor, camelCases
any remaining snake_case top-level property — needed because
`StructuredTableConfig.total_rows`/`truncated` have no Pydantic alias).
Rewired `CHART_SCHEMA`/`DATATABLE_SCHEMA`/`MAP_SCHEMA` to `derive_schema(...)`
calls; extended `Chart.lower()` (axis-label/trendline caption Text) and
`Map.lower()` (per-layer `labelField`/`markerColor`/`totalCount`/`capped`
summary — reading the new `MapLayer.layer` id field, since the derived
schema's layer shape supersedes the old hand-written `{name,type}` one).
Extended `INSTRUCTIONS` for Chart/Map. Added `INLINE_DATA_NOT_ALLOWED_FOR_LLM`
to `catalog/base.py` and wired the `origin=LLM` inline-`data`/`datasets`
rejection into `catalog/__init__.py::validate_envelope` (TOOL-origin exempt).
All 12 pre-existing `test_export.py`/`test_spec_vendored.py` tests confirm
`export_catalog_definition()` still validates the derived schemas + `$defs`
against the vendored `catalog_definition.json`. New
`tests/outputs/a2ui/test_catalog_parity.py` (9 tests) covers derivation
parity, the LLM/TOOL origin guard, and the extended `lower()` output. Full
`tests/outputs/a2ui/` suite: 484 passed, 1 skipped (0 regressions). ruff
clean on all changed files.

**Deviations from spec**: Updated the pre-existing FEAT-470 golden test
`test_components_chart_datatable_map.py::TestMapComponent::test_map_lowering_golden`
(+ its `golden/map_lowered.json` fixture) — not listed in this task's Files
table, but a direct, necessary consequence of superseding the old
hand-written `MapLayer` shape (`{name,type}` → full `MapLayer` vocabulary,
`layer` id field) that this task's own scope required. No other out-of-scope
files touched.
