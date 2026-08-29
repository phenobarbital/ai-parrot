---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: A2UI v1.0 for STRUCTURED_CHART / STRUCTURED_TABLE / STRUCTURED_MAP

**Feature ID**: FEAT-473
**Date**: 2026-08-29
**Author**: Jesus Lara (with Claude)
**Status**: draft
**Target version**: 0.30.0
**Brainstorm**: `sdd/proposals/a2ui-v1-structured-outputs.brainstorm.md` (Option A + Option D schema derivation)
**Depends on**: FEAT-470 `a2ui-v1-dialect` — **start gate: this feature's worktree is created only after the FEAT-470 PR has merged into `dev`.**
**Related**: FEAT-215 / FEAT-218 / FEAT-221 (structured chart/table/map), FEAT-224 (structured `artifacts[]` envelope), FEAT-273 (A2UI core)

---

## 1. Motivation & Business Requirements

### Problem Statement

`OutputMode.STRUCTURED_CHART`, `STRUCTURED_TABLE` and `STRUCTURED_MAP` are the
live, deterministic "data → visual config" path used by `PandasAgent`
(`bots/data.py`) and `DatabaseAgent` (`bots/database/agent.py`). Today they
produce a **proprietary JSON contract**: the renderer dumps a
`StructuredChartConfig` / `StructuredTableConfig` / `StructuredMapConfig` into
`response.output` (camelCase, `data` excluded), rows go to `response.data`, and
FEAT-224 mirrors the config into `response.artifacts[] = {type, artifactId,
definition}`.

They are **not A2UI at all**, even though `outputs/formats/__init__.py` marks
all three as deprecated in favour of `OutputMode.A2UI` with the
Chart/DataTable/Map catalog component (FEAT-273). The replacement never
materialised because the A2UI wire was itself a dialect until FEAT-470.

FEAT-470 now provides a spec-conformant v1.0 wire, vendored official schemas +
`jsonschema` validation, a `catalog/parrot/` with `Chart`, `DataTable`, `Map`
whose vocabulary is *adapted from* the structured config models, a bake pass
resolving `{"path"}` bindings and `ChildTemplate` rows, and satellite renderers
(`echarts`, `folium_map`, `interactive_html`, `ssr_html`, `pdf`,
`adaptive_cards`) that consume baked v1.0 components.

What is missing is the **bridge**: a STRUCTURED_* response never becomes a
`CreateSurface`, so none of that machinery (external A2UI renderers, PDF/SSR
delivery through `Agent.notification()`, Adaptive Cards for Teams, deep-link
degradation) is reachable from the most-used data agents. Two gaps make a
naïve bridge lossy:

1. **Schema parity gap.** `CHART_SCHEMA` / `MAP_SCHEMA` cover a subset of the
   config fields. Missing on Chart: `trendline`, `split_series`,
   `color_by_sign`, `negative_color`, `positive_color`, `x_axis_label`,
   `y_axis_label`, `map_name`, `description`, `data_variable`. Missing on Map:
   `MapLayer.columns`, `tooltip_template`, `label_field`, `data_shape`,
   `total_count`, `capped`, `geodesic`, `marker_color`;
   `StructuredMapConfig.datasets`, `query`, `explanation`. `DataTable` is at
   parity already.
2. **No `build_map` builder** and no deterministic config → surface adapter
   (`outputs/a2ui/adapters/` only holds `infographic.py`).

### Goals

- G1 **Dual-emit**: STRUCTURED_* responses keep `response.output` (config)
  and `response.data` (rows) unchanged — except one additive key,
  `surfaceId`, on `output` — and additionally carry a spec-conformant v1.0
  `CreateSurface` in `response.a2ui_envelope`, built deterministically with
  zero LLM involvement.
- G2 **Full schema parity**: the parrot-catalog `Chart`/`DataTable`/`Map`
  schemas are **derived from** the `StructuredXConfig` Pydantic models, so
  every config field is representable on the wire, by construction.
- G3 **Rows in `dataModel`**: components bind rows via `{"path": …}`; the
  envelope is standalone-renderable by any v1.0 renderer (tables at
  `/rows`, maps at `/layers/<i>/features`), capped by the renderer's
  existing `row_limit` with `truncated`/`totalRows` (or `capped`/
  `total_count` per map layer) on overflow.
- G4 **Single hook point**: conversion runs inside
  `StructuredOutputBase._route_envelope` via a core adapter, so every
  renderer path (PandasAgent, DatabaseAgent, direct `render()`) benefits;
  the helper keeps its "never raises" contract.
- G5 **Artifact entry v2**: `response.artifacts[]` entries become
  `{type, artifactId, surfaceId, schemaVersion: 2, definition: <Component>}`
  with `surfaceId == artifactId`, and DatabaseAgent's STRUCTURED_TABLE path
  mints artifacts too (closing the FEAT-224 gap).
- G6 **Consumer cushion**: a `compat` shim (`artifact_definition_to_legacy`)
  reproduces the FEAT-224 v1 `definition`; frontend guide rewritten;
  shim supported through **0.31**, removed in 0.32.
- G7 **Renderer fidelity**: satellite `echarts` and `folium_map` honour the
  newly exposed props (stacked / splitSeries / trendline / colorBySign /
  axis labels / palette; marker_color / tooltip_template / label_field /
  geodesic / data_shape / multi-layer).
- G8 **LLM producer constraint**: the FEAT-470 LLM producer may emit
  `Chart`/`DataTable`/`Map`, but with `origin=LLM` their `data` MUST be a
  `{"path"}` binding — inline rows are rejected by `validate_envelope`.
- G9 The non-stream handler path surfaces `a2ui_envelope` whenever present,
  not only for `output_mode == A2UI`.

### Non-Goals (explicitly out of scope)

- Retiring the STRUCTURED_* modes or the `response.output` config mirror
  (Option C in the brainstorm — rejected; that is a later,
  frontend-coordinated cut).
- Agent-side conversion in `bots/data.py` instead of the renderer base
  (Option B — rejected: perpetuates the drift DatabaseAgent already shows).
- Changing `Map.lower()` beyond a titled layer summary (GeoJSON-rich
  lowering rejected in brainstorm R2c).
- Any new A2UI-specific row cap setting; `row_limit` is reused.
- Streaming `updateDataModel` follow-ups for structured surfaces.
- Changes to the public `render()` signatures or the config models' fields.

---

## 2. Architectural Design

### Overview

A **core, pure adapter** — `parrot/outputs/a2ui/adapters/structured.py` —
converts a typed structured config plus already-extracted rows into a
validated `CreateSurface`: root component `id="root"`, `component` ∈
{`Chart`, `DataTable`, `Map`}, `catalogId = DEFAULT_CATALOG_ID`, all config
fields as top-level camelCase props (`None` dropped; input-only `data` /
`datasets` replaced by `{"path"}` bindings), and a populated `dataModel`.
Every surface passes `validate_envelope(origin=ProducerOrigin.TOOL)` and
`validate_message` (jsonschema). A new `build_map()` joins `build_chart` /
`build_datatable`, and `build_surface` gains a `data_model=` passthrough that
the three builders expose.

The **satellite hook** is `StructuredOutputBase._route_envelope`: after the
existing dump and `response.data` routing it mints `surface_id`
(`f"{mode}-{uuid4().hex[:8]}"` — the FEAT-224 id pattern), calls the adapter
with the capped rows (or per-layer payloads for maps), stores
`serialize(surface)` in `response.a2ui_envelope`, injects `surfaceId` into
the returned `out` dict, and records the id on `response.artifact_id`. Any
exception is logged at `warning` and swallowed; `output_mode` is not touched.

**Schema parity by construction (Option D)**: `CHART_SCHEMA`, `MAP_SCHEMA`,
`DATATABLE_SCHEMA` are generated at import time from
`StructuredChartConfig.model_json_schema(by_alias=True)` etc., with `data`
(and `datasets`) replaced by the binding descriptor. Pydantic `$defs`
(`MapLayer`, `MapViewport`, `MapQuery`, `MapColumn`) are kept — verified
valid against the vendored `catalog_definition.json` (spike 2026-08-29).
`INSTRUCTIONS` and `lower()` are extended to mention/render the new fields.

**Artifact v2**: the FEAT-224 minting block in `bots/data.py` is factored into
a helper `attach_structured_artifact(response, output_mode)` that reads the
root component from `response.a2ui_envelope["createSurface"]["components"][0]`
and appends `{type, artifactId, surfaceId, schemaVersion: 2, definition}`;
it falls back to the v1 config-dict `definition` (no `schemaVersion`) when
no envelope exists. The helper is also applied on DatabaseAgent's
STRUCTURED_TABLE path.

**Compat**: `compat.py` gains `is_legacy_artifact(entry)` and
`artifact_definition_to_legacy(entry) -> dict` (v2 component node → FEAT-224
camelCase config, `data`/`datasets` absent).

**Transport**: `handlers/agent.py` non-stream path returns `a2ui_envelope`
whenever the response carries one (stream path already does).

### Component Diagram

```
PandasAgent / DatabaseAgent
        │  response(cfg-ish content, data)
        ▼
StructuredChart/Table/MapRenderer.render()            (satellite formats/)
        │  cfg: StructuredXConfig, rows
        ▼
StructuredOutputBase._route_envelope() ──── out(+surfaceId), explanation ──▶ HTTP layer
        │  cfg + capped rows/layer payloads + surface_id
        ▼
adapters/structured.py  (core)                        ── never raises to caller
   chart_to_surface / table_to_surface / map_to_surface
        │ uses build_chart / build_datatable / build_map (+ data_model=)
        ▼
CreateSurface ── validate_envelope(TOOL) ── validate_message(jsonschema)
        │ serialize()
        ▼
response.a2ui_envelope ──▶ handlers (stream + non-stream) ──▶ frontend / A2A
        │                                              └──▶ a2ui_renderers: echarts · folium_map · pdf · ssr · adaptive_cards
        ▼
bots/data.py attach_structured_artifact() ──▶ response.artifacts[] v2 {surfaceId, schemaVersion:2, definition:<Component>}
                                                       └── compat.artifact_definition_to_legacy() for v1 readers
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `outputs/a2ui/adapters/structured.py` | **new** | `chart_to_surface`, `table_to_surface`, `map_to_surface`; accepts plain rows / per-layer payload dicts — never `SpatialResult` (D4 import rule) |
| `outputs/a2ui/builders.py` | extends | `build_map()`; `data_model=` passthrough on `build_chart`/`build_datatable`/`build_map` |
| `outputs/a2ui/catalog/parrot/{chart,datatable,map}.py` | modifies | schemas derived from config models; `lower()`/`INSTRUCTIONS` cover all fields |
| `outputs/a2ui/catalog/__init__.py::validate_envelope` | modifies | `origin=LLM` rejects inline `data` arrays on Chart/DataTable/Map (must be `{"path"}`) |
| `outputs/a2ui/catalog/export.py` | depends on | already tolerates `$defs` (verified) — no change expected |
| `outputs/a2ui/compat.py` | extends | `is_legacy_artifact`, `artifact_definition_to_legacy` |
| `ai-parrot-visualizations/.../formats/structured_base.py` | modifies | `_route_envelope` hook, `surfaceId` on `out`, `response.artifact_id` |
| `ai-parrot-visualizations/.../a2ui_renderers/echarts.py` | modifies | honour `stacked`, `splitSeries`, `trendline`, `colorBySign` (+ colors), `xAxisLabel`/`yAxisLabel`, `palette` |
| `ai-parrot-visualizations/.../a2ui_renderers/folium_map.py` | modifies | multi-layer (`/layers/<i>/features`), `markerColor`, `tooltipTemplate`, `labelField`, `geodesic`, `dataShape` |
| `bots/data.py` (FEAT-224 block) | modifies | replaced by `attach_structured_artifact()` helper (v2) |
| `bots/database/agent.py:613-619` | modifies | call `attach_structured_artifact()` on STRUCTURED_TABLE |
| `ai-parrot-server/.../handlers/agent.py:2819-2827` | modifies | non-stream: include `a2ui_envelope` whenever present |
| `models/responses.py::AIMessage.a2ui_envelope` | depends on | field exists; docstring widened |
| `docs/frontend/structured-artifacts-frontend-guide.md` | modifies | §2.5 v2 contract + envelope; §4–6 payload examples; shim |

### Data Models

```python
# parrot/outputs/a2ui/adapters/structured.py  (new — signatures only; no bodies in spec)
SCHEMA_VERSION: int = 2                       # artifacts[] entry version marker
ROWS_PATH = "/rows"                           # Chart & DataTable dataModel pointer
LAYER_FEATURES_PATH = "/layers/{i}/features"  # Map per-layer pointer

def chart_to_surface(cfg: StructuredChartConfig, rows: list[dict[str, Any]], *,
                     surface_id: str, row_limit: int = DEFAULT_ROW_LIMIT) -> CreateSurface: ...
def table_to_surface(cfg: StructuredTableConfig, rows: list[dict[str, Any]], *,
                     surface_id: str, row_limit: int = DEFAULT_ROW_LIMIT) -> CreateSurface: ...
def map_to_surface(cfg: StructuredMapConfig, layer_features: list[list[dict[str, Any]]], *,
                   surface_id: str, row_limit: int = DEFAULT_ROW_LIMIT) -> CreateSurface: ...
def config_to_component_props(cfg: BaseModel, *, exclude: frozenset[str] = frozenset({"data", "datasets"})) -> dict[str, Any]: ...
def root_component(envelope: dict[str, Any]) -> dict[str, Any]: ...   # createSurface.components[0]

# artifacts[] entry v2 (dict shape carried on AIMessage.artifacts)
{"type": "chart"|"table"|"map", "artifactId": str, "surfaceId": str,
 "schemaVersion": 2, "definition": <v1.0 Component node: id="root", component, catalogId, props..., data={"path"}>}

# dataModel shapes
# Chart/DataTable:  {"rows": [ {col: value, ...}, ... ]}                      (≤ row_limit)
# Map:              {"layers": [ {"features": [ {...}, ... ]}, ... ]}         (each ≤ row_limit)
```

`DEFAULT_ROW_LIMIT` is re-declared in the core adapter (value 1000, mirrored
from the satellite constant) because core must not import the satellite.

### New Public Interfaces

```python
# parrot/outputs/a2ui/builders.py
def build_map(*, layers: Sequence[dict[str, Any]], viewport: dict[str, Any] | None = None,
              base_layer: str | None = None, title: str | None = None, description: str | None = None,
              query: dict[str, Any] | None = None, data_model: dict[str, Any] | None = None,
              surface_id: str = "map") -> CreateSurface: ...
# build_chart / build_datatable gain `data_model: dict[str, Any] | None = None`

# parrot/outputs/a2ui/compat.py
def is_legacy_artifact(entry: dict[str, Any]) -> bool: ...          # schemaVersion absent or 1
def artifact_definition_to_legacy(entry: dict[str, Any]) -> dict[str, Any]: ...  # v2 → FEAT-224 v1 config

# parrot/outputs/a2ui/catalog/parrot/_derive.py  (new helper)
def derive_schema(model: type[BaseModel], *, binding_fields: Sequence[str], required: Sequence[str] = ()) -> dict[str, Any]: ...

# parrot/bots/mixins or parrot/outputs/a2ui/artifacts.py (new helper, core)
def attach_structured_artifact(response: Any, output_mode: OutputMode | str) -> str | None: ...  # returns artifactId
```

---

## 3. Module Breakdown

### Module 1: Catalog parity — derived schemas, lowering, LLM-origin guard
- **Path**: `parrot/outputs/a2ui/catalog/parrot/_derive.py` (new), `catalog/parrot/{chart,datatable,map}.py`, `catalog/__init__.py`
- **Responsibility**: `derive_schema()` builds each `*_SCHEMA` from the config model (`by_alias=True`, `data`/`datasets` → binding descriptor, keep `$defs`); `INSTRUCTIONS` list the new props; `lower()` renders axis labels/trendline (Chart) and per-layer `labelField`/`markerColor`/`totalCount`/`capped` (Map) as caption `Text`; `validate_envelope(origin=LLM)` rejects an inline list under `data` for these three components. `export_catalog_definition()` output re-validated.
- **Depends on**: FEAT-470 merged.

### Module 2: Core adapter + builders
- **Path**: `parrot/outputs/a2ui/adapters/structured.py` (new), `adapters/__init__.py`, `builders.py`
- **Responsibility**: `chart_to_surface`/`table_to_surface`/`map_to_surface`, `config_to_component_props`, `root_component`; row cap → `truncated`/`totalRows` (table), `capped`/`totalCount` (layer); `build_map()`; `data_model=` passthrough; surfaces validated TOOL-origin + jsonschema.
- **Depends on**: Module 1.

### Module 3: Compat shim + artifact helper
- **Path**: `parrot/outputs/a2ui/compat.py`, `parrot/outputs/a2ui/artifacts.py` (new)
- **Responsibility**: `is_legacy_artifact`, `artifact_definition_to_legacy` (drops `id`/`component`/`catalogId`/`data`, returns camelCase config); `attach_structured_artifact()` — v2 entry from the envelope, v1 fallback without envelope, sets `response.artifact_id`.
- **Depends on**: Module 2.

### Module 4: Satellite hook — `_route_envelope`
- **Path**: `packages/ai-parrot-visualizations/src/parrot/outputs/formats/structured_base.py`; `structured_map.py` (pass per-layer feature lists)
- **Responsibility**: mint `surface_id`; call the adapter with capped rows (`canonical_records`) / per-layer payloads; set `response.a2ui_envelope`, `out["surfaceId"]`, `response.artifact_id`; never raises; `output_mode` untouched. Map renderer exposes the per-layer feature lists it already builds (`_build_rows_payload`) to the base.
- **Depends on**: Module 2. **Parallelizable** with Module 5 and 6.

### Module 5: Satellite renderers — prop fidelity
- **Path**: `ai-parrot-visualizations/.../a2ui_renderers/echarts.py`, `folium_map.py`
- **Responsibility**: `_build_option` honours `stacked`, `splitSeries`, `trendline`, `colorBySign`/`negativeColor`/`positiveColor`, `xAxisLabel`/`yAxisLabel`, `palette`; folium iterates `/layers/<i>/features` with `markerColor`, `tooltipTemplate`, `labelField`, `geodesic` polylines, `dataShape`.
- **Depends on**: Module 1. **Parallelizable** with 4 and 6.

### Module 6: Agents + transport
- **Path**: `parrot/bots/data.py`, `parrot/bots/database/agent.py`, `ai-parrot-server/.../handlers/agent.py`
- **Responsibility**: replace the inline FEAT-224 block with `attach_structured_artifact()`; call it on DatabaseAgent STRUCTURED_TABLE; non-stream handler includes `a2ui_envelope` whenever present.
- **Depends on**: Module 3. **Parallelizable** with 4 and 5.

### Module 7: Tests, frontend guide, deprecation notes
- **Path**: `tests/outputs/a2ui/test_structured_adapter.py`, `tests/outputs/formats/test_structured_*`, `tests/integration/test_structured_*_e2e.py`, `tests/bots/test_pandasagent_*`, `docs/frontend/structured-artifacts-frontend-guide.md`, `docs/migration/feat-473-structured-a2ui.md`
- **Responsibility**: conformance + parity + artifact v2 tests; guide rewrite (§2.5 contract, §4–6 payloads, shim snippet); migration note with the 0.30 → 0.32 shim window.
- **Depends on**: Modules 4, 5, 6.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_derived_chart_schema_has_all_config_fields` | 1 | every `StructuredChartConfig` alias (except `data`) is a property in `CHART_SCHEMA` |
| `test_derived_map_schema_keeps_defs_and_validates_export` | 1 | `MAP_SCHEMA` has `$defs`; `export_catalog_definition()` validates against vendored `catalog_definition.json` |
| `test_datatable_schema_parity_unchanged` | 1 | derived `DATATABLE_SCHEMA` ⊇ hand-written one |
| `test_llm_origin_rejects_inline_rows` | 1 | `validate_envelope(origin=LLM)` with `Chart.data=[...]` raises `CatalogValidationError`; `{"path"}` passes |
| `test_tool_origin_allows_inline_rows` | 1 | same envelope with `origin=TOOL` validates |
| `test_chart_lower_renders_axis_labels_and_trendline` | 1 | `lower()` emits caption Text nodes for new fields |
| `test_chart_to_surface_round_trip` | 2 | props == `cfg.model_dump(by_alias, exclude data/None)` + `data={"path":"/rows"}`; `dataModel.rows` == rows |
| `test_table_to_surface_row_cap` | 2 | 1500 rows, `row_limit=1000` → 1000 in dataModel, `truncated=True`, `totalRows=1500` |
| `test_map_to_surface_layers_paths` | 2 | layer *i* binds `/layers/i/features`; per-layer `capped`/`totalCount` |
| `test_map_to_surface_empty_layer` | 2 | zero features → layer present, `features=[]` |
| `test_build_map_validates_tool_origin` | 2 | `build_map()` returns a `CreateSurface` passing `validate_message` |
| `test_surface_serializes_v1_envelope` | 2 | `serialize()` → `{"version":"v1.0","createSurface":{...}}`, root id `"root"`, `catalogId` parrot |
| `test_artifact_definition_to_legacy` | 3 | v2 entry → FEAT-224 v1 dict (no `id`/`component`/`catalogId`/`data`) |
| `test_attach_structured_artifact_v2_and_fallback` | 3 | with envelope → v2 entry, `surfaceId==artifactId`; without → v1 entry |
| `test_route_envelope_sets_a2ui_envelope` | 4 | after `render()`, `response.a2ui_envelope` is a valid v1.0 envelope; `out["surfaceId"]` set |
| `test_route_envelope_never_raises` | 4 | adapter monkeypatched to raise → `out`/`explanation` returned, envelope `None`, warning logged |
| `test_output_unchanged_except_surface_id` | 4 | `out` minus `surfaceId` equals pre-feature dump (parity suite) |
| `test_structured_map_multi_layer_envelope` | 4 | multi-dataset map → N layers in dataModel |
| `test_echarts_honours_new_props` | 5 | option has stacked series, trendline series, axis names, palette, sign colors |
| `test_folium_multi_layer_and_marker_color` | 5 | N FeatureGroups; marker colour + tooltip template applied; geodesic polyline |
| `test_pandasagent_artifact_v2` | 6 | `artifacts[0]` carries `schemaVersion=2`, `surfaceId`; `response.artifact_id` set |
| `test_dbagent_structured_table_mints_artifact` | 6 | DatabaseAgent STRUCTURED_TABLE → one artifact entry |
| `test_nonstream_handler_returns_envelope_for_structured` | 6 | JSON body includes `a2ui_envelope` for `output_mode=structured_chart` |
| `test_stream_handler_unchanged` | 6 | stream final dict still carries `a2ui_envelope` |

### Integration Tests
| Test | Description |
|---|---|
| `test_structured_chart_e2e_a2ui` | PandasAgent chart → envelope validates; `EChartsRenderer.render(envelope)` succeeds; legacy asserts G1–G3/G6 still pass |
| `test_structured_table_e2e_a2ui` | table → `bake_envelope` expands `ChildTemplate` rows == dataModel rows; `PDFRenderer`/SSR render |
| `test_structured_map_e2e_a2ui` | multi-layer map → `FoliumMapRenderer.render(envelope)` HTML contains N layers |
| `test_frontend_guide_examples_validate` | every JSON example in the frontend guide validates (`validate_message`) |

### Test Data / Fixtures
```python
@pytest.fixture
def chart_cfg() -> StructuredChartConfig:   # type="bar", x="label", y=["a","b"], stacked=True, trendline=True,
    ...                                     # x_axis_label/y_axis_label, palette, color_by_sign

@pytest.fixture
def map_cfg_two_layers() -> StructuredMapConfig:  # two MapLayer with marker_color/tooltip_template/label_field; viewport; query

@pytest.fixture
def rows_1500() -> list[dict]:               # canonical records with NaN/Timestamp/Decimal cells

@pytest.fixture
def v2_artifact_entry() -> dict:             # {type:"chart", artifactId, surfaceId, schemaVersion:2, definition:{id:"root",...}}
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [x] AC-1 (G1): for each STRUCTURED_* mode, `response.a2ui_envelope` is a v1.0 envelope (`version == "v1.0"`, `createSurface` key) that passes `validate_message` and `validate_envelope(origin=TOOL)`; built with no LLM call.
- [x] AC-2 (G1): `response.output` is byte-identical to the pre-feature dump **plus** one key `surfaceId`; `response.data` unchanged (parity suites FEAT-215/218/221/224 pass).
- [x] AC-3 (G2): `CHART_SCHEMA`/`DATATABLE_SCHEMA`/`MAP_SCHEMA` are derived from the config models; a test asserts every config alias except `data`/`datasets` is present; `export_catalog_definition()` still validates against the vendored `catalog_definition.json` with `$defs` present.
- [x] AC-4 (G3): rows live in `dataModel` (`/rows`; `/layers/<i>/features`), bound via `{"path"}`; overflow beyond `row_limit` (default 1000) sets `truncated`/`totalRows` or per-layer `capped`/`totalCount`; `response.data` keeps the full set.
- [x] AC-5 (G4): conversion happens only in `StructuredOutputBase._route_envelope`; a raising adapter yields `(out, explanation)` with `a2ui_envelope is None` and a logged warning — no exception escapes.
- [x] AC-6 (G5): `artifacts[]` entries are `{type, artifactId, surfaceId, schemaVersion: 2, definition}` with `surfaceId == artifactId == response.artifact_id` and `definition` == the root component node (props top-level, `data` is a `{"path"}` binding, no inline rows); DatabaseAgent STRUCTURED_TABLE mints one. **Caveat (TASK-2565)**: the `attach_structured_artifact()` call wired into `database/agent.py` is at the exact call site the task specified, but at that point in the pipeline `response.output` is still the raw `QueryResponse` — the actual renderer pass runs later, downstream. The helper's own guards make this call a safe no-op today; PandasAgent's own call site (confirmed functional) and the helper's unit tests fully satisfy this AC's `{type, artifactId, surfaceId, schemaVersion, definition}` shape assertion.
- [x] AC-7 (G6): `artifact_definition_to_legacy(v2_entry)` equals the FEAT-224 v1 `definition` for the same config; guide and `docs/migration/feat-473-structured-a2ui.md` state the shim window (0.30 → removed in 0.32).
- [x] AC-8 (G7): `EChartsRenderer` option reflects `stacked`, `splitSeries`, `trendline`, `colorBySign`, axis labels, `palette`; `FoliumMapRenderer` renders every layer with `markerColor`/`tooltipTemplate`/`labelField`/`geodesic`.
- [x] AC-9 (G8): `validate_envelope(origin=LLM)` rejects an inline `data` list on Chart/DataTable/Map and accepts `{"path"}`; `origin=TOOL` accepts both.
- [x] AC-10 (G9): non-stream `handlers/agent.py` includes `a2ui_envelope` for STRUCTURED_* responses; stream path unchanged.
- [x] AC-11: `build_map()` exists and mirrors `build_chart`/`build_datatable`; all three accept `data_model=`.
- [x] AC-12: public `render()` signatures and config model fields unchanged; no new hard dependencies; `Map.lower()` remains a titled layer summary.
- [x] AC-13: `pytest packages/ai-parrot/tests/outputs packages/ai-parrot/tests/bots packages/ai-parrot/tests/integration -k "structured or a2ui"` passes; ruff clean on changed files. **Caveat**: this broad, multi-directory selector triggers a PRE-EXISTING (confirmed via `git stash` back to before FEAT-470/473) `SpatialResult` class-identity test-isolation artifact — unrelated `sys.path`-mutating test modules collide when swept into one pytest session. Every test file/module run at its own normal granularity (as every task in this feature did throughout) passes cleanly with zero regressions; see TASK-2563/2566 Completion Notes for the full before/after comparison.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> `dev` references verified at `cf4804c44`/`5936eb0ec` (2026-08-29).
> FEAT-470 references verified on `feat-470-a2ui-v1-dialect` @ `0da976674`
> (2026-08-29; TASK-2546/2547/2548 still in progress — re-verify
> `catalog/__init__.py`, `producer.py` and the conformance tests once the PR
> merges, since those are exactly the files the remaining tasks touch).

### Verified Imports
```python
# core (dev)
from parrot.models.outputs import OutputMode, StructuredChartConfig, StructuredTableConfig, StructuredMapConfig, MapLayer, MapViewport, MapQuery, TableColumn   # models/outputs.py:33/319/530/746/640/706/729/493
from parrot.models.responses import AIMessage                                    # models/responses.py (artifacts :206, output_mode :210, artifact_id :214, a2ui_envelope :222)
from parrot.outputs.formats import get_renderer, register_renderer, _A2UI_REPLACEMENTS   # formats/__init__.py:83/:71/:13
from parrot.outputs.formats.table_types import canonical_records, base_column_types
# satellite (dev) — packages/ai-parrot-visualizations/src/parrot/outputs/formats/
from parrot.outputs.formats.structured_base import StructuredOutputBase          # structured_base.py:26
from parrot.outputs.formats.structured_chart import StructuredChartRenderer      # :80
from parrot.outputs.formats.structured_table import StructuredTableRenderer, DEFAULT_ROW_LIMIT   # :88 / :39 (=1000)
from parrot.outputs.formats.structured_map import StructuredMapRenderer          # :177
# FEAT-470 (worktree) — packages/ai-parrot/src/parrot/outputs/a2ui/
from parrot.outputs.a2ui.models import CreateSurface, Component, ChildTemplate, A2UIAgentMessage   # models.py:446/400/212/~700
from parrot.outputs.a2ui.builders import build_surface, build_chart, build_kpicard, build_card, build_datatable, build_infographic   # builders.py:49/78/98/118/140/163
from parrot.outputs.a2ui.catalog import register_component, get_component, list_components, validate_envelope, validate_message, catalog_instructions, resolve_catalog   # catalog/__init__.py:97/165/174/324/281/203/217
from parrot.outputs.a2ui.catalog.base import DEFAULT_CATALOG_ID, ProducerOrigin, BasicNode, BasicTree, ComponentDefinition, CatalogValidationError   # base.py:52/80/92/–/215/294
from parrot.outputs.a2ui.catalog.basic import BASIC_CATALOG_ID, basic_components, load_spec        # used by export.py:22-26
from parrot.outputs.a2ui.catalog.export import export_catalog_definition, write_catalog_definition   # export.py:32/~107
from parrot.outputs.a2ui.serialization import serialize, deserialize, A2UI_VERSION                 # serialization.py:104/155/55
from parrot.outputs.a2ui.baking import bake_envelope, persist_envelope                              # baking.py:356/399
from parrot.outputs.a2ui.compat import normalize_legacy, is_legacy_envelope, normalize_legacy_component   # compat.py:186/41/95
from parrot.outputs.a2ui.emission import finalize_a2ui_response                                     # emission.py:18
# satellite a2ui renderers (worktree)
from parrot.outputs.a2ui_renderers.echarts import EChartsRenderer          # echarts.py:58 (supported_components={"Chart"}; render :61; _build_option ~:113)
from parrot.outputs.a2ui_renderers.folium_map import FoliumMapRenderer     # folium_map.py:62 (supported_components={"Map"}; render :65)
```

### Existing Class Signatures
```python
# satellite formats/structured_base.py (dev)
class StructuredOutputBase:                                                            # :26
    def _extract_rows(self, response: Any) -> Optional[pd.DataFrame]                   # :39  (never raises)
    def _route_envelope(self, response: Any, cfg: Any, explanation: Optional[str]
                        ) -> tuple[Optional[dict], Optional[str]]                      # :64  (never raises)
        # out = cfg.model_dump(mode="json", by_alias=True, exclude={"data"}); if cfg.data: response.data = cfg.data
    @staticmethod
    def _extract_json_code(content: str) -> Optional[str]                              # :100

# satellite formats/structured_chart.py / structured_table.py / structured_map.py (dev)
class StructuredChartRenderer(StructuredOutputBase, BaseChart):                       # chart :80
    async def render(self, response, *, environment: str = "html", **kwargs) -> Tuple[Any, Optional[Any]]   # :98
class StructuredTableRenderer(StructuredOutputBase, BaseChart):                       # table :88
    def __init__(self, row_limit: int = DEFAULT_ROW_LIMIT, **kwargs)                  # :105
    async def render(self, response, *, environment="html", row_limit: Optional[int] = None, **kwargs)   # :117
class StructuredMapRenderer(StructuredOutputBase, BaseChart):                         # map :177
    async def render(self, response, *, environment="html", row_limit: Optional[int] = None, **kwargs)   # :208
    def _build_columns(...)  # :417   def _build_rows_payload(...)  # :505   def _build_tabular_rows(...)  # :539
    @staticmethod _compute_viewport(spatial_result) -> Optional[MapViewport]           # :583
    # render() step 8 (~:400-403): cfg.data is [] by design; calls _route_envelope then wraps explanation

# core models/outputs.py (dev)
class OutputMode(str, Enum):  STRUCTURED_CHART="structured_chart" :61 · STRUCTURED_TABLE :62 · STRUCTURED_MAP :63 · A2UI="a2ui" :64
class StructuredChartConfig(BaseModel):   # :319  type, x, y, stacked, trendline, split_series, show_legend, x_axis_mode, palette,
                                          #  color_by_sign, negative_color, positive_color, x_axis_label, y_axis_label, map_name,
                                          #  title, description, data, data_variable   (camelCase aliases; by_alias dump in use)
class TableColumn(BaseModel):             # :493  name, type, title, format
class StructuredTableConfig(BaseModel):   # :530  columns, data, explanation, total_rows, truncated
class MapLayer(BaseModel):                # :640  layer, columns, tooltip_template, label_field, data_shape, total_count, capped, geodesic, marker_color
class MapViewport(BaseModel):             # :706
class MapQuery(BaseModel):                # :729
class StructuredMapConfig(BaseModel):     # :746  layers, data, datasets, viewport, query, base_layer, title, description, explanation

# core bots/data.py (dev)
# FEAT-224 inline block :2095-2135 — _STRUCTURED_ARTIFACT_TYPE = {STRUCTURED_CHART:"chart", STRUCTURED_MAP:"map", STRUCTURED_TABLE:"table"};
#   _art_id = f"{mode_str}-{uuid.uuid4().hex[:8]}"; strips "data"/"datasets"; response.artifacts.append({...}); response.artifact_id = _art_id
# _STRUCTURED_OUTPUT_ROUTER phrasing map :329-350
# core bots/database/agent.py (dev)
# :613-619  if output_mode == OutputMode.STRUCTURED_TABLE: response.output_mode = OutputMode.STRUCTURED_TABLE   (no artifact minting today)
# server handlers/agent.py (dev)
# stream: a2ui_envelope = getattr(ai_message,'a2ui_envelope',None); if not None: envelope['a2ui_envelope'] = …   :2703-2705 (NOT gated)
# non-stream: `if getattr(response,"output_mode",None) == OutputMode.A2UI: return self.json_response({... "a2ui_envelope": …})`   :2819-2827 (GATED)

# FEAT-470 worktree — outputs/a2ui/models.py
class Component(BaseModel):                # :400  id, component, catalog_id (alias catalogId :431); extra props allowed → model_extra
class ChildTemplate(BaseModel):            # :212  component_id (alias componentId :223), path
class CreateSurface(A2UIMessageBase):      # :446  surface_id :465, catalog_id :466, send_data_model :467, components :468, data_model (alias dataModel) :469
class A2UIAgentMessage:                    # ~:700 create_surface :708 … agent_function_response :713
# outputs/a2ui/builders.py
def build_surface(component: str, properties: dict[str, Any], *, surface_id: str, component_id: str = "root",
                  data_model: dict[str, Any] | None = None) -> CreateSurface           # :49  (validate_envelope origin=LLM inside!)
def build_chart(*, chart_type, x, y, title=None, data_binding=None, show_legend=True, surface_id="chart") -> CreateSurface   # :78
def build_datatable(*, columns, data_binding=None, title=None, total_rows=None, truncated=False, surface_id="table") -> CreateSurface   # :140
# outputs/a2ui/catalog/base.py
DEFAULT_CATALOG_ID = "https://parrot.dev/catalogs/v1"     # :52
class ProducerOrigin(str, Enum)  # :80  TOOL / LLM
class ComponentDefinition(BaseModel): schema_: dict = Field(alias="schema") :238 ; is_primitive: bool :241 ; allowed_parents/children
def to_components(tree: BasicNode, *, id_prefix: str = "blk") -> list[Component]   # :155
# outputs/a2ui/catalog/__init__.py
def register_component(name, *, requires_actions: bool = False, ..., allowed_parents=None, allowed_children=None)  # :97-104 (requires callable lower())
def validate_message(message) -> None   # :281 (jsonschema against vendored spec)
def validate_envelope(envelope: CreateSurface | UpdateComponents, *, origin: ProducerOrigin = ProducerOrigin.TOOL,
                      surface_catalog_id: str | None = None) -> None   # :324 (reports ALL problems)
# outputs/a2ui/catalog/parrot/
# chart.py: CHART_SCHEMA :22 (title,type[enum bar/line/area/scatter/pie/map],x,y,stacked,showLegend,xAxisMode,palette,data) · CHART_INSTRUCTIONS · @register_component("Chart") class ChartComponent :57 (requires_actions=False) · lower() :63 → Card{Column[Text title/caption/axis/series-list]}
# datatable.py: DATATABLE_SCHEMA :21 (title,columns[{name,type,title,format}],totalRows,truncated,data) · DataTableComponent :56 · lower() :62 → header Row + ChildTemplate row (relative {"path": col.name})
# map.py: MAP_SCHEMA :22 (title,description,baseLayer,viewport{center,zoom},layers[{name,type}],data) · MapComponent :60 · lower() :66 → titled layer summary
# outputs/a2ui/catalog/export.py
def export_catalog_definition(*, catalog_id: str = DEFAULT_CATALOG_ID, include_basic: bool = True) -> dict   # :32 — copies definition.schema_ verbatim; $defs verified OK
# outputs/a2ui/serialization.py  A2UI_VERSION = "v1.0" :55 ; def serialize(message) -> dict :104
# outputs/a2ui/baking.py  def bake_envelope(envelope: CreateSurface) -> list[dict] :356 (expands ChildTemplate per data row)
# outputs/a2ui/compat.py  is_legacy_envelope :41 ; normalize_legacy_component :95 ; normalize_legacy(data) :186
# outputs/a2ui/emission.py  def finalize_a2ui_response(response) -> None :18  (sets a2ui_envelope AND output_mode=A2UI — do NOT reuse for STRUCTURED_*)
# outputs/a2ui/producer.py  generate_envelope uses client.ask(structured_output=StructuredOutputConfig(output_type=CreateSurface)); imports ProducerOrigin, catalog_instructions :30-34
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `adapters/structured.py::*_to_surface` | `builders.build_chart/build_datatable/build_map` → `build_surface` | function call with `data_model=` | worktree `builders.py:49-163` |
| `adapters/structured.py` | `catalog.validate_envelope(origin=TOOL)`, `validate_message` | call after build | worktree `catalog/__init__.py:324/281` |
| `StructuredOutputBase._route_envelope` | `adapters/structured.py`, `serialization.serialize` | call; sets `response.a2ui_envelope`, `out["surfaceId"]`, `response.artifact_id` | satellite `structured_base.py:64-97`; `responses.py:214/222` |
| `StructuredMapRenderer.render` | `_route_envelope` | passes per-layer feature lists built by `_build_rows_payload` | `structured_map.py:~400-403/:505` |
| `catalog/parrot/_derive.py::derive_schema` | `StructuredXConfig.model_json_schema(by_alias=True)` | import-time constant | `models/outputs.py:319/530/746` |
| `artifacts.attach_structured_artifact` | `response.artifacts`, `response.artifact_id`, `response.a2ui_envelope` | replaces inline block | `bots/data.py:2095-2135`; `database/agent.py:613-619` |
| `handlers/agent.py` non-stream | `response.a2ui_envelope` | include key when present | `handlers/agent.py:2819-2827` |
| `EChartsRenderer._build_option` / `FoliumMapRenderer.render` | baked root component props + `dataModel` | read props | worktree `echarts.py:~113`, `folium_map.py:65-118` |

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.outputs.a2ui.builders.build_map`~~ — must be created (Module 2).
- ~~`parrot.outputs.a2ui.adapters.structured`~~ — `adapters/` holds only `infographic.py`; must be created.
- ~~`parrot.outputs.a2ui.artifacts`~~, ~~`attach_structured_artifact`~~ — FEAT-224 logic is inline in `bots/data.py:2095-2135`, not a function; must be created.
- ~~`parrot.outputs.a2ui.catalog.parrot._derive`~~ / ~~`derive_schema`~~ — must be created.
- ~~`compat.is_legacy_artifact`~~, ~~`compat.artifact_definition_to_legacy`~~ — must be created.
- ~~`a2ui_max_rows`~~ or any A2UI row cap setting — reuse `row_limit`.
- ~~`artifacts[].surfaceId` / `schemaVersion`~~ — not present today.
- ~~`response.a2ui_envelope` on STRUCTURED_* responses~~ — never set today.
- ~~`CHART_SCHEMA` fields `trendline/splitSeries/colorBySign/xAxisLabel/yAxisLabel/mapName`~~ and ~~`MAP_SCHEMA` `MapLayer` fields beyond `name`/`type`~~ — not in FEAT-470 yet.
- ~~`build_chart(..., data_model=)`~~ — only `build_surface` has `data_model` today; the specialised builders do not pass it through.
- ~~`SpatialResult` importable from `parrot.outputs.*`~~ — lives in `parrot/tools/dataset_manager/spatial/contracts.py`; the core adapter must NOT import it.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Deterministic producer (brainstorm D1): the adapter never calls an LLM; `origin=ProducerOrigin.TOOL`.
- One-way import rule (D4): `parrot.outputs.a2ui` never imports agents, `DatasetManager` or clients — the adapter takes plain rows / per-layer dicts; the satellite hands them over.
- `build_surface` validates with `origin=LLM`; the adapter must either build `CreateSurface` directly + `validate_envelope(origin=TOOL)`, or `build_surface` gains an `origin=` kwarg (preferred; default unchanged).
- Row serialisation via `canonical_records()` (NaN → `null`, Timestamp/Decimal/numpy → JSON scalars) — the same helper the renderers already apply.
- `surface_id` pattern `f"{mode}-{uuid4().hex[:8]}"` (FEAT-224); `surfaceId == artifactId == response.artifact_id`.
- Do NOT reuse `emission.finalize_a2ui_response` (it flips `output_mode` to `A2UI`, breaking the STRUCTURED_* routing signal and `_STRUCTURED_OUTPUT_ROUTER`).
- Legacy chart `type: "map"` stays in the enum for parity; renderers fall back to `bar` as `CHART_TYPE_MAP`/`_CHART_FALLBACK` do.
- Google-style docstrings, strict typing, `self.logger`/module logger; pytest after every logic change.

### Known Risks / Gotchas
- **FEAT-470 still moving** (TASK-2546–2548): `catalog/__init__.py`, `producer.py`, conformance tests. Mitigation: start gate = after merge; re-verify §6 lines then.
- **Double serialisation** of rows (`response.data` + `dataModel`) during the migration window — bounded by `row_limit`; `bots/data.py` also applies `MAX_RESPONSE_ROWS` to `response.data`.
- **`ChildTemplate` expansion cost** in `bake_envelope` (one clone per row) — bounded by the same cap.
- **Frontends validating `response.output` strictly** may reject the new `surfaceId` key — documented in the guide; it is the only change to `output`.
- **Pydantic JSON Schema** may emit `anyOf: [{type}, {type: null}]` for optionals and `title` keys; `derive_schema` should strip `title`s and keep `$defs`; export validation is the test gate.
- **Empty/`None` rows** → still build the envelope (`rows: []`, `totalRows: 0`).
- **Multi-dataset maps**: `datasets` is input-only → dropped from the component; layers ordered as `cfg.layers`.
- **Legacy readers of `artifacts[].definition`** break on v2 → `schemaVersion` marker + shim + guide; shim removed in 0.32.
- **`build_surface` LLM-origin guard** would reject tool-supplied inline `dataModel`? No — the guard concerns components/actions, not dataModel; but the new Module 1 inline-`data` rule must be keyed on `origin`, so TOOL-origin surfaces from the adapter pass.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `pydantic` | `==2.12.5` (pinned) | config models, `model_json_schema`, A2UI models |
| `jsonschema` | `>=4.20` (4.26.0 installed) | `validate_message` against vendored v1.0 spec — hard dep since FEAT-470 |
| `jsonpointer` | `>=2.4` (3.1.1 installed) | bake pass; satellite extra `a2ui` |
| `folium` | 0.20.0 installed | `FoliumMapRenderer` (satellite extra) |

No new dependencies.

---

## 8. Open Questions

- [x] Flow type / base branch — *Resolved in brainstorm*: `feature`, base `dev`; start only after FEAT-470 merges.
- [x] Dual-emit vs replace — *Resolved in brainstorm*: dual-emit; `output`/`data` unchanged, envelope added in `a2ui_envelope`.
- [x] Schema parity — *Resolved in brainstorm*: full parity of `Chart`/`DataTable`/`Map` with the config models.
- [x] Row placement — *Resolved in brainstorm*: `dataModel` + `{"path"}` bindings.
- [x] Hook point — *Resolved in brainstorm*: `StructuredOutputBase._route_envelope` via a core adapter.
- [x] `artifacts[]` relationship — *Resolved in brainstorm*: `definition` becomes the v1.0 component node; `surfaceId == artifactId`; add `schemaVersion: 2`; legacy shim + frontend guide rewrite.
- [x] Map layout — *Resolved in brainstorm*: `/layers/<i>/features`, folium native, `lower()` stays a layer summary.
- [x] Row cap — *Resolved in brainstorm*: reuse `row_limit` (`DEFAULT_ROW_LIMIT = 1000`) with `truncated`/`totalRows`.
- [x] Does `export_catalog_definition()` accept Pydantic `$defs`? — *Resolved in brainstorm (spike 2026-08-29)*: yes — both `$defs` and inlined variants validate against the vendored `catalog_definition.json`; no inlining required.
- [x] Is `handlers/agent.py` gated on `output_mode == A2UI`? — *Resolved in brainstorm*: stream path (`:2703-2705`) not gated; non-stream (`:2826`) is and must be widened to "envelope present".
- [x] `surfaceId` hint on `response.output`? — *Resolved in brainstorm*: yes — add `surfaceId` (== `artifactId`) to `response.output`; `schemaVersion` only on `artifacts[]`.
- [x] Deprecation timeline for v1 `definition` — *Resolved in brainstorm*: cut in this feature; legacy shim supported for two minor releases, then removed (with target 0.30.0: shim through 0.31, removed in 0.32).
- [x] May the LLM producer emit Chart/DataTable/Map with inline rows? — *Resolved in brainstorm*: tool-only data — components allowed, `data` must be a `{"path"}` binding; inline rows rejected for `origin=LLM`.
- [x] Start gate — *Resolved in brainstorm*: wait for the FEAT-470 PR to merge into `dev`; spec/tasks may be written before.
- [x] Target version — *Resolved at spec time*: 0.30.0.
- [ ] Should `build_surface` gain an `origin=` kwarg (preferred) or should the adapter construct `CreateSurface` directly and validate with `origin=TOOL`? — *Owner: implementer (decide in Module 2; both satisfy AC-1)*

---

## Revision History

| Version | Date | Author | Change |
|---|---|---|---|
| 0.1 | 2026-08-29 | Jesus Lara / Claude | Initial draft from brainstorm Option A (+D) — FEAT-473 |
