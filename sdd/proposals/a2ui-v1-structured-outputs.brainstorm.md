---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Brainstorm: A2UI v1.0 for STRUCTURED_CHART / STRUCTURED_TABLE / STRUCTURED_MAP

**Date**: 2026-08-29
**Author**: Jesus Lara (with Claude)
**Status**: exploration
**Recommended Option**: A (with the schema-derivation technique from Option D)
**Depends on**: FEAT-470 `a2ui-v1-dialect` — starts only after its PR merges to `dev` (start gate, Q5)
**Related**: FEAT-215 (STRUCTURED_CHART), FEAT-218 (STRUCTURED_TABLE), FEAT-221 (STRUCTURED_MAP), FEAT-224 (structured `artifacts[]` envelope), FEAT-273 (A2UI core)

---

## Problem Statement

`OutputMode.STRUCTURED_CHART`, `STRUCTURED_TABLE` and `STRUCTURED_MAP` are the
live, deterministic "data → visual config" path used by `PandasAgent`
(`bots/data.py`) and `DatabaseAgent` (`bots/database/agent.py`). Today they
produce a **proprietary JSON contract**: the renderer dumps a
`StructuredChartConfig` / `StructuredTableConfig` / `StructuredMapConfig` into
`response.output` (camelCase, `data` excluded), rows go to `response.data`, and
FEAT-224 mirrors the config into `response.artifacts[] = {type, artifactId,
definition}`.

They are **not A2UI at all**, even though `outputs/formats/__init__.py`
already marks all three as deprecated "in favour of `OutputMode.A2UI` with the
Chart/DataTable/Map catalog component" (FEAT-273). The intended replacement
never materialised because the A2UI wire was itself a dialect until FEAT-470.

FEAT-470 (13 of 17 tasks landed on `feat-470-a2ui-v1-dialect` as of
2026-08-28) now gives us a spec-conformant v1.0 wire, a vendored official
schema + `jsonschema` validation, a `catalog/parrot/` with `Chart`, `DataTable`
and `Map` components whose vocabulary is *adapted from* the structured config
models, a bake pass that resolves `{"path"}` bindings and `ChildTemplate`
rows, and satellite renderers (`echarts`, `folium_map`, `interactive_html`,
`ssr_html`, `pdf`, `adaptive_cards`) that consume baked v1.0 components.

What is missing is the **bridge**: a STRUCTURED_* response never becomes a
`CreateSurface`, so none of that machinery (external A2UI renderers, PDF/SSR
delivery via `Agent.notification()`, Adaptive Cards for Teams, deep-link
degradation) is reachable from the most-used data agents. Two concrete gaps
make a naïve bridge lossy:

1. **Schema parity gap.** The FEAT-470 `CHART_SCHEMA` / `MAP_SCHEMA` /
   `DATATABLE_SCHEMA` cover only a subset of the config fields. Missing on
   Chart: `trendline`, `split_series`, `color_by_sign`, `negative_color`,
   `positive_color`, `x_axis_label`, `y_axis_label`, `map_name`,
   `description`, `data_variable`. Missing on Map: `MapLayer.columns`,
   `tooltip_template`, `label_field`, `data_shape`, `total_count`, `capped`,
   `geodesic`, `marker_color`; `StructuredMapConfig.datasets`, `query`,
   `explanation`. `DataTable` is already at parity (`columns{name,type,title,
   format}`, `totalRows`, `truncated`).
2. **No `build_map` builder** and no deterministic "config → surface"
   adapter exists (`outputs/a2ui/adapters/` only holds `infographic.py`).

**Who is affected**: frontend consumers of AgentTalk structured artifacts
(`docs/frontend/structured-artifacts-frontend-guide.md`), any channel that
wants PDF/Teams/SSR delivery of data-agent results, and third-party A2UI
renderers.

## Constraints & Requirements

Decisions locked during discovery (Rounds 0–3):

- **Flow**: `type: feature`, `base_branch: dev`. **Start gate**: the worktree is
  created only after FEAT-470 has merged to `dev` (no rebase over in-flight
  catalog/producer changes).
- **Dual-emit** (R1a): `response.output` (config JSON) and `response.data`
  (rows) keep their current shape. A v1.0 `CreateSurface` is **added** in
  `response.a2ui_envelope`, built **deterministically** — zero LLM
  involvement (D1 of the original A2UI brainstorm: tools own their data).
- **Full schema parity** (R1b): the parrot-catalog `Chart` / `DataTable` /
  `Map` schemas and their `lower()` carry every `StructuredXConfig` field; no
  information is lost between `response.output` and the envelope.
- **Rows live in `dataModel`** (R1c) and components bind via
  `{"path": "/…"}`; the envelope is standalone-renderable by any v1.0
  renderer.
- **Hook point** (R2a): the conversion runs inside
  `StructuredOutputBase._route_envelope` (satellite `structured_base.py`) via
  a **core** adapter so every renderer path benefits (PandasAgent,
  DatabaseAgent, direct `render()` callers).
- **`artifacts[].definition` changes shape** (R2b/R3a): it becomes the v1.0
  parrot-catalog **Component node** (props top-level, `data: {"path"}`), the
  entry gains `surfaceId` (== `artifactId`) and a `schemaVersion: 2` marker;
  the full `CreateSurface` lives once in `response.a2ui_envelope`. This is the
  **only breaking change** of the feature.
- **Consumer cushion** (R3b): rewrite the frontend guide, and ship a
  one-call legacy adapter (`normalize_legacy`-style) that turns a v2
  artifact entry back into the FEAT-224 v1 camelCase config for old
  frontends.
- **Map layout** (R2c): one `dataModel` path per layer
  (`/layers/<i>/features`); `folium_map` is the native renderer;
  `Map.lower()` stays a titled layer summary for static surfaces.
- **`response.output` hint** (Q2): the legacy config mirror additionally
  carries `surfaceId` (same value as `artifactId`) so consumers reading only
  `output` can correlate with the envelope. No other key changes.
- **Deprecation** (Q3): v1 `definition` shape is cut in this feature
  (target 0.29.x); `artifact_definition_to_legacy()` shim + guide supported
  through 0.31, then the shim is removed.
- **LLM producer** (Q4): the FEAT-470 LLM producer may emit
  `Chart`/`DataTable`/`Map`, but `data` MUST be a `{"path"}` binding into a
  tool-supplied `dataModel`; inline rows from `origin=LLM` are rejected by
  `validate_envelope` (D1: tools own data). Components stay
  `requires_actions=False`.
- **Row cap** (R2d): reuse the renderer's existing `row_limit`
  (`DEFAULT_ROW_LIMIT = 1000`, `structured_table.py:39`). On overflow the
  envelope carries the capped rows with `truncated: true` + `totalRows`
  (table) / `capped` + `total_count` (map layer); the full set remains only
  in `response.data`.
- **Never raises**: `_route_envelope` is documented "never raises"; a failed
  envelope build must log and leave `a2ui_envelope = None`, never break the
  legacy path.
- No new hard dependencies: `pydantic 2.12.5`, `jsonschema 4.26.0`,
  `jsonpointer 3.1.1` already present (FEAT-470 made `jsonschema` a hard dep
  of core).
- Public API of the three renderers (`render(response, *, environment,
  row_limit, **kwargs) -> (out, explanation)`) and of the config models is
  unchanged.

---

## Options Explored

### Option A: Core adapter invoked from `StructuredOutputBase._route_envelope`

Add `parrot/outputs/a2ui/adapters/structured.py` in **core** with three pure
functions — `chart_to_surface(cfg, rows, *, surface_id, row_limit)`,
`table_to_surface(cfg, rows, …)`, `map_to_surface(cfg, layers_payload, …)` —
each returning a validated `CreateSurface` (root component id `"root"`,
`catalogId = DEFAULT_CATALOG_ID`, `dataModel` populated, `validate_envelope(…,
origin=ProducerOrigin.TOOL)`). `_route_envelope` (satellite) calls the
adapter after the existing dump, stores `serialize(surface)` in
`response.a2ui_envelope`, and returns `(out, explanation)` exactly as today.
`bots/data.py` FEAT-224 block reads the component node from the envelope to
fill `artifacts[].definition` (v2). Widen the three catalog schemas + `lower()`
to full parity and add `build_map` next to `build_chart`/`build_datatable`.

✅ **Pros:**
- Single conversion point; every producer of a STRUCTURED_* response gets an
  envelope (PandasAgent, DatabaseAgent, tests calling `render()` directly).
- Adapter lives in core next to `builders.py`/`baking.py`, so it can be unit-
  tested without the satellite and reused by future tools (D1 dual producers).
- The satellite change is ~10 lines inside an already "never raises" helper.
- Envelope is standalone: `echarts`/`folium_map`/`pdf` renderers and external
  renderers consume it with no knowledge of `response.data`.

❌ **Cons:**
- Core adapter must import the config models (`parrot.models.outputs`) — fine
  (same distribution), but it couples `outputs/a2ui` to `models.outputs`.
- Rows are serialised twice (`response.data` + `dataModel`) until the legacy
  mirror is retired — bounded by `row_limit`.
- Map: `SpatialResult` lives in `tools/dataset_manager/spatial/contracts.py`;
  the adapter must accept the already-built per-layer payload dicts the map
  renderer produces (`_build_rows_payload`), not the `SpatialResult` object,
  to respect the "outputs core never imports DatasetManager" rule (D4).

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` 2.12.5 | `CreateSurface`/`Component` models, config models | pinned in core |
| `jsonschema` 4.26.0 | `validate_message` against vendored v1.0 spec | hard dep since FEAT-470 TASK-2534 |
| `jsonpointer` 3.1.1 | bake pass path resolution (already used by `baking.py`) | satellite extra `a2ui`; core lazy-imports |

🔗 **Existing Code to Reuse:**
- `outputs/a2ui/builders.py` — `build_surface()` (root id, catalogId, TOOL/LLM validation) as the envelope constructor; `build_chart`/`build_datatable` as the shape template for a new `build_map`.
- `outputs/a2ui/catalog/parrot/{chart,datatable,map}.py` — extend `*_SCHEMA`, `*_INSTRUCTIONS`, `lower()`.
- `outputs/a2ui/serialization.py::serialize` — dict for `response.a2ui_envelope`.
- `outputs/a2ui/compat.py::normalize_legacy` — pattern for the artifact v2→v1 shim.
- `outputs/a2ui/emission.py::finalize_a2ui_response` — reference for how `a2ui_envelope` is placed (we do NOT change `output_mode`, unlike this helper).
- `formats/structured_base.py::_route_envelope` — hook point.
- `bots/data.py:2095-2135` — FEAT-224 artifact minting (update to v2 shape).

---

### Option B: Agent-side attachment (next to FEAT-224 in `bots/data.py`)

Keep renderers untouched. In `PandasAgent` (and `DatabaseAgent`) after the
renderer returns, re-parse `content` (the config dict) plus `response.data`,
build the `CreateSurface` with the same core adapter, and set
`response.a2ui_envelope` + `artifacts[]` v2 in one place.

✅ **Pros:**
- Zero satellite changes; the satellite stays a pure "config producer".
- All FEAT-224 logic (artifact id, definition) and the envelope are minted in
  one block, easy to reason about.

❌ **Cons:**
- Two agents to patch (`data.py`, `database/agent.py`) and any future agent
  that uses the renderers must remember to do it → the exact class of drift
  FEAT-224 already suffers (the DatabaseAgent path today does *not* mint
  artifacts).
- The agent has to reverse-engineer the config from `content` (a dumped dict)
  instead of holding the typed `cfg`, re-validating with Pydantic.
- Direct `render()` callers (tests, tools, `Agent.notification()` pipelines)
  get no envelope.

📊 **Effort:** Medium

📦 **Libraries / Tools:** same as A.

🔗 **Existing Code to Reuse:** same adapter as A; `bots/data.py:2095-2135`.

---

### Option C: Retire STRUCTURED_* into `OutputMode.A2UI` (alias + LLM-free producer)

Make the three modes thin aliases: the renderers become A2UI producers whose
`out` **is** the serialised `CreateSurface`; `response.output_mode` flips to
`A2UI`; the config JSON and `artifacts[].definition` v1 disappear.

✅ **Pros:**
- Honours the FEAT-273 deprecation literally; one output contract, no
  dual serialisation, no shim.
- `handlers/agent.py` already forwards `a2ui_envelope` for `A2UI` mode.

❌ **Cons:**
- Breaks every current frontend and the whole FEAT-215/218/221/224 test
  matrix (`tests/outputs/formats/test_structured_*`, `tests/integration/
  test_structured_*_e2e.py`, `test_pandasagent_structured_*`).
- Explicitly rejected in Round 1a (dual-emit chosen).
- Loses the `output_mode` routing signal (`_STRUCTURED_OUTPUT_ROUTER` in
  `bots/data.py:329-350`, `IntentRouter` tests) that selects chart/table/map
  from phrasing.

📊 **Effort:** High

📦 **Libraries / Tools:** same as A.

🔗 **Existing Code to Reuse:** `emission.py::finalize_a2ui_response`.

---

### Option D (unconventional): Derive the catalog schemas from the config models

Instead of hand-maintaining `CHART_SCHEMA`/`MAP_SCHEMA`/`DATATABLE_SCHEMA`,
generate them at import time from `StructuredChartConfig.model_json_schema(
by_alias=True)` etc., stripping the input-only `data`/`datasets` fields and
replacing them with the `{"path"}` binding descriptor. Parity becomes a
property **by construction**: adding a field to the config model automatically
extends the catalog, the LLM `INSTRUCTIONS`, and `export_catalog_definition()`.

✅ **Pros:**
- Eliminates the parity gap permanently (it is exactly what drifted between
  FEAT-215/221 and FEAT-470 TASK-2539).
- One source of truth for frontend docs, catalog export and validation.

❌ **Cons:**
- Pydantic JSON Schema emits `$defs`/`anyOf` for nested models (`MapLayer`,
  `MapViewport`, `MapQuery`, `TableColumn`); the vendored v1.0 catalog format
  and `export_catalog_definition()` must tolerate `$defs` (needs a check
  against `catalogs/basic/catalog.json` conventions).
- Field naming: config aliases are camelCase already (`by_alias=True` in
  `_route_envelope`) — verify every alias matches what TASK-2539 chose
  (`showLegend`, `xAxisMode`, `totalRows`, `baseLayer`).
- Alone it does not deliver the envelope — it is a technique, not a bridge.

📊 **Effort:** Low (as an add-on to A)

📦 **Libraries / Tools:** `pydantic` `model_json_schema`; no new deps.

🔗 **Existing Code to Reuse:** `catalog/parrot/*.py` schema constants;
`catalog/export.py::export_catalog_definition`.

---

## Recommendation

**Option A** is recommended, adopting **Option D's schema derivation** for the
three parrot-catalog components:

- It is the only option that satisfies every locked decision: dual-emit, a
  single hook (`_route_envelope`), deterministic (no LLM), standalone
  envelope with rows in `dataModel`.
- It fixes the drift that Option B would perpetuate (DatabaseAgent already
  misses FEAT-224 minting today) — the renderer base class is the one place
  every STRUCTURED_* response passes through.
- Option C is the eventual end state (retire the legacy mirror), but it is a
  frontend-coordinated cut, not this feature. Option A leaves that door open:
  once `a2ui_envelope` is consumed everywhere, removing `response.output`'s
  config mirror is a one-line change.
- Trade-off accepted: rows are serialised twice for the migration window,
  bounded by `row_limit`. The core adapter takes plain row dicts / per-layer
  payloads (never `SpatialResult`), preserving the D4 one-way import rule.
- Trade-off accepted: `artifacts[].definition` breaks shape (user decision
  R2b). Cushioned by `schemaVersion: 2`, the shim and the rewritten guide.

---

## Feature Description

### User-Facing Behavior

- A PandasAgent/DatabaseAgent answer in `structured_chart` / `structured_table`
  / `structured_map` mode returns, in addition to the unchanged
  `output` (config) and `data` (rows), a `a2ui_envelope` field holding a
  spec-conformant v1.0 `{"version":"v1.0","createSurface":{…}}` with a single
  root `Chart` / `DataTable` / `Map` component of the parrot catalog
  (`catalogId: https://parrot.dev/catalogs/v1`) and a populated `dataModel`.
- `response.artifacts[]` entries become
  `{type, artifactId, surfaceId, schemaVersion: 2, definition: <Component>}`
  where `definition` is the v1.0 component node (props top-level; `data`
  is a `{"path": "/rows"}` binding, never inline rows). `surfaceId ==
  artifactId`. `response.artifact_id` keeps pointing at it.
- The same envelope can be handed to any FEAT-470 renderer: `echarts` (option
  JSON / HTML), `folium_map` (HTML), `interactive_html`, `ssr_html`, `pdf`,
  `adaptive_cards` (Teams) — enabling PDF/e-mail/Teams delivery of data-agent
  results through `Agent.notification()`, and consumption by external A2UI
  renderers.
- Frontend guide (`docs/frontend/structured-artifacts-frontend-guide.md`)
  documents the v2 artifact entry, the envelope, the `dataModel` layout and
  the legacy shim for old clients.

### Internal Behavior

1. **Renderer** (`StructuredChartRenderer` / `StructuredTableRenderer` /
   `StructuredMapRenderer`) builds its typed `cfg` exactly as today and calls
   `_route_envelope(response, cfg, explanation)`.
2. **`_route_envelope`** (satellite) — after the existing dump + `response.data`
   routing — calls the core adapter with `cfg`, the capped rows (or per-layer
   payloads for maps) and `surface_id`; stores `serialize(surface)` in
   `response.a2ui_envelope`; leaves `output_mode` untouched. Any exception is
   logged at `warning` and swallowed (`a2ui_envelope` stays `None`).
   `surface_id` is minted here (`f"{mode}-{uuid4().hex[:8]}"`, the existing
   FEAT-224 pattern) and exposed to the agent (e.g. via
   `response.artifact_id`) so the artifact entry can reuse it.
3. **Core adapter** `outputs/a2ui/adapters/structured.py`:
   - Chart → `Component(id="root", component="Chart", **props)` with all
     config fields (camelCase aliases, `None`s dropped), `data: {"path":
     "/rows"}`; `dataModel = {"rows": [...]}` (canonical records, ≤ row cap).
   - DataTable → same, `columns` list + `totalRows`/`truncated` set from the
     cap; `data: {"path": "/rows"}`. The existing `DataTable.lower()` already
     turns this into a `ChildTemplate` row pattern (`{componentId, path}`)
     expanded by `bake_envelope`.
   - Map → `layers[i]` carry all `MapLayer` fields; each layer gets
     `data: {"path": "/layers/<i>/features"}`; `dataModel = {"layers": [{"features":
     [...]}, …]}`; `viewport`, `query`, `baseLayer`, `title`, `description`
     top-level. A new `build_map()` builder mirrors `build_chart`.
   - Every surface goes through `validate_envelope(origin=ProducerOrigin.TOOL)`
     and `validate_message` (jsonschema) — an invalid surface is a bug, not
     a runtime condition, so the adapter raises and `_route_envelope` logs.
4. **Catalog parity** — `CHART_SCHEMA`/`MAP_SCHEMA`/`DATATABLE_SCHEMA` are
   derived from the config models' JSON Schema (Option D), with
   `data`/`datasets` replaced by the binding descriptor; `INSTRUCTIONS`
   mention the new fields; `lower()` renders `xAxisLabel`/`yAxisLabel`/
   `trendline` as caption text and per-layer `label_field`/`marker_color`
   in the map summary. The satellite `echarts` `_build_option` honours
   `stacked`, `splitSeries`, `trendline`, `colorBySign`, palettes and axis
   labels; `folium_map` honours `marker_color`, `tooltip_template`,
   `label_field`, `geodesic` (lines) and `data_shape`.
5. **Agents** — the FEAT-224 block in `bots/data.py` reads the root component
   from `response.a2ui_envelope["createSurface"]["components"][0]` to fill
   `definition` v2 (falls back to the v1 config dict when the envelope is
   absent, so behaviour degrades gracefully). The same block is factored into
   a helper and applied on the `DatabaseAgent` STRUCTURED_TABLE path
   (`database/agent.py:613-619`), closing today's gap.
6. **Compat shim** — `outputs/a2ui/compat.py` gains
   `artifact_definition_to_legacy(entry) -> dict` (v2 → FEAT-224 v1 camelCase
   config) and `is_legacy_artifact(entry)`.

### Edge Cases & Error Handling

- **Empty/None rows** (chart with no data, table with 0 rows): envelope is
  still built with `dataModel.rows = []`; `totalRows = 0`. Map with no
  features: layer present, empty `features`.
- **Row cap exceeded**: `dataModel` carries the first `row_limit` rows;
  `truncated: true`, `totalRows: <full>`; map layers set `capped`/
  `total_count`. `response.data` is untouched (it already has its own
  `MAX_RESPONSE_ROWS` cap in `bots/data.py`).
- **Non-JSON-serialisable cells** (Timestamp, Decimal, NaN, numpy scalars):
  reuse `canonical_records()` (`formats/table_types.py`) which the renderers
  already apply; NaN → `null`.
- **Adapter failure** (validation error, unexpected type): logged, envelope
  `None`, legacy path unaffected — never raise from `_route_envelope`.
- **Missing satellite** (`ai-parrot-visualizations` not installed): nothing
  changes; the adapter is only invoked from the satellite base class.
- **`ChildTemplate` expansion cost**: `bake_envelope` clones one row subtree
  per data row — bounded by the same row cap.
- **Multi-dataset maps** (`StructuredMapConfig.datasets`): each dataset is a
  layer; ordering is the `layers` order; `datasets` is dropped from the
  component (it is input-only, like `data`) and represented by
  `/layers/<i>/features`.
- **Legacy clients** reading `artifacts[].definition` as v1: detect
  `schemaVersion` absent/`1` vs `2`; shim documented in the guide.
- **Chart `type: "map"`** (legacy vocabulary in `StructuredChartConfig.type`):
  kept in the Chart schema enum for parity; renderers treat it as `bar`
  fallback exactly as `CHART_TYPE_MAP`/`_CHART_FALLBACK` do today.

---

## Capabilities

### New Capabilities
- `a2ui-structured-adapter`: deterministic `StructuredXConfig` + rows → v1.0
  `CreateSurface` (core `outputs/a2ui/adapters/structured.py`, `build_map`).
- `a2ui-structured-artifact-v2`: `artifacts[]` entry v2 (`surfaceId`,
  `schemaVersion`, component-node `definition`) + legacy shim.

### Modified Capabilities
- `a2ui-v1-dialect` (FEAT-470): parrot-catalog `Chart`/`DataTable`/`Map`
  schemas derived from config models (full parity), `lower()` and
  `INSTRUCTIONS` extended; satellite `echarts`/`folium_map` honour the new
  props.
- `structured-chart` / `structured-table` / `structured-map`
  (FEAT-215/218/221): renderers emit `a2ui_envelope` via
  `_route_envelope`; public `render()` signature unchanged.
- `structured-artifact-envelope` (FEAT-224): `definition` shape v2;
  DatabaseAgent path now mints artifacts too.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `packages/ai-parrot/src/parrot/outputs/a2ui/adapters/structured.py` | new | `chart_to_surface`, `table_to_surface`, `map_to_surface`; takes plain rows/payloads, never `SpatialResult` |
| `outputs/a2ui/builders.py` | extends | `build_map()`; `build_chart`/`build_datatable` gain `data_model=` passthrough |
| `outputs/a2ui/catalog/parrot/{chart,datatable,map}.py` | modifies | schemas derived from config models; `lower()`/`INSTRUCTIONS` cover all fields |
| `outputs/a2ui/catalog/export.py` | modifies (verify) | must tolerate `$defs` from Pydantic-generated schemas |
| `outputs/a2ui/compat.py` | extends | `artifact_definition_to_legacy`, `is_legacy_artifact` |
| `ai-parrot-visualizations/.../formats/structured_base.py` | modifies | `_route_envelope` calls the adapter, sets `response.a2ui_envelope` |
| `ai-parrot-visualizations/.../a2ui_renderers/echarts.py` | modifies | honour `stacked/splitSeries/trendline/colorBySign/axis labels/palette` |
| `ai-parrot-visualizations/.../a2ui_renderers/folium_map.py` | modifies | honour `marker_color/tooltip_template/label_field/geodesic/data_shape`; multi-layer |
| `bots/data.py` (FEAT-224 block ~2095-2135) | modifies | artifact entry v2 from the envelope; factor into helper |
| `bots/database/agent.py:613-619` | modifies | apply the artifact helper on STRUCTURED_TABLE |
| `models/responses.py::AIMessage.a2ui_envelope` | depends on | field already exists; docstring widened to "A2UI or STRUCTURED_* responses" |
| `handlers/agent.py` (server) | depends on | already forwards `a2ui_envelope` (lines ~2701-2705, ~2819-2827); verify it is not gated on `output_mode == A2UI` |
| `docs/frontend/structured-artifacts-frontend-guide.md` | modifies | §2.5 contract → v2 + envelope; §4–6 payload examples |
| Tests: `tests/outputs/formats/test_structured_*`, `tests/integration/test_structured_*_e2e.py`, `tests/bots/test_pandasagent_*` | modifies/extends | assert envelope presence + conformance; artifact v2 shape |
| **Breaking**: `artifacts[].definition` shape | breaking | cushioned by `schemaVersion`, shim, guide |

No new dependencies. No deployment change.

---

## Code Context

### User-Provided Code
None — all decisions were given as answers to the discovery questions.

### Verified Codebase References

All `dev` paths verified on `cf4804c44`; worktree paths verified on
`feat-470-a2ui-v1-dialect` @ `d6efb01ef` (2026-08-28, TASK-2544 complete;
TASK-2545…2548 still in progress).

#### Classes & Signatures
```python
# packages/ai-parrot-visualizations/src/parrot/outputs/formats/structured_base.py (dev)
class StructuredOutputBase:                                              # :26
    def _extract_rows(self, response: Any) -> Optional[pd.DataFrame]: # :39
    def _route_envelope(self, response: Any, cfg: Any, explanation: Optional[str]
                        ) -> tuple[Optional[dict], Optional[str]]:      # :64  ("never raises")
        # out = cfg.model_dump(mode="json", by_alias=True, exclude={"data"}); response.data = cfg.data
    @staticmethod
    def _extract_json_code(content: str) -> Optional[str]:              # :100

# packages/ai-parrot-visualizations/src/parrot/outputs/formats/structured_chart.py (dev)
class StructuredChartRenderer(StructuredOutputBase, BaseChart):        # :80
    async def render(self, response: Any, *, environment: str = "html", **kwargs
                     ) -> Tuple[Any, Optional[Any]]:                    # :98
# structured_table.py (dev)
DEFAULT_ROW_LIMIT: int = 1000                                           # :39
class StructuredTableRenderer(StructuredOutputBase, BaseChart):        # :88
    def __init__(self, row_limit: int = DEFAULT_ROW_LIMIT, **kwargs)   # :105
    async def render(self, response, *, environment="html", row_limit: Optional[int]=None, **kwargs)  # :117
# structured_map.py (dev)
class StructuredMapRenderer(StructuredOutputBase, BaseChart):          # :177
    async def render(self, response, *, environment="html", row_limit: Optional[int]=None, **kwargs)  # :208
    def _build_columns(...)   # :417   def _build_rows_payload(...)  # :505
    def _build_tabular_rows(...)  # :539   @staticmethod _compute_viewport(spatial_result) -> Optional[MapViewport]  # :583

# packages/ai-parrot/src/parrot/models/outputs.py (dev)
class OutputMode(str, Enum):                                            # :33
    STRUCTURED_CHART = "structured_chart"  # :61   STRUCTURED_TABLE = "structured_table"  # :62
    STRUCTURED_MAP = "structured_map"      # :63   A2UI = "a2ui"                          # :64
class StructuredChartConfig(BaseModel):   # :319  fields: type, x, y, stacked, trendline, split_series,
    # show_legend, x_axis_mode, palette, color_by_sign, negative_color, positive_color, x_axis_label,
    # y_axis_label, map_name, title, description, data, data_variable
class TableColumn(BaseModel):             # :493  name, type, title, format
class StructuredTableConfig(BaseModel):   # :530  columns, data, explanation, total_rows, truncated
class MapLayer(BaseModel):                # :640  layer, columns, tooltip_template, label_field, data_shape,
                                          #       total_count, capped, geodesic, marker_color
class MapViewport(BaseModel):             # :706
class MapQuery(BaseModel):                # :729
class StructuredMapConfig(BaseModel):     # :746  layers, data, datasets, viewport, query, base_layer,
                                          #       title, description, explanation

# packages/ai-parrot/src/parrot/models/responses.py (dev)
class AIMessage: artifacts: List[Dict[str, Any]]   # :206
    output_mode: OutputMode                        # :210
    artifact_id: Optional[str]                     # :214
    a2ui_envelope: Optional[Dict[str, Any]]        # :222  (FEAT-273)

# packages/ai-parrot/src/parrot/bots/data.py (dev)
# FEAT-224 artifact minting block: _STRUCTURED_ARTIFACT_TYPE {STRUCTURED_CHART:"chart", STRUCTURED_MAP:"map",
# STRUCTURED_TABLE:"table"}; _art_id = f"{mode}-{uuid4().hex[:8]}"; strips "data"/"datasets";
# response.artifacts.append({"type","artifactId","definition"}); response.artifact_id = _art_id   # :2095-2135
# _STRUCTURED_OUTPUT_ROUTER phrasing map                                                            # :329-350
# packages/ai-parrot/src/parrot/bots/database/agent.py (dev)
# if output_mode == OutputMode.STRUCTURED_TABLE: … response.output_mode = STRUCTURED_TABLE          # :613-619 (no artifact minting)

# --- FEAT-470 worktree: packages/ai-parrot/src/parrot/outputs/a2ui/ ---
# models.py
class DataBinding(BaseModel)                      # :155
class ChildTemplate(BaseModel): component_id: str = Field(alias="componentId")  # :212/:223
class Action(BaseModel)                           # :250
class Extensions(RootModel[dict[str, Any]])       # :341
class ComponentMetadata(BaseModel)                # :364
class A2UIMessageBase(BaseModel)                  # :381
class Component(BaseModel): catalog_id: str | None = Field(alias="catalogId")   # :400/:431  (extra props → model_extra)
class CreateSurface(A2UIMessageBase):             # :446
    surface_id: str = Field(alias="surfaceId")                        # :465
    catalog_id: str | None = Field(alias="catalogId")                 # :466
    send_data_model: bool = Field(default=False, alias="sendDataModel")  # :467
    components: list[Component]                                       # :468
    data_model: dict[str, Any] = Field(alias="dataModel")             # :469
class A2UIAgentMessage: create_surface | update_components | update_data_model | delete_surface
                        | call_renderer_function | agent_function_response       # :708-713

# builders.py
def build_surface(component: str, properties: dict, *, surface_id: str, component_id: str = "root",
                  data_model: dict | None = None) -> CreateSurface          # :49  (validate_envelope origin=LLM)
def build_chart(*, chart_type, x, y, title=None, data_binding=None, show_legend=True, surface_id="chart")  # :78
def build_kpicard(...)  # :98   def build_card(...)  # :118
def build_datatable(*, columns, data_binding=None, title=None, total_rows=None, truncated=False, surface_id="table")  # :140
def build_infographic(...)  # :163

# catalog/base.py
DEFAULT_CATALOG_ID = "https://parrot.dev/catalogs/v1"   # :52
class ProducerOrigin(str, Enum)   # :80 (TOOL / LLM)
class BasicNode(BaseModel)        # :92    class TabSpec  # :136
def to_components(tree: BasicNode, *, id_prefix: str = "blk") -> list[Component]   # :155
class ComponentDefinition(BaseModel)  # :215   class FunctionDefinition  # :246
class RegisteredComponent  # :270   class CatalogValidationError(CatalogError)  # :294
# catalog/__init__.py
def register_component(...)  # :97   def get_component(name) -> RegisteredComponent  # :165
def catalog_instructions() -> str  # :203
def resolve_catalog(component_catalog_id, surface_catalog_id) -> str  # :217
def validate_message(message: A2UIAgentMessage | A2UIRendererMessage) -> None  # :281 (jsonschema)
def validate_envelope(envelope: CreateSurface | UpdateComponents, *, origin: ProducerOrigin = ProducerOrigin.TOOL,
                      surface_catalog_id: str | None = None) -> None   # :324
# catalog/parrot/chart.py   CHART_SCHEMA :22 (title,type,x,y,stacked,showLegend,xAxisMode,palette,data) ; class ChartComponent :57 ; lower() :63
# catalog/parrot/datatable.py DATATABLE_SCHEMA :21 (title,columns{name,type,title,format},totalRows,truncated,data) ; DataTableComponent :56 ; lower() :62 (ChildTemplate row, relative {"path": col})
# catalog/parrot/map.py      MAP_SCHEMA :22 (title,description,baseLayer,viewport{center,zoom},layers[{name,type}],data) ; MapComponent :60 ; lower() :66
# serialization.py  A2UI_VERSION = "v1.0" :55 ; def serialize(message) -> dict :104 ; deserialize :155 ; to_jsonl :201
# baking.py  def bake_envelope(envelope: CreateSurface) -> list[dict] :356 ; async persist_envelope :399 ; _expand_template :307
# compat.py  is_legacy_envelope :41 ; normalize_legacy_component :95 ; normalize_legacy(data) :186
# emission.py  def finalize_a2ui_response(response: Any) -> None :18 (sets a2ui_envelope AND output_mode=A2UI)
# satellite a2ui_renderers (worktree): EChartsRenderer :58 (supported_components={"Chart"}, render :61, _build_option ~:113)
#   FoliumMapRenderer :62 (supported_components={"Map"}, render :65; reads baked Map center/zoom/point features)
```

#### Verified Imports
```python
# dev
from parrot.models.outputs import OutputMode, StructuredChartConfig, StructuredTableConfig, StructuredMapConfig, MapLayer, MapViewport, MapQuery, TableColumn
from parrot.models.responses import AIMessage
from parrot.outputs.formats import get_renderer, register_renderer          # formats/__init__.py:83/:99
from parrot.outputs.formats.table_types import canonical_records, base_column_types
from parrot.outputs.formats.structured_base import StructuredOutputBase     # satellite
# FEAT-470 worktree
from parrot.outputs.a2ui.models import CreateSurface, Component, ChildTemplate
from parrot.outputs.a2ui.builders import build_surface, build_chart, build_datatable
from parrot.outputs.a2ui.catalog import register_component, validate_envelope, validate_message
from parrot.outputs.a2ui.catalog.base import DEFAULT_CATALOG_ID, ProducerOrigin, BasicNode, BasicTree
from parrot.outputs.a2ui.serialization import serialize, A2UI_VERSION
from parrot.outputs.a2ui.baking import bake_envelope
from parrot.outputs.a2ui.compat import normalize_legacy
```

#### Key Attributes & Constants
- `DEFAULT_ROW_LIMIT = 1000` (`structured_table.py:39`) — the row cap to reuse.
- `DEFAULT_CATALOG_ID = "https://parrot.dev/catalogs/v1"` (worktree `catalog/base.py:52`).
- `A2UI_VERSION = "v1.0"` (worktree `serialization.py:55`).
- `Component` accepts arbitrary top-level props (read back via `component.model_extra`, see `lower()` implementations).
- Installed: `pydantic 2.12.5`, `jsonschema 4.26.0`, `jsonpointer 3.1.1`, `folium 0.20.0`.

### Does NOT Exist (Anti-Hallucination)
- ~~`parrot.outputs.a2ui.builders.build_map`~~ — no map builder; only chart/kpicard/card/datatable/infographic.
- ~~`parrot.outputs.a2ui.adapters.structured`~~ — `adapters/` contains only `infographic.py`.
- ~~`a2ui_max_rows`~~ / any A2UI-specific row cap setting — does not exist; reuse `row_limit`.
- ~~`_attach_structured_artifact`~~ — mentioned in a FEAT-224 test docstring, but the logic is inline in `bots/data.py:2095-2135`, not a function.
- ~~`artifacts[].surfaceId` / `schemaVersion`~~ — not present today; FEAT-224 entries are `{type, artifactId, definition}` only.
- ~~`response.a2ui_envelope` on STRUCTURED_* responses~~ — never set today (only `OutputMode.A2UI`, infographic and interactive paths, `bots/base.py:1421-1464`).
- ~~`CHART_SCHEMA` fields `trendline`, `splitSeries`, `colorBySign`, `xAxisLabel`, `yAxisLabel`, `mapName`~~ and ~~`MAP_SCHEMA` `MapLayer` fields beyond `name`/`type`~~ — not in the FEAT-470 schemas yet.
- ~~`wikitoolkit` binary~~ — `.venv/bin/wikitoolkit` was missing in this session (MCP failed to connect); research was done with grep/read.

---

## Parallelism Assessment

- **Internal parallelism**: three independent lanes after a small shared
  foundation (adapter skeleton + schema derivation): (1) core adapter +
  `build_map` + compat shim + tests; (2) satellite `_route_envelope` hook +
  `echarts`/`folium_map` prop coverage; (3) agents (`data.py`,
  `database/agent.py`) artifact v2 + frontend guide. Lanes 2 and 3 touch
  different packages; lane 1 must land first.
- **Cross-feature independence**: **conflicts with FEAT-470** by design —
  same `catalog/parrot/*.py`, `builders.py`, satellite `a2ui_renderers/*`.
  FEAT-470 TASK-2545 (Adaptive Cards), 2546 (transport), 2547 (LLM producer),
  2548 (conformance suite) are still in progress; 2547/2548 touch
  `catalog_instructions()` and the conformance tests we will extend. Nothing
  in FEAT-471 (rustworkx) or other in-flight worktrees overlaps.
- **Recommended isolation**: `per-spec` — one worktree branched from `dev`
  **after the FEAT-470 PR merges**, tasks sequential.
- **Rationale**: the shared foundation (schema derivation changes the very
  files FEAT-470 is still finishing) makes parallel worktrees a merge hazard;
  the lanes are small enough that sequential execution costs little.

---

## Open Questions

- [x] Flow type / base branch — *Owner: Jesus Lara*: `feature`, base `dev`; start only after FEAT-470 merges (see start-gate question).
- [x] Dual-emit vs replace — *Owner: Jesus Lara*: dual-emit; `output`/`data` unchanged, envelope added in `a2ui_envelope`.
- [x] Schema parity — *Owner: Jesus Lara*: full parity of `Chart`/`DataTable`/`Map` with the config models.
- [x] Row placement — *Owner: Jesus Lara*: `dataModel` + `{"path"}` bindings.
- [x] Hook point — *Owner: Jesus Lara*: `StructuredOutputBase._route_envelope` via a core adapter.
- [x] `artifacts[]` relationship — *Owner: Jesus Lara*: `definition` becomes the v1.0 component node; `surfaceId == artifactId`; add `schemaVersion: 2`; legacy shim + frontend guide rewrite.
- [x] Map layout — *Owner: Jesus Lara*: `/layers/<i>/features`, folium native, `lower()` stays a layer summary.
- [x] Row cap — *Owner: Jesus Lara*: reuse `row_limit` (`DEFAULT_ROW_LIMIT = 1000`) with `truncated`/`totalRows`.
- [x] Does `export_catalog_definition()` / the vendored catalog format accept Pydantic `$defs` in component schemas? — *Owner: Claude (spike 2026-08-29)*: yes — `StructuredMapConfig.model_json_schema(by_alias=True)` (with `$defs` MapColumn/MapLayer/MapQuery/MapViewport) and the inlined variant BOTH validate against the vendored `catalog_definition.json`; no inlining required (keep a small inliner as optional hardening).
- [x] Is `handlers/agent.py` forwarding of `a2ui_envelope` gated on `output_mode == A2UI`? — *Owner: Claude (verified)*: the **stream** path (`handlers/agent.py:2703-2705`) forwards it whenever present — no change needed; the **non-stream** path (`:2826`) sits inside the `output_mode == A2UI` branch and must be widened to "envelope present".
- [x] Should `response.output`'s config mirror carry a `surfaceId` hint too? — *Owner: Jesus Lara*: yes — add `surfaceId` (== `artifactId`) to `response.output`; `schemaVersion` only on `artifacts[]`.
- [x] Deprecation timeline for the FEAT-224 v1 `definition` shape — *Owner: Jesus Lara*: cut in this feature (0.29.x); legacy shim supported for two minor releases (through 0.31), then removed.
- [x] May the FEAT-470 LLM producer emit `Chart`/`DataTable`/`Map` with inline `dataModel` rows? — *Owner: Jesus Lara*: tool-only data — the LLM may emit the components but `data` must be a `{"path"}` binding to a tool-supplied dataModel; inline rows rejected for `origin=LLM`.
- [x] Start gate — *Owner: Jesus Lara*: wait for the FEAT-470 PR to merge into `dev`; then branch from `dev`. Spec/tasks may be written before that.
