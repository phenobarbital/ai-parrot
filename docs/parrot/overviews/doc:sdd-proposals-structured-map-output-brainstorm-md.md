---
type: Wiki Overview
title: 'Brainstorm: Structured Map Output Mode (`STRUCTURED_MAP`)'
id: doc:sdd-proposals-structured-map-output-brainstorm-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: FEAT-219 (`spatial-dataset-filter`) delivered **half** of the original intent.
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

# Brainstorm: Structured Map Output Mode (`STRUCTURED_MAP`)

**Date**: 2026-06-04
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: B

---

## Problem Statement

FEAT-219 (`spatial-dataset-filter`) delivered **half** of the original intent.
It built the deterministic spatial-filtering capability in `DatasetManager`
(`spatial_filter(spec) → SpatialFeatureCollection`), so a request like *"return
the schools and shopping malls within 5 miles of warehouse XYZ"* resolves to a
real, hallucination-free GeoJSON result via engine push-down (PostGIS `ST_DWITHIN`
/ BigQuery `GEOGRAPHY`) with a bounded Pandas haversine fallback.

What it **did not** build is the second half: a **structured map output** that an
agent (e.g. `PandasAgent`) can emit through the renderer pipeline — homologated
with `StructuredChartConfig` (FEAT-215) and `StructuredTableConfig` (FEAT-218).
Verification of the current tree confirms the gap:

- There is **no** `OutputMode.STRUCTURED_MAP` in `models/outputs.py`.
- There is **no** `StructuredMapConfig` model and **no** renderer registered via
  `register_renderer(OutputMode.STRUCTURED_MAP, ...)`.
- `bots/data.py` (`PandasAgent`) has **zero** awareness of spatial output —
  it cannot route a map config the way it routes `STRUCTURED_CHART`.
- `SpatialFeatureCollection` is consumed **only** by `spatial_filter_handler.py`
  (a transport-layer path), never by the agent's renderer pipeline.

The FEAT-219 spec explicitly scoped map presentation out ("**No map rendering —
ever. Backend returns features only.**"), assuming the frontend would build the
Leaflet map straight from raw GeoJSON. The new feature closes that gap by adding
a **presentation contract**: the backend still does not render a map, but it now
returns *everything the frontend needs to paint one* — per-dataset layers with
the columns to show, labels, per-element tooltip templates, plus map-level
viewport, the query geometry, the data, and a prose explanation of what was done.

**Affected:** frontend map consumers (Leaflet), `PandasAgent` users requesting
map output, and the FEAT-219 spatial backend (its output contract changes —
see below).

## Constraints & Requirements

- **C1 — Homologation.** The output MUST mirror the structured family
  conventions: a Pydantic config with `populate_by_name=True`, `data` carried as
  **INPUT-ONLY** and excluded from the serialized `output`, a renderer that
  returns `(out_without_data, explanation)`, routes rows to `response.data`, and
  **never raises** (`(None, error_message)` on failure) — exactly as
  `StructuredTableRenderer` / `StructuredChartRenderer` do.
- **C2 — No map rendering.** The backend returns a *config + data*, never an
  HTML/Leaflet map. (Inherited from FEAT-219.)
- **C3 — Layers per dataset.** The config MUST expose one layer per dataset
  (`source`/`layer` discriminator), each with its own column set / labels /
  tooltip template.
- **C4 — Per-dataset separation at the source.** Per the Round-2 decision,
  `spatial_filter` MUST be modified to return results **already grouped per
  dataset** (instead of one merged `FeatureCollection`). This is a backward
  contract change to FEAT-219.
- **C5 — Deterministic base, optional LLM refine.** Presentation metadata
  (columns/labels/tooltips) comes from the `DatasetSpatialProfile` registry
  (deterministic); an **optional** narrow LLM pass may add labels/format hints —
  deterministic always wins (same pattern as FEAT-218).
- **C6 — Configurable data shape per layer.** Each layer must support **both**
  a native GeoJSON `FeatureCollection` payload **and** a flattened
  rows+columns+geometry-ref payload (table-style), selectable per layer / per
  request.
- **C7 — Map-level metadata.** The config MUST carry: viewport (center/zoom or
  bbox, computed deterministically from features), the query geometry
  (point + radius from `SpatialFilterSpec`), an optional base-tile/style hint,
  and `title` + `description` + `explanation` framing (as CHART/TABLE).
- **C8 — Compact tooltips.** Tooltips are expressed as a **per-layer template**
  (à la `description_template`), never as pre-rendered per-element strings, to
  keep payloads bounded at large feature counts (apartments ≈ 879k).
- **C9 — Renderer reads from `response.data`.** On the agent path, `PandasAgent`
  invokes `DatasetManager.spatial_filter` as a tool; the renderer reads the
  spatial result from `response.data` (mirroring how `StructuredTableRenderer`
  reads the DataFrame).
- **C10 — Capping preserved.** Per-dataset hard cap + true `total_count` +
  `capped`/`truncated` flags must survive into the per-layer config.

---

## Options Explored

### Option A: Thin Wrapper — reuse the merged `SpatialFeatureCollection`, split in the renderer

A `StructuredMapRenderer` reads the **existing merged** `SpatialFeatureCollection`
from `response.data`, groups features by their `properties.source`/`layer`
discriminator, and emits a `StructuredMapConfig` with one layer per group.
FEAT-219's `spatial_filter` is left **untouched**.

✅ **Pros:**
- Zero changes to FEAT-219 — no contract break, no re-test of the spatial backend.
- Smallest blast radius; fastest to ship.
- The `source` discriminator already exists in every feature's `properties`.

❌ **Cons:**
- **Contradicts the Round-2 decision** (user chose "spatial_filter returns
  already-separated"). Grouping in the renderer re-derives structure the source
  could have provided directly.
- Per-dataset `total_count` / `geodesic_paths` are recorded at the collection
  level in FEAT-219, not per group — the renderer would have to reverse-map them.
- Grouping a 879k-feature merged collection in the renderer is wasteful vs.
  keeping groups separate upstream.

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` (v2, in-tree) | `StructuredMapConfig` model | Same as CHART/TABLE configs |
| — | No new deps | Pure in-tree |

🔗 **Existing Code to Reuse:**
- `packages/ai-parrot-visualizations/.../formats/structured_table.py` — renderer skeleton (extract/refine/route pattern).
- `parrot/tools/dataset_manager/spatial/contracts.py:168` — `SpatialFeatureCollection`.

---

### Option B: Homologated `STRUCTURED_MAP` mode + per-dataset spatial result (Recommended)

Introduce `OutputMode.STRUCTURED_MAP` and a `StructuredMapConfig` Pydantic model
homologated with the structured family, plus a `StructuredMapRenderer` registered
via `register_renderer(OutputMode.STRUCTURED_MAP, ...)`. **Modify FEAT-219** so
`spatial_filter` returns results grouped per dataset (a `Dict[str, SpatialLayerResult]`
or `List[SpatialLayerResult]` where each carries its own `features`, `total_count`,
`capped`, `geodesic`), keeping a thin compatibility shim or a bumped contract.

`StructuredMapConfig` shape (homologated):
- `layers: List[MapLayer]` — one per dataset; each `MapLayer` has `source`/`layer`
  id, `columns: List[MapColumn]` (reusing the `TableColumn` `name/type/title/format`
  vocabulary), `tooltip_template: str`, `label_field: Optional[str]`,
  `data_shape: Literal["geojson","rows"]`, and its own capping metadata.
- `data` — **INPUT-ONLY**, excluded from `output`, routed to `response.data`
  (the per-layer features/rows).
- Map-level: `viewport` (center/zoom or bbox), `query` (point+radius+unit from the
  `SpatialFilterSpec`), `base_layer` hint (optional), `title`, `description`,
  `explanation`.

The renderer reads the per-dataset spatial result from `response.data`, builds
one `MapLayer` per dataset deterministically (columns from
`DatasetSpatialProfile.property_cols` + types via `base_column_types`, tooltip
from `description_template`), optionally LLM-refines labels/format hints, computes
the viewport from feature bounds, and returns `(out_without_data, explanation)`.
`PandasAgent` gets a `STRUCTURED_MAP` branch in `bots/data.py` paralleling the
`STRUCTURED_CHART` branch (force the config as structured output / route to the
renderer).

✅ **Pros:**
- Full homologation with CHART/TABLE — same envelope, same `(out, explanation)`,
  same data-routing, frontend treats all three uniformly.
- Honors the Round-2 decision: clean per-dataset layers at the source; per-layer
  capping/`geodesic` flags map 1:1.
- Both data shapes (C6) and a per-layer tooltip template (C8) live naturally in
  `MapLayer`.
- Reuses the proven `TableColumn` type vocabulary + `base_column_types` +
  `canonical_records` machinery.

❌ **Cons:**
- **Breaks the FEAT-219 output contract** — `spatial_filter` return type changes;
  `spatial_filter_handler.py` and any deterministic-mode frontend caller must be
  updated (or served via a compatibility flag).
- Larger surface: enum + model + renderer + agent wiring + FEAT-219 refactor.
- Two data shapes double the renderer's serialization paths (GeoJSON vs rows).

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` (v2, in-tree) | `StructuredMapConfig` / `MapLayer` / `MapColumn` | mirror `StructuredTableConfig` |
| `pandas` (in-tree) | row flattening for `data_shape="rows"` | via `canonical_records` |
| — | No new external deps | Pure in-tree |

🔗 **Existing Code to Reuse:**
- `parrot/models/outputs.py:39` — `OutputMode` enum (add `STRUCTURED_MAP`); `:472` `TableColumn`; `:509` `StructuredTableConfig` (template for the new model).
- `packages/ai-parrot-visualizations/.../formats/structured_table.py:87` — `StructuredTableRenderer` (full renderer pattern: extract → base types → canonical rows → LLM refine → build config → exclude data → route to `response.data` → never raise).
- `parrot/outputs/formats/__init__.py` — `register_renderer` + `_MODULE_MAP` (add `STRUCTURED_MAP: ('.structured_map',)`).
- `parrot/outputs/formats/table_types.py:42,70` — `base_column_types`, `canonical_records`.
- `parrot/tools/dataset_manager/tool.py:4186` — `spatial_filter` (refactor to per-dataset grouping).
- `parrot/tools/dataset_manager/spatial/contracts.py` — `SpatialFilterSpec`, `DatasetSpatialProfile`, `SpatialFeatureCollection`.
- `parrot/bots/data.py:1499–1680` — `STRUCTURED_CHART` wiring (template for the `STRUCTURED_MAP` branch).
- `parrot/outputs/formatter.py:218,284` — `get_renderer` dispatch.

---

### Option C: Generalize into a `StructuredGeoConfig` superset (chart `type="map"` + spatial layers)

`StructuredChartConfig` already supports `type="map"` with `mapName`/GeoJSON for
choropleths. Option C unifies *all* geographic output under one extended config
that serves both choropleth charts and spatial point/feature layers, rather than
a dedicated `STRUCTURED_MAP`.

✅ **Pros:**
- One geographic contract; no third near-duplicate config.
- Frontend has a single geo entry point.

❌ **Cons:**
- Overloads `StructuredChartConfig` (already large, FEAT-215/robustness churn) —
  high regression risk to a stabilized model.
- Choropleth-by-region and spatial-point-layers are genuinely different shapes;
  forcing one schema produces many mutually-exclusive optional fields.
- Muddies the clean CHART/TABLE/MAP triad; harder for the LLM to target.

📊 **Effort:** High

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` (v2, in-tree) | extend `StructuredChartConfig` | high blast radius on a hot model |

🔗 **Existing Code to Reuse:**
- `parrot/models/outputs.py:310` — `StructuredChartConfig` (`type="map"`, `map_name`).

---

## Recommendation

**Option B** is recommended.

It is the only option that satisfies **C1 (homologation)** and **C4 (per-dataset
separation at the source)** simultaneously — the two hardest user constraints.
Option A is cheaper but explicitly contradicts the Round-2 decision and forces the
renderer to re-derive per-dataset capping/`geodesic` metadata that FEAT-219 records
at the collection level. Option C maximizes reuse but pays for it with high
regression risk on the already-churned `StructuredChartConfig`, and conflates two
fundamentally different geographic shapes.

The trade-off we accept with B is a **breaking change to the FEAT-219 output
contract** (`spatial_filter` return type + `spatial_filter_handler.py`). This is
acceptable because FEAT-219 is recent, internal, and has a contained set of
callers; the per-dataset grouping it requires is also independently desirable
(per-layer capping, cleaner manifest alignment). We will provide a compatibility
shim or a versioned envelope so the deterministic frontend path is not stranded.

---

## Feature Description

### User-Facing Behavior

A `PandasAgent` (or DB agent) invoked with `output_mode=OutputMode.STRUCTURED_MAP`
for a spatial query returns a single `StructuredMapConfig` JSON envelope:

- **`layers[]`** — one entry per requested dataset, each with: a `layer`/`source`
  id, `columns` (`name`/`type`/`title`/`format`), a `tooltip_template`, an optional
  `label_field`, a `data_shape` (`"geojson"` or `"rows"`), and per-layer capping
  metadata (`total_count`, `capped`, `geodesic`).
- **map-level** — `viewport` (center+zoom or bbox), `query` (point/radius/unit),
  optional `base_layer` hint, `title`, `description`, and `explanation`.
- **`data`** is *not* in the serialized config; the feature/row payload is routed
  to `response.data` exactly as CHART/TABLE do.

The frontend paints the Leaflet map entirely from this contract — no guessing
about which columns to show, how to label markers, what the tooltip says, or where
to center the map. The deterministic frontend path (no LLM) gets the same shape.

### Internal Behavior

1. **Agent path** — `PandasAgent` resolves the NL request, calls
   `DatasetManager.spatial_filter(spec)` as a tool; the per-dataset spatial result
   lands in `response.data`. A new `STRUCTURED_MAP` branch in `bots/data.py`
   parallels the `STRUCTURED_CHART` branch.
2. **Spatial backend (modified FEAT-219)** — `spatial_filter` returns results
   **grouped per dataset** (each group carries its own `features` + capping +
   `geodesic`), instead of one merged collection.
3. **Renderer** — `StructuredMapRenderer.render`:
   - reads the per-dataset spatial result from `response.data`;
   - for each dataset, builds a `MapLayer` deterministically: columns from
     `DatasetSpatialProfile.property_cols` typed via `base_column_types`, tooltip
     from `description_template`, label from a configured field;
   - serializes the layer payload in the requested `data_shape` (GeoJSON passthrough
     or `canonical_records` rows + geometry refs);
   - computes the map `viewport` from the union of feature bounds; copies the
     `query` geometry from the spec;
   - runs an **optional** LLM refine pass for labels/format hints (deterministic
     wins, hard types untouched);
   - builds `StructuredMapConfig`, excludes `data` from `output`, routes payload to
     `response.data`, returns `(out, explanation)`; never raises.
4. **Registration** — `register_renderer(OutputMode.STRUCTURED_MAP, system_prompt=...)`
   + `_MODULE_MAP[OutputMode.STRUCTURED_MAP] = ('.structured_map',)`.

### Edge Cases & Error Handling

- **No features** for a dataset → emit an empty layer (columns/metadata present,
  `data` empty) so the frontend can still toggle the layer; never drop it silently.
- **Mixed geometry sources** (lat/lng pair vs native `geom_col`) → viewport bounds
  computed from whatever geometry each layer exposes.
- **Capping** → per-layer `total_count`/`capped` preserved; viewport computed from
  *returned* (capped) features, flagged so the frontend knows it's partial.
- **LLM refine failure/timeout** → fall back to deterministic schema; never block.
- **Renderer failure** → `(None, error_message)` — never raise (C1).
- **`data_shape="rows"`** on a dataset with no flat columns → fall back to GeoJSON
  and log; do not crash.
- **Deterministic frontend path** (no agent) → same `StructuredMapConfig` via the
  handler, behind a compatibility/version flag so legacy callers aren't broken.

---

## Capabilities

### New Capabilities
- `structured-map-output`: `OutputMode.STRUCTURED_MAP` + `StructuredMapConfig` /
  `MapLayer` / `MapColumn` models + `StructuredMapRenderer` registered in the
  formats pipeline + `PandasAgent` wiring.

### Modified Capabilities
- `spatial-dataset-filter` (FEAT-219): `spatial_filter` return contract changes to
  per-dataset grouping; `spatial_filter_handler.py` updated; optional
  compatibility shim/version flag.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/models/outputs.py` | extends | add `OutputMode.STRUCTURED_MAP`; add `StructuredMapConfig`/`MapLayer`/`MapColumn` |
| `packages/ai-parrot-visualizations/.../formats/structured_map.py` | new | `StructuredMapRenderer` (mirrors `structured_table.py`) |
| `parrot/outputs/formats/__init__.py` | modifies | register module in `_MODULE_MAP` |
| `parrot/bots/data.py` | modifies | new `STRUCTURED_MAP` branch (parallels `STRUCTURED_CHART`) |
| `parrot/tools/dataset_manager/tool.py` | modifies | `spatial_filter` → per-dataset grouped result |
| `parrot/tools/dataset_manager/spatial/contracts.py` | extends | per-dataset result model; presentation hints on `DatasetSpatialProfile` |
| `parrot/handlers/spatial_filter_handler.py` | modifies | adapt to new contract / version flag |
| `parrot/bots/database/agent.py` | optional | mirror branch for DB agent (as it has for `STRUCTURED_TABLE`) |
| Frontend (Leaflet consumer) | depends on | new contract; coordinate the shape |

---

## Code Context

### User-Provided Code
_None pasted; requirements were given in prose during the discovery rounds._

### Verified Codebase References

#### Classes & Signatures
```python
# parrot/models/outputs.py:39
class OutputMode(str, Enum):
    ...
    STRUCTURED_CHART = "structured_chart"   # :72
    STRUCTURED_TABLE = "structured_table"   # :73  (FEAT-218)
    # STRUCTURED_MAP to be added

# parrot/models/outputs.py:472
class TableColumn(BaseModel):
    name: str       # :492  (matches a key in data rows)
    type: str       # :493  string|integer|number|boolean|date|datetime|time|duration|any
    title: str      # :500
    format: Optional[str]  # :501  currency|percent|email|uri|enum|id|code

# parrot/models/outputs.py:509
class StructuredTableConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)   # :528
    columns: List[TableColumn]   # :530
    data: List[dict]             # :533  INPUT-ONLY, excluded from output
    explanation: Optional[str]   # :540
    total_rows: Optional[int]    # :544
    truncated: bool              # :548

# parrot/models/outputs.py:310
class StructuredChartConfig(BaseModel):   # has type="map" + map_name (choropleth)

# parrot/tools/dataset_manager/spatial/contracts.py:20
class SpatialFilterSpec(BaseModel):
    point: Tuple[float, float]   # :33  (lat, lng)
    radius: float                # :37  gt=0
    unit: Literal["mi","km","m"] # :42
    datasets: List[str]          # :46  min_length=1

# parrot/tools/dataset_manager/spatial/contracts.py:106
class DatasetSpatialProfile(BaseModel):
    dataset: str                       # :127
    lat_col / lng_col / geom_col       # :128-133
    layer: str                         # :134  Leaflet layer id / GeoJSON source discriminator
    property_cols: List[str]           # :135  → feature.properties
    description_template: str          # :139  str.format_map template (tooltip seed)
    geodesic: bool                     # :143

# parrot/tools/dataset_manager/spatial/contracts.py:168
class SpatialFeatureCollection(BaseModel):
    type: Literal["FeatureCollection"]  # :187
    features: List[Dict]                # :191  each: geometry, properties(data+description+source), type
    total_count: int                    # :195
    capped: bool                        # :200
    geodesic_paths: Dict[str, bool]     # :204  per-dataset

# parrot/tools/dataset_manager/tool.py:4186
async def spatial_filter(self, spec: "SpatialFilterSpec",
                         cap_per_dataset: int = 1000) -> "SpatialFeatureCollection":
    ...   # currently MERGES all datasets into one collection — to be grouped per dataset

# packages/ai-parrot-visualizations/.../formats/structured_table.py:87
@register_renderer(OutputMode.STRUCTURED_TABLE, system_prompt=STRUCTURED_TABLE_SYSTEM_PROMPT)
class StructuredTableRenderer(BaseChart):
    async def render(self, response, *, environment="html",
                     row_limit=None, **kwargs) -> Tuple[Any, Optional[Any]]:
        ...   # extract → base_column_types → canonical_records → LLM refine
              # → build config → exclude {"data"} → response.data = cfg.data → (out, explanation)
              # never raises: returns (None, error_message) on failure

# parrot/outputs/formats/table_types.py:42
def base_column_types(df: pd.DataFrame) -> dict[str, str]: ...
# parrot/outputs/formats/table_types.py:70
def canonical_records(df: pd.DataFrame, row_limit: int = 1000) -> tuple[list[dict], int, bool]: ...
```

#### Verified Imports
```python
from parrot.models.outputs import OutputMode, StructuredTableConfig, TableColumn  # parrot/models/outputs.py
from parrot.outputs.formats import register_renderer, get_renderer                # parrot/outputs/formats/__init__.py
from parrot.outputs.formats.table_types import base_column_types, canonical_records
from parrot.tools.dataset_manager.spatial import (
    SpatialFilterSpec, DatasetSpatialProfile, SpatialFeatureCollection,
)  # parrot/tools/dataset_manager/spatial/__init__.py:8
```

#### Key Attributes & Constants
- `register_renderer(mode, system_prompt=None)` → decorator (parrot/outputs/formats/__init__.py)
- `_MODULE_MAP[OutputMode.X] = ('.module',)` lazy-import dispatch (same file)
- `RENDERERS` / `_PROMPTS` global dicts (same file)
- `Formatter._get_renderer(mode)` / dispatch at `parrot/outputs/formatter.py:218,284`
- `DatasetSpatialProfile.layer` is the **`source` discriminator** already written into each feature's `properties.source` (the natural per-layer key).

### Does NOT Exist (Anti-Hallucination)
- ~~`OutputMode.STRUCTURED_MAP`~~ — not defined (to be added).
- ~~`StructuredMapConfig`~~ / ~~`MapLayer`~~ / ~~`MapColumn`~~ — do not exist.
- ~~`StructuredMapRenderer`~~ / ~~`formats/structured_map.py`~~ — do not exist.
- ~~`PandasAgent` spatial/map output handling~~ — `bots/data.py` has no spatial branch.
- ~~per-dataset grouped `spatial_filter` output~~ — currently returns ONE merged `SpatialFeatureCollection`.
- ~~tooltip/label/column-type fields on `DatasetSpatialProfile`~~ — only `property_cols` + `description_template` exist today.
- ~~viewport/bbox computation anywhere~~ — no existing helper; new code.

---

## Parallelism Assessment

- **Internal parallelism**: Moderate. The contract models (`StructuredMapConfig`)
  and the FEAT-219 `spatial_filter` per-dataset refactor are a foundational layer
  that the renderer and `PandasAgent` wiring depend on — those must come first.
  After the contract lands, the renderer, the agent wiring, and the handler update
  can proceed with some independence, but they share `models/outputs.py` and
  `data.py`.
- **Cross-feature independence**: Touches files recently churned by FEAT-215
  (`StructuredChartConfig`, `data.py` structured branches) and FEAT-218
  (`structured_table.py`, `table_types.py`, `data.py`). Also **modifies FEAT-219**
  files (`tool.py`, `spatial/contracts.py`, `spatial_filter_handler.py`). Confirm
  no in-flight branch is editing these before starting.
- **Recommended isolation**: `per-spec` (single worktree, sequential tasks).
- **Rationale**: The contract change ripples through models → renderer → agent →
  handler with shared hot files (`data.py`, `outputs.py`); sequential tasks in one
  worktree avoid merge churn and keep the FEAT-219 contract migration atomic.

---

…(truncated)…
