---
type: Wiki Overview
title: 'Feature Specification: Structured Map Output Mode (`STRUCTURED_MAP`)'
id: doc:sdd-specs-structured-map-output-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: FEAT-219 (`spatial-dataset-filter`) delivered only **half** of the original
relates_to:
- concept: mod:parrot.models.outputs
  rel: mentions
- concept: mod:parrot.outputs.formats
  rel: mentions
- concept: mod:parrot.outputs.formats.table_types
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.spatial
  rel: mentions
---

---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Structured Map Output Mode (`STRUCTURED_MAP`)

**Feature ID**: FEAT-221
**Date**: 2026-06-04
**Author**: Jesus Lara
**Status**: approved
**Target version**: TBD

> Source brainstorm: `sdd/proposals/structured-map-output.brainstorm.md`
> (Recommended Option **B** — Homologated `STRUCTURED_MAP` mode + per-dataset spatial result).
> Aligns with the accepted `structured-artifact-contract` brainstorm
> (`sdd/proposals/structured-artifact-contract.brainstorm.md`, Juan Ruffato) —
> this feature realizes the **`map`** member of the `chart, map, document,
> infographic, summary, table` structured taxonomy and the data/presentation split.

---

## 1. Motivation & Business Requirements

### Problem Statement

FEAT-219 (`spatial-dataset-filter`) delivered only **half** of the original
intent. It built the deterministic spatial-filtering capability in
`DatasetManager` (`spatial_filter(spec) → SpatialFeatureCollection`), so a
request like *"return the schools and shopping malls within 5 miles of warehouse
XYZ"* resolves to a real, hallucination-free GeoJSON result via engine push-down
(PostGIS `ST_DWITHIN` / BigQuery `GEOGRAPHY`) with a bounded Pandas haversine
fallback.

What it did **not** build is the second half: a **structured map output** an
agent (e.g. `PandasAgent`) can emit through the renderer pipeline — homologated
with `StructuredChartConfig` (FEAT-215) and `StructuredTableConfig` (FEAT-218).
Verification of the current tree confirms the gap:

- No `OutputMode.STRUCTURED_MAP` in `parrot/models/outputs.py`.
- No `StructuredMapConfig` model and no renderer registered via
  `register_renderer(OutputMode.STRUCTURED_MAP, ...)`.
- `bots/data.py` (`PandasAgent`) has zero awareness of spatial output — it cannot
  route a map config the way it routes `STRUCTURED_CHART`.
- `SpatialFeatureCollection` is consumed only by `spatial_filter_handler.py`
  (transport layer), never by the agent renderer pipeline.

FEAT-219 explicitly scoped map presentation out ("**No map rendering — ever.
Backend returns features only.**"), assuming the frontend would build the Leaflet
map straight from raw GeoJSON. This feature closes the gap by adding the
**presentation contract**: the backend still does not render a map, but it
returns *everything the frontend needs to paint one* — per-dataset layers with
the columns to show, labels, per-element tooltip templates, plus map-level
viewport, the query geometry, the data, and a prose explanation of what was done.

**Affected:** frontend map consumers (Leaflet), `PandasAgent` users requesting
map output, and the FEAT-219 spatial backend (its output contract changes).

### Goals

- **G1 — Homologation.** The output mirrors the structured family conventions:
  a Pydantic config with `populate_by_name=True`, `data` carried as **INPUT-ONLY**
  and excluded from the serialized `output`, a renderer returning
  `(out_without_data, explanation)` that routes rows to `response.data` and
  **never raises** (`(None, error_message)` on failure).
- **G2 — No map rendering.** The backend returns a *config + data*, never an
  HTML/Leaflet map (inherited from FEAT-219).
- **G3 — Layers per dataset.** One layer per dataset (`source`/`layer`
  discriminator), each with its own columns / labels / tooltip template.
- **G4 — Per-dataset separation at the source.** `spatial_filter` returns results
  already grouped per dataset (replacing the single merged `FeatureCollection`).
- **G5 — Deterministic base + optional LLM refine.** Presentation metadata comes
  from the `DatasetSpatialProfile` registry; an optional narrow LLM pass may add
  labels/format hints — deterministic always wins (FEAT-218 pattern).
- **G6 — Configurable data shape per layer.** Each layer supports **both** a
  native GeoJSON `FeatureCollection` payload **and** a flattened
  rows+columns+geometry-ref payload, selectable per layer/request.
- **G7 — Map-level metadata.** The config carries: viewport (bbox + optional
  center/zoom, computed deterministically), the query geometry (point+radius+unit
  from `SpatialFilterSpec`), an optional base-tile/style hint, and
  `title` + `description` + `explanation`.
- **G8 — Compact tooltips.** Tooltips are a per-layer template (à la
  `description_template`), never pre-rendered per-element strings (payload bounded
  at ≈879k features).
- **G9 — Renderer reads from `response.data`.** On the agent path, `PandasAgent`
  invokes `DatasetManager.spatial_filter` as a tool; the renderer reads the
  spatial result from `response.data`.
- **G10 — Capping preserved.** Per-dataset hard cap + true `total_count` +
  `capped`/`truncated` flags survive into the per-layer config.

### Non-Goals (explicitly out of scope)

- Server-side map rendering (HTML/Leaflet/Folium) — never (G2). The existing
  Folium `OutputMode.MAP` is untouched and unrelated.
- Choropleth charts — already covered by `StructuredChartConfig` `type="map"`;
  not folded in here. *(Unifying all geo output under one config was rejected in
  brainstorm — see proposals/structured-map-output.brainstorm.md Option C.)*
- Re-deriving per-dataset grouping inside the renderer from a merged collection
  *(rejected — brainstorm Option A).*
- DB agent (`bots/database/agent.py`) `STRUCTURED_MAP` support — deferred to a
  follow-up; v1 targets `PandasAgent` only (see §8).

---

## 2. Architectural Design

### Overview

Introduce `OutputMode.STRUCTURED_MAP` plus a `StructuredMapConfig` Pydantic model
(with `MapLayer` / `MapColumn`) homologated with the structured family, and a
`StructuredMapRenderer` registered via
`register_renderer(OutputMode.STRUCTURED_MAP, ...)`. FEAT-219's `spatial_filter`
is modified to return results grouped **per dataset** (each group carrying its
own `features`, `total_count`, `capped`, `geodesic`), exposed through a versioned
result model so the existing deterministic frontend path (handler) is not broken.

The data/presentation split (per the `structured-artifact-contract` direction) is
realized as: **data schema** = `MapLayer.columns` (`name/type/title/format`,
reusing the `TableColumn` vocabulary) + the row/feature payload; **presentation
schema** = layer `tooltip_template`, `label_field`, `data_shape`, plus map-level
`viewport`/`query`/`base_layer`/`title`/`description`.

`StructuredMapRenderer` reads the per-dataset spatial result from `response.data`,
builds one `MapLayer` per dataset deterministically (columns from
`DatasetSpatialProfile.property_cols` typed via `base_column_types`, tooltip from
`description_template`), optionally LLM-refines labels/format hints, computes the
viewport from feature bounds, excludes `data` from `output`, routes the payload to
`response.data`, and returns `(out, explanation)` — never raising. `PandasAgent`
gains a `STRUCTURED_MAP` branch paralleling the `STRUCTURED_CHART` branch.

### Component Diagram
```
PandasAgent (bots/data.py)
   │  output_mode = STRUCTURED_MAP
   │  calls tool ──→ DatasetManager.spatial_filter(spec)
   │                      │  (modified: per-dataset grouping)
   │                      └──→ SpatialResult { layers: {dataset → SpatialLayerResult} }
   │                                 │ routed to response.data
   ▼
Formatter._get_renderer(STRUCTURED_MAP)
   │
   ▼
StructuredMapRenderer.render(response)
   ├─ per dataset: base_column_types + canonical_records (rows) | GeoJSON passthrough
   ├─ columns/tooltip/label from DatasetSpatialProfile (+ optional LLM refine)
   ├─ viewport from feature bounds; query from SpatialFilterSpec
   ├─ build StructuredMapConfig (exclude {"data"})
   └─ response.data = payload ; return (out, explanation)
                       │
                       ▼
            Frontend (Leaflet) paints map from config + response.data

(parallel transport path, unchanged contract via version shim)
spatial_filter_handler.py ──→ DatasetManager.spatial_filter ──→ SpatialResult
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `OutputMode` (`parrot/models/outputs.py:39`) | extends | add `STRUCTURED_MAP = "structured_map"` |
| `StructuredTableConfig` / `TableColumn` (`outputs.py:509`/`:472`) | mirrors | template for `StructuredMapConfig`/`MapColumn` |
| `register_renderer` + `_MODULE_MAP` (`outputs/formats/__init__.py`) | uses | register `('.structured_map',)` |
| `StructuredTableRenderer` (`.../formats/structured_table.py:88`) | mirrors | renderer skeleton (extract→types→rows→refine→route→never-raise) |
| `base_column_types` / `canonical_records` (`outputs/formats/table_types.py:42`/`:70`) | uses | column typing + JSON-safe rows |
| `DatasetManager.spatial_filter` (`dataset_manager/tool.py:4186`) | modifies | per-dataset grouped result |
| `SpatialFilterSpec`/`DatasetSpatialProfile`/`SpatialFeatureCollection` (`spatial/contracts.py`) | extends | new per-dataset result model; presentation hints on profile |
| `spatial_filter_handler.py` | modifies | adapt to new contract via version shim |
| `bots/data.py` `STRUCTURED_CHART` branch (`:1499–1680`) | mirrors | new `STRUCTURED_MAP` branch |
| `Formatter._get_renderer` (`outputs/formatter.py:218,284`) | uses | dispatch unchanged |

### Data Models
```python
# parrot/models/outputs.py — new (mirrors StructuredTableConfig / TableColumn)

class MapColumn(BaseModel):
    """A presentable column for a map layer (same vocabulary as TableColumn)."""
    name: str                       # matches a key in feature.properties / row
    type: str                       # string|integer|number|boolean|date|datetime|time|duration|any
    title: str                      # human label (LLM may refine)
    format: Optional[str] = None    # currency|percent|email|uri|enum|id|code

class MapLayer(BaseModel):
    """One layer per dataset — data schema + presentation schema."""
    model_config = ConfigDict(populate_by_name=True)
    layer: str                                  # Leaflet layer id / GeoJSON source discriminator
    columns: List[MapColumn]
    tooltip_template: Optional[str] = None      # str.format_map over feature.properties (compact, G8)
    label_field: Optional[str] = None           # property key used for the marker label
    data_shape: Literal["geojson", "rows"] = "geojson"   # G6
    total_count: int = 0                        # per-dataset true count (G10)
    capped: bool = False
    geodesic: Optional[bool] = None             # from SpatialFeatureCollection.geodesic_paths

class MapViewport(BaseModel):
    bbox: Optional[List[float]] = None          # [min_lng, min_lat, max_lng, max_lat]
    center: Optional[Tuple[float, float]] = None  # (lat, lng) — optional, frontend may derive
    zoom: Optional[int] = None                   # optional hint

class MapQuery(BaseModel):
    point: Tuple[float, float]                  # (lat, lng) — echoed from SpatialFilterSpec
    radius: float
    unit: Literal["mi", "km", "m"]

class StructuredMapConfig(BaseModel):
    """Framework-agnostic map configuration (FEAT-221) — mirrors StructuredTableConfig."""
    model_config = ConfigDict(populate_by_name=True)
    layers: List[MapLayer]
    data: List[dict] = Field(default_factory=list)   # INPUT-ONLY; excluded from output, routed to response.data
    viewport: Optional[MapViewport] = None
    query: Optional[MapQuery] = None
    base_layer: Optional[str] = None             # optional base-tile/style HINT
    title: Optional[str] = None
    description: Optional[str] = None
    explanation: Optional[str] = None

# parrot/tools/dataset_manager/spatial/contracts.py — new per-dataset grouped result (G4)

class SpatialLayerResult(BaseModel):
    """Per-dataset slice of a spatial filter result."""
    layer: str
    features: List[Dict] = Field(default_factory=list)
    total_count: int = 0
    capped: bool = False
    geodesic: bool = True

class SpatialResult(BaseModel):
    """Versioned per-dataset result returned by spatial_filter (replaces merged collection)."""
    version: Literal[2] = 2
    layers: Dict[str, SpatialLayerResult] = Field(default_factory=dict)  # keyed by resolved dataset name
    # back-compat: a .as_feature_collection() helper yields the legacy merged shape for the handler
```

> NOTE: the exact wire field names of `StructuredMapConfig` and the viewport
> representation are pending frontend confirmation (see §8). The shapes above are
> the proposed design; implementation should treat them as the default and adjust
> only if the frontend coordination resolves otherwise.

### New Public Interfaces
```python
# parrot/tools/dataset_manager/tool.py (modified signature)
async def spatial_filter(
    self, spec: SpatialFilterSpec, cap_per_dataset: int = 1000
) -> SpatialResult:   # was -> SpatialFeatureCollection
    ...

# packages/ai-parrot-visualizations/src/parrot/outputs/formats/structured_map.py (new)
@register_renderer(OutputMode.STRUCTURED_MAP, system_prompt=STRUCTURED_MAP_SYSTEM_PROMPT)
class StructuredMapRenderer(BaseChart):
    async def render(
        self, response: Any, *, environment: str = "html",
        row_limit: Optional[int] = None, **kwargs,
    ) -> Tuple[Any, Optional[Any]]:
        ...   # returns (config_dict_without_data, explanation) | (None, error_message); never raises
```

---

## 3. Module Breakdown

> These map to Task Artifacts in `/sdd-task`.

### Module 1: Structured map contract models
- **Path**: `packages/ai-parrot/src/parrot/models/outputs.py`
- **Responsibility**: Add `OutputMode.STRUCTURED_MAP`; add `MapColumn`, `MapLayer`,
  `MapViewport`, `MapQuery`, `StructuredMapConfig` mirroring `StructuredTableConfig`
  (`populate_by_name=True`, `data` INPUT-ONLY, column-name validator).
- **Depends on**: existing `TableColumn` pattern.

### Module 2: FEAT-219 per-dataset result refactor
- **Path**: `packages/ai-parrot/src/parrot/tools/dataset_manager/spatial/contracts.py`,
  `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py`
- **Responsibility**: Add `SpatialLayerResult` + `SpatialResult` (version=2);
  change `spatial_filter` to return per-dataset grouping; provide
  `as_feature_collection()` back-compat helper.
- **Depends on**: existing `SpatialFeatureCollection`, `spatial_filter`.

### Module 3: Transport handler compatibility
- **Path**: `packages/ai-parrot/src/parrot/handlers/spatial_filter_handler.py`
- **Responsibility**: Adapt both endpoints to the new `SpatialResult`; serve the
  legacy merged shape via `as_feature_collection()` (or a `?version=` toggle) so
  the deterministic frontend path is not broken.
- **Depends on**: Module 2.

### Module 4: StructuredMapRenderer
- **Path**: `packages/ai-parrot-visualizations/src/parrot/outputs/formats/structured_map.py`
  and `_MODULE_MAP` registration in `packages/ai-parrot/src/parrot/outputs/formats/__init__.py`
- **Responsibility**: Read `SpatialResult` from `response.data`; build one
  `MapLayer` per dataset (columns via `base_column_types`, tooltip from
  `description_template`); optional LLM refine (deterministic wins); compute
  viewport from bounds; both `data_shape`s; exclude `data`; route to
  `response.data`; return `(out, explanation)`; never raise.
- **Depends on**: Module 1, Module 2, `table_types`, `StructuredTableRenderer` pattern.

### Module 5: Presentation hints on the spatial profile
- **Path**: `packages/ai-parrot/src/parrot/tools/dataset_manager/spatial/contracts.py`
  (+ registry seed)
- **Responsibility**: Extend `DatasetSpatialProfile` with optional presentation
  hints needed by Module 4 (e.g. `label_col`, `tooltip_template` distinct from
  `description_template`, per-column `title`/`format` overrides). Backward
  compatible (all optional, defaults preserve current behavior).
- **Depends on**: Module 1.

### Module 6: PandasAgent STRUCTURED_MAP wiring
- **Path**: `packages/ai-parrot/src/parrot/bots/data.py`
- **Responsibility**: Add a `STRUCTURED_MAP` branch paralleling `STRUCTURED_CHART`
  — force/route the config, ensure the `spatial_filter` tool result lands in
  `response.data`, set `response.output_mode`.
- **Depends on**: Modules 1, 2, 4.

### Module 7: Tests
- **Path**: `packages/ai-parrot/tests/...`
- **Responsibility**: Unit + integration coverage (see §4).
- **Depends on**: Modules 1–6.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_structured_map_config_excludes_data` | 1 | `model_dump(exclude={"data"})` drops rows; layers/viewport retained |
| `test_map_column_vocabulary` | 1 | `MapColumn.type`/`format` accept the same vocab as `TableColumn` |
| `test_config_validates_column_names` | 1 | column names absent from data rows raise (mirror table validator) |
| `test_spatial_filter_returns_per_dataset` | 2 | `spatial_filter` returns `SpatialResult` keyed by dataset, per-layer counts |
| `test_spatial_result_back_compat_collection` | 2 | `as_feature_collection()` reproduces the legacy merged shape |
| `test_handler_serves_legacy_shape` | 3 | handler still returns the merged FeatureCollection contract |
| `test_renderer_builds_layers_deterministically` | 4 | one `MapLayer` per dataset; columns typed via `base_column_types` |
| `test_renderer_data_shape_rows_and_geojson` | 4 | both `data_shape`s produce valid payloads; rows via `canonical_records` |
| `test_renderer_viewport_from_bounds` | 4 | bbox/center computed from feature coordinates |
| `test_renderer_llm_refine_deterministic_wins` | 4 | LLM cannot change hard types; only adds format/labels |
| `test_renderer_never_raises` | 4 | malformed input → `(None, error_message)` |
| `test_renderer_empty_layer_preserved` | 4 | dataset with zero features → empty layer, not dropped |
| `test_profile_presentation_hints_optional` | 5 | new profile fields default-compatible |
| `test_pandasagent_structured_map_branch` | 6 | `output_mode=STRUCTURED_MAP` routes config + data correctly |

### Integration Tests
| Test | Description |
|---|---|
| `test_structured_map_e2e_llm_mode` | NL spatial query → PandasAgent → `StructuredMapConfig` + `response.data` |
| `test_structured_map_e2e_multi_dataset` | two datasets → two layers, per-layer capping + viewport union |
| `test_deterministic_handler_unchanged` | frontend deterministic path still receives legacy/compat shape |

### Test Data / Fixtures
```python
@pytest.fixture
def two_dataset_spatial_result():
    # SpatialResult with two SpatialLayerResult groups (schools, malls),
    # each with a few GeoJSON point features + per-layer total_count/capped.
    ...

@pytest.fixture
def map_profiles():
    # DatasetSpatialProfile per dataset with property_cols + description_template
    # (+ new optional presentation hints).
    ...
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] `OutputMode.STRUCTURED_MAP` exists and `StructuredMapConfig`/`MapLayer`/`MapColumn`
      mirror the structured-family contract (`populate_by_name=True`, `data` INPUT-ONLY,
      excluded from `output`). **(G1)**
- [ ] The renderer returns `(out_without_data, explanation)`, routes rows to
      `response.data`, and returns `(None, error_message)` on any failure — never raises. **(G1)**
- [ ] No server-side map is ever produced. **(G2)**
- [ ] The config exposes one layer per dataset via the `source`/`layer` discriminator. **(G3)**
- [ ] `spatial_filter` returns results grouped per dataset (`SpatialResult`). **(G4)**
- [ ] Presentation metadata derives deterministically from `DatasetSpatialProfile`;
      the optional LLM refine cannot change hard types (deterministic wins). **(G5)**
- [ ] Each layer supports both `data_shape="geojson"` and `data_shape="rows"`. **(G6)**
- [ ] The config carries viewport, query geometry, optional base-layer hint, and
      `title`/`description`/`explanation`. **(G7)**
- [ ] Tooltips are expressed as a per-layer template (no per-element strings). **(G8)**
- [ ] On the agent path the renderer reads the spatial result from `response.data`. **(G9)**
- [ ] Per-dataset `total_count`/`capped`/`geodesic` survive into each `MapLayer`. **(G10)**
- [ ] The deterministic frontend path through `spatial_filter_handler.py` continues
      to work (legacy/compat shape served).
- [ ] All unit tests pass (`pytest packages/ai-parrot/tests/ -v`).
- [ ] All integration tests pass.
- [ ] No breaking changes to merged `STRUCTURED_CHART` (FEAT-215) / `STRUCTURED_TABLE` (FEAT-218).

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** All references below were re-verified
> on branch `dev` at FEAT-221 authoring time (after rebasing onto origin/dev).

### Verified Imports
```python
from parrot.models.outputs import (
    OutputMode, StructuredTableConfig, TableColumn, StructuredChartConfig,
    StructuredOutputConfig,
)  # verified: packages/ai-parrot/src/parrot/models/outputs.py
from parrot.outputs.formats import register_renderer, get_renderer  # verified: outputs/formats/__init__.py
from parrot.outputs.formats.table_types import base_column_types, canonical_records  # verified: table_types.py:42,70
from parrot.tools.dataset_manager.spatial import (
    SpatialFilterSpec, DatasetSpatialProfile, SpatialFeatureCollection,
)  # verified: packages/ai-parrot/src/parrot/tools/dataset_manager/spatial/__init__.py:8
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/models/outputs.py
class OutputMode(str, Enum):                       # line 39
    STRUCTURED_CHART = "structured_chart"          # line 72
    STRUCTURED_TABLE = "structured_table"          # line 73  (FEAT-218)
    MAP = "map"                                     # line 59  (Folium — unrelated, do NOT reuse)

class TableColumn(BaseModel):                       # line 472
    name: str                                       # line 492
    type: str                                       # line 493  string|integer|number|boolean|date|datetime|time|duration|any
    title: str                                      # line 500
    format: Optional[str] = None                    # line 501  currency|percent|email|uri|enum|id|code

class StructuredTableConfig(BaseModel):             # line 509
    model_config = ConfigDict(populate_by_name=True)  # line 528
    columns: List[TableColumn]                      # line 530
    data: List[dict] = Field(default_factory=list)  # line 533  INPUT-ONLY, excluded from output
    explanation: Optional[str] = None               # line 540
    total_rows: Optional[int] = None                # line 544
    truncated: bool = False                         # line 548
    @model_validator(mode="after")
    def _validate_column_names(self): ...           # line 553  column.name ∈ data[0].keys()

class StructuredChartConfig(BaseModel):             # line 310  (has type="map" + map_name — choropleth, NOT this feature)

# packages/ai-parrot-visualizations/src/parrot/outputs/formats/structured_table.py
@register_renderer(OutputMode.STRUCTURED_TABLE, system_prompt=STRUCTURED_TABLE_SYSTEM_PROMPT)  # line 87
class StructuredTableRenderer(BaseChart):           # line 88
    def __init__(self, row_limit: int = DEFAULT_ROW_LIMIT, **kwargs): ...   # line 105
    async def render(self, response, *, environment="html",
                     row_limit=None, **kwargs) -> Tuple[Any, Optional[Any]]: ...  # line 117
    async def _apply_llm_refine(self, columns, response) -> list[TableColumn]: ...  # line 233
    # routes: out = cfg.model_dump(mode="json", by_alias=True, exclude={"data"}); response.data = cfg.data

# packages/ai-parrot/src/parrot/outputs/formats/__init__.py
def register_renderer(mode: OutputMode, system_prompt: Optional[str] = None): ...   # decorator
_MODULE_MAP: dict = { OutputMode.STRUCTURED_TABLE: ('.structured_table',), ... }     # lazy import table
def get_renderer(mode) -> Type[Renderer]: ...

…(truncated)…
