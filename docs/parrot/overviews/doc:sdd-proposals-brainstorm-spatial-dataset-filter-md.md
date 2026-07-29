---
type: Wiki Overview
title: Brainstorm — Spatial Filtering for DatasetManager (deterministic + LLM-driven)
id: doc:sdd-proposals-brainstorm-spatial-dataset-filter-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: A PandasAgent over live geospatial datasets (USA apartments ~879k, public/private
---

---
type: brainstorm
feature: spatial-dataset-filter
base_branch: dev
status: open
related: [DatasetManager, PandasAgent, AgenTalk]
---

# Brainstorm — Spatial Filtering for DatasetManager (deterministic + LLM-driven)

## 1. Problem

A PandasAgent over live geospatial datasets (USA apartments ~879k, public/private
schools ~133k, hospitals, hotels, malls, universities, Pokemon warehouses, US Census)
must serve two consumption modes that produce **the same structured output**:

1. **LLM mode** — natural language ("show universities, colleges and schools within
   5 miles of warehouse XYZ") → the LLM emits a spatial filter → executed → structured
   features returned.
2. **Deterministic mode** — the frontend sends `(point, radius, [datasets])` directly,
   no LLM in the loop → executed → structured features returned.

Backend returns **structured data only** (point lists with properties + description).
The backend never renders maps. The frontend builds the map (e.g. one Leaflet layer
per dataset/`source`).

Datasets live in **heterogeneous backends**: some PostgreSQL (PostGIS-capable), some
BigQuery (`GEOGRAPHY`), some without spatial functions. The filter execution must be
backend-aware: push the predicate down to the engine where possible, fall back to a
bounded Pandas computation otherwise.

## 2. Codebase Contract (grep anchors, not line numbers)

What already exists and constrains the design:

| Symbol | File | Relevance |
|---|---|---|
| `class DatasetManager(AbstractToolkit)` | `tool.py` | Catalog + toolkit; spatial filter attaches here. `tool_prefix = "dataset"`. |
| `_pctx_var` ContextVar | `tool.py` | Per-call `PermissionContext` isolation across concurrent requests on a shared manager. **Reuse for scatter-gather** — no new mechanism needed. |
| `def _pre_execute` / `_pctx_var.set(pctx)` | `tool.py` | Where per-call permission context is established. |
| `_source_type_map` / `type(self.source)` dispatch | `tool.py` (`to_info`) | Existing precedent for dispatching on source type. Spatial routing dispatches on `source.driver` instead. |
| `def materialize` | `tool.py` | DataFrame-materialization path + Redis Parquet cache. **Spatial filter must NOT go through this** for large tables. |
| `def _apply_filter` | `tool.py` | Equality/`isin` filter on a materialized DataFrame — basis for the Pandas-fallback refine step. |
| `def _resolve_name` | `tool.py` | Name/alias resolution — spatial filter resolves dataset names through this. |
| `async def add_table_source` / `def add_query` / `def add_dataframe` | `tool.py` | Registration entry points; relevant to profile co-registration option (A). |
| `class DataSource(ABC)` (`fetch`, `prefetch_schema`, `describe`, `cache_key`, `has_builtin_cache`, `routing_meta`) | `base.py` | Source ABC. Note: **no connection/driver in the base** — those live on concrete sources. |
| `class TableSource` / `self.driver` / `_normalize_driver` | `table.py` | `driver` is first-class and normalized (`pg`, `bigquery`, `mysql`, …). **This is the backend discriminator.** |
| `def _get_connection_args` → `_resolve_credentials(self.driver)` | `table.py` | Returns `(credentials_dict, dsn)`. The Ibis backend must construct from this. |
| `def _build_filter_clause` (equality / `IN`) | `table.py` | Existing WHERE-fragment builder. A bbox prefilter is a `BETWEEN` variant of this same machinery. |
| `def _build_schema_query` | `table.py` | Per-driver INFORMATION_SCHEMA prefetch — confirms `pg`/`bigquery`/`mysql` are the live drivers. |
| `class CompositeDataSource` / `component_names` / `fetch` validation | `composite.py` | Precedent for a multi-dataset coordinator that validates every component exists and raises a descriptive `ValueError`. Spatial profile resolution copies this discipline. |
| `class InMemorySource` | `memory.py` | No driver, no I/O — falls into the Pandas path trivially. |

## 3. Proposed Architecture

Three layers; the transport question lives only in layer 3.

### 3.1 `SpatialFilterSpec` — backend-agnostic intent (Pydantic v2)

Emitted identically by the LLM (NL→spec) or the frontend (direct). Carries pure
geospatial intent; knows nothing about backends.

```python
class SpatialFilterSpec(BaseModel):
    point: tuple[float, float]          # (lat, lng)
    radius: float
    unit: Literal["mi", "km", "m"] = "mi"
    datasets: list[str]                 # resolved via _resolve_name
    # bbox/polygon variants deferred — see Non-Goals
```

### 3.2 `DatasetSpatialProfile` — declarative geo-semantics only

The profile carries **only** what the source does not know: which columns are
geometry and how to render a feature. It carries **no** driver/DSN/table — all
inherited from the source at execute time (prevents drift from connection identity).

```python
class DatasetSpatialProfile(BaseModel):
    dataset: str                        # FK to a registered dataset name
    lat_col: str | None = None          # naive lat/lng pair, OR…
    lng_col: str | None = None
    geom_col: str | None = None         # …a native geometry/geography column
    layer: str                          # Leaflet layer / GeoJSON `source` id
    property_cols: list[str]            # → feature.properties
    description_template: str           # e.g. "{name} ({type})"
    geodesic: bool = True               # honesty flag (records semantics, see 3.4)
```

### 3.3 Backend dispatch — collapses to ~2 branches (Ibis confirmed)

Routing keys on `getattr(source, "driver", None)`:

- `driver in {"pg", "bigquery"}` → **Ibis push-down**. One Ibis expression compiles to
  both dialects' `ST_DWITHIN`; connection built from `_get_connection_args()`. The
  per-backend hand-written SQL dialect registry is **eliminated** by Ibis.
- everything else (`mysql`, unknown driver, `Mongo`/`InMemory`) → **bbox-pushdown +
  Pandas haversine fallback**: derive bounding box from `(point, radius)`, push it as a
  `BETWEEN` predicate (extends `_build_filter_clause`), fetch only box survivors, refine
  with exact haversine in memory. The bbox is a cheap superset of the circle; never pull
  879k rows.

### 3.4 `spatial_filter` method + `SpatialCompiler`

`DatasetManager.spatial_filter` is a **thin method** (so the LLM sees it as a toolkit op
for NL→spec mode, and `_pctx_var` gives permission isolation for free). It orchestrates
only:

```
resolve profiles (validate, à la CompositeDataSource)
  → group datasets by (driver, connection)
  → asyncio.gather per group (RequestContext propagated via _pctx_var)
  → merge into one FeatureCollection
```

The per-backend translation lives in a separate `SpatialCompiler`
(`compile(spec, profile) -> CompiledQuery` deterministic / no I/O; `execute(...)` I/O).
**Manager orchestrates; compiler translates** — mirrors the loaders-vs-agents split. The
`compile` step is `syrupy`-snapshotable without touching a DB.

Each query projects geometry as GeoJSON in the SELECT (`ST_AsGeoJSON` / `ST_ASGEOJSON`)
so all backends return geometry in one format; feature assembly downstream is identical.

### 3.5 `FeatureCollection` contract (the real unifier)

GeoJSON `FeatureCollection`, one feature per record, `properties` carrying data +
description + a `source`/`layer` discriminator. Frontend maps directly to Leaflet layers
(`L.geoJSON` grouped by `source`) and is **agnostic to mode** — it cannot tell whether
the spec came from a user drag or LLM parsing.

Must contemplate capping + `total_count` (return N features + the true count) or
server-side clustering for high-density radii (apartments). Do not dump everything.

### 3.6 Manifest endpoint

A `get_manifest()` (new) serves three consumers from one source of truth: frontend layer
toggles, LLM dataset awareness, manager routing. Lists available spatial datasets, their
`layer` id, `geodesic` flag, and `property_cols`.

### 3.7 Transport — handler, not AgenTalk

The deterministic path is stateless request/response and must **not** pass through
`AbstractBot.run()` (no memory, hooks, lifecycle-event coupling it doesn't need). Since
LLM-builds-filter is one-shot structured output, **one thin HTTP handler serves both** the
direct filter and the NL→spec synthesis (put a synthesizer in front). AgenTalk gains a
typed envelope **only if** the UX is integrated (chat references the live map selection) —
and even then the envelope forwards to the same `spatial_filter`, it does not run the agent.

## 4. Options to Decide

### 4.1 Profile registration

| Option | Mechanism | Pros | Cons |
|---|---|---|---|
| **A — Co-registered** | `spatial=...` kwarg on `add_table_source`/`add_query`, stored on `DatasetEntry` | Automatic lifecycle (evict → profile gone); profile can't reference a missing dataset | Every registration call grows a param; can't profile datasets registered elsewhere |
| **B — Separate registry** | `SPATIAL_PROFILE_REGISTRY` keyed by dataset name; declarable in a manifest | Matches fractal registry pattern; manifest-driven; serves frontend manifest directly; independent of registration order | Referential integrity is now ours — must validate dataset exists (copy `CompositeDataSource.fetch` discipline) |

**Leaning B** (consistent with "declarativo y registrado" + manifest requirement).

### 4.2 Resolved decisions (carried from discussion)

- **Geometry in DB** — execution is in the engine (PostGIS / BigQuery functions), Pandas
  only as bounded fallback. ✔
- **Ibis** — confirmed to support `ST_DWITHIN`; used as the compilation layer for
  `pg` + `bigquery`. ✔
- **Boundary parity** — assumed between `pg` `geography` and BigQuery `GEOGRAPHY` (both
  geodesic). The `geodesic` flag records, per dataset, whether the actual path is geodesic
  or spherical-approximate — see Open Question 3.

## 5. Non-Goals (v1)

- **No bit-exact boundary parity** across all paths. Geodesic where a native geographic
  type exists; spherical haversine in the Pandas fallback. Recorded via `geodesic`, not
  guaranteed identical.
- **No spatial filter on `CompositeDataSource`.** The JOIN can relocate geometry columns
  (suffixes), making `geom_col` ambiguous, and the bbox would have to push into the
  geometry-owning component, not the joined result. Explicitly deferred.
- **No bbox/polygon query shapes** in v1 — radius only. `SpatialFilterSpec` is shaped to
  admit them later.
- **No map rendering** — ever. Backend returns features only.

## 6. Open Questions (to resolve in spec)

1. **[RISK] Ibis ⇄ navconfig connection mapping.** `_get_connection_args()` returns
   `(credentials_dict, dsn)`. `ibis.postgres.connect` wants host/port/user/password/
   database; `ibis.bigquery.connect` wants project_id + credentials. Does the navconfig
   credentials dict map cleanly onto Ibis's connect signatures, or is a translation shim
   required? **This is the single biggest unknown — spike before committing Ibis as the
   compilation layer.** If a shim is needed, weigh shim vs. hand-written dialect templates
   (the dialect work is ~2 small SQL templates and fully syrupy-friendly).

2. **bbox prefilter as a range predicate.** Can `_build_filter_clause` (or a sibling) be
   taught `BETWEEN`/range predicates for the fallback push-down without disturbing the
   existing equality/`IN` path? Confirm where the bbox WHERE injection lives relative to
   `_inject_permanent_filter`.

3. **`geodesic` resolution per path.** When Ibis routes a `pg` table through a non-`geography`
   column, the predicate degrades to planar. How is `geodesic` actually determined —
   declared on the profile, or inferred from the column type at compile time? Decide whether
   it's an input or an output of compilation.

4. **Profile registration shape** — A vs B (§4.1). Recommend B; confirm.

5. **Result capping / clustering policy.** Hard cap + `total_count`, or server-side
   clustering? Per-dataset or global? Apartments at a generous radius forces this.

6. **Cross-backend concurrency limits.** `asyncio.gather` across grouped backends — any
   per-connection pool ceiling in AsyncDB that bounds fan-out?

7. **Transport envelope.** HTTP handler only (default), or also a typed AgenTalk envelope?
   Decide by: does the chat need to reference the live map selection? If no → handler only.

## 7. Recommended Spec Sequence

1. `SpatialFilterSpec` + `FeatureCollection` contract + `DatasetSpatialProfile` + manifest
   (pure types, no I/O — unblocks frontend immediately).
2. `SpatialCompiler` Ibis backend (`pg` + `bigquery`) — gated on OQ1 spike.
3. Pandas bbox-fallback backend — gated on OQ2.
4. `DatasetManager.spatial_filter` orchestration (group → gather → merge).
5. HTTP handler (direct + NL→spec synthesis).
6. AgenTalk envelope — only if OQ7 resolves to "integrated UX".

## Revision History

| Date | Change |
|---|---|
| 2026-06-03 | Initial brainstorm. Backend discriminator = `source.driver`; Ibis collapses dialect registry to ~2 branches; profile carries geo-semantics only; transport = thin handler. Open Questions captured for `/sdd-spec`. |
