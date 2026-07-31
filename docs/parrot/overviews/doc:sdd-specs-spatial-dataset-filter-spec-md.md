---
type: Wiki Overview
title: 'Feature Specification: Spatial Filtering for DatasetManager'
id: doc:sdd-specs-spatial-dataset-filter-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: A `PandasAgent` over live geospatial datasets (USA apartments ~879k, public/private
relates_to:
- concept: mod:parrot.tools.dataset_manager
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.tool
  rel: mentions
---

---
# SDD flow type and base branch (FEAT-145).
# - type: feature  (default)  → base_branch: dev (or any non-main branch)
# - type: hotfix              → base_branch MUST be: main
type: feature
base_branch: dev
---

# Feature Specification: Spatial Filtering for DatasetManager

**Feature ID**: FEAT-219
**Date**: 2026-06-03
**Author**: Jesus Lara
**Status**: approved
**Target version**: TBD

> Source brainstorm: `sdd/proposals/spatial-dataset-filter.brainstorm.md`
> (Recommended Option **B** — separate `SPATIAL_PROFILE_REGISTRY` + Ibis-gated compiler).

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

A `PandasAgent` over live geospatial datasets (USA apartments ~879k, public/private
schools ~133k, hospitals, hotels, malls, universities, warehouses, US Census) must serve
**two consumption modes that produce the same structured output**:

1. **LLM mode** — natural language ("show universities, colleges and schools within
   5 miles of warehouse XYZ") → the LLM emits a spatial filter spec → executed →
   structured features returned.
2. **Deterministic mode** — the frontend sends `(point, radius, [datasets])` directly,
   no LLM in the loop → executed → structured features returned.

The backend returns **structured data only** (point lists with properties + description);
it never renders maps — the frontend builds the map (one Leaflet layer per
dataset/`source`). Datasets live in **heterogeneous backends**: some PostgreSQL
(PostGIS-capable), some BigQuery (`GEOGRAPHY`), some without spatial functions. Filter
execution must be backend-aware: push the predicate down to the engine where possible,
fall back to a bounded Pandas computation otherwise — **never pull 879k rows into memory**.

### Goals

- **G1** — One output contract: a GeoJSON `FeatureCollection` identical for both modes;
  the frontend cannot tell whether a spec came from a user drag or LLM parsing.
- **G2** — Backend-agnostic intent: a single `SpatialFilterSpec` emitted identically by
  LLM or frontend, knowing nothing about drivers/DSNs.
- **G3** — Push-down first: execute the predicate in the engine (`ST_DWITHIN`); Pandas
  haversine only as a *bounded* fallback after a bbox prefilter.
- **G4** — No full materialization of large tables for spatial queries.
- **G5** — Per-call permission isolation via the existing `_pctx_var` ContextVar across
  scatter-gather.
- **G6** — Result capping: hard cap + `total_count`, per-dataset.
- **G7** — Deterministic, snapshot-testable compilation (`compile` is I/O-free).
- **G8** — Manifest endpoint serving frontend layer toggles + LLM dataset awareness +
  manager routing from one source of truth.

### Non-Goals (explicitly out of scope)

- **No bit-exact boundary parity** across all paths (geodesic where a native geographic
  type exists; spherical haversine in the Pandas fallback — recorded via `geodesic`, not
  guaranteed identical).
- **No spatial filter on `CompositeDataSource`** (a JOIN relocates geometry columns,
  making `geom_col` ambiguous).
- **No bbox/polygon query shapes** in v1 — radius only (`SpatialFilterSpec` shaped to
  admit them later).
- **No map rendering** — ever. Backend returns features only.
- **No full chat↔map bidirectional state coupling** — the AgenTalk envelope is a typed
  pass-through only.
- *Co-registered profiles (`spatial=` kwarg) were rejected in brainstorm — see
  `proposals/spatial-dataset-filter.brainstorm.md` Option A. Profiles live in a standalone
  registry instead.*

---

## 2. Architectural Design

### Overview

Three layers; the transport question lives only in layer 3. Per brainstorm Option **B**:
a standalone `SPATIAL_PROFILE_REGISTRY` (manifest-driven, validated at execute time à la
`CompositeDataSource`) feeds a **manager-orchestrates / compiler-translates** split.

- **`DatasetManager.spatial_filter`** is a *thin* toolkit method (so the LLM sees it as a
  tool, and `_pctx_var` gives permission isolation for free). It orchestrates only:
  `resolve profiles (validate) → group datasets by (driver, connection) →
  asyncio.gather per group (RequestContext via _pctx_var) → merge into one
  FeatureCollection (hard cap + total_count)`.
- **`SpatialCompiler`** owns per-backend translation: `compile(spec, profile) ->
  CompiledQuery` is deterministic and I/O-free (snapshot-testable); `execute(...)`
  performs I/O. Routing keys on `getattr(source, "driver", None)`:
  - `driver in {"pg", "bigquery"}` → **engine push-down** (`ST_DWITHIN`), connection from
    `_get_connection_args()`. The compiler *internals* are **Ibis** if the OQ1 spike
    passes, otherwise ~2 hand-written SQL dialect templates (the contract and orchestration
    are unchanged either way).
  - everything else (`mysql`, unknown, `InMemorySource`) → **bbox prefilter + Pandas
    haversine**: derive bbox from `(point, radius)`, push as a `BETWEEN` predicate
    (extends `_build_filter_clause`), fetch only box survivors, refine with exact haversine.
  - Each query projects geometry as GeoJSON in the SELECT (`ST_AsGeoJSON` / `ST_ASGEOJSON`)
    so feature assembly is identical across backends.

### Component Diagram

```
Frontend (point,radius,[datasets]) ─┐
                                    ├─→ HTTP handler ──→ DatasetManager.spatial_filter
LLM (NL) ──→ NL→spec synthesizer ───┘                          │
AgenTalk typed envelope (pass-through) ───────────────────────→┘
                                                               │
        ┌──────────────────────────────────────────────────────┘
        ▼
  resolve profiles (SPATIAL_PROFILE_REGISTRY, validate)
        │
        ├─ group by (driver, connection)
        │
        ├─→ SpatialCompiler.compile(spec, profile) → CompiledQuery  (pure, snapshotable)
        │        ├─ pg / bigquery   → ST_DWITHIN push-down  (Ibis | dialect template)
        │        └─ mysql / unknown → bbox BETWEEN + Pandas haversine refine
        │
        ├─→ asyncio.gather(execute per group, _pctx_var propagated)
        │
        └─→ merge → FeatureCollection (hard cap N + total_count)
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `DatasetManager` (`tool.py`) | extends | new `spatial_filter` thin method; reuses `_pctx_var`, `_pre_execute`, `_resolve_name`, `_apply_filter`, `to_info`/`_source_type_map` dispatch precedent |
| `TableSource` (`table.py`) | extends | bbox `BETWEEN` predicate via `_build_filter_clause`; connection args via `_get_connection_args`; driver discriminator `self.driver` |
| `CompositeDataSource` (`composite.py`) | pattern reuse | copy validate-every-component discipline (`fetch`); spatial filter NOT applied to composites in v1 |
| `InMemorySource` (`memory.py`) | uses | no driver → falls into the Pandas/haversine path |
| AsyncDB | uses (existing) | query execution for push-down + bbox fetch |
| HTTP handler (aiohttp) | new | direct filter + NL→spec synthesis |
| AgenTalk | extends | typed pass-through envelope forwarding to `spatial_filter` (no agent loop) |
| `pyproject.toml` | modifies (conditional) | `ibis-framework` extra added only if OQ1 spike passes |

### Data Models

```python
# Pure contracts — no I/O. (Field names from brainstorm Code Context.)

class SpatialFilterSpec(BaseModel):
    point: tuple[float, float]          # (lat, lng)
    radius: float
    unit: Literal["mi", "km", "m"] = "mi"
    datasets: list[str]                 # resolved via DatasetManager._resolve_name
    # bbox/polygon variants deferred — see Non-Goals

class DatasetSpatialProfile(BaseModel):
    dataset: str                        # FK to a registered dataset name
    lat_col: str | None = None          # naive lat/lng pair, OR…
    lng_col: str | None = None
    geom_col: str | None = None         # …a native geometry/geography column
    layer: str                          # Leaflet layer / GeoJSON `source` id
    property_cols: list[str]            # → feature.properties
    description_template: str           # e.g. "{name} ({type})"
    geodesic: bool = True               # DECLARED hint; compiler verifies (see OQ geodesic)

# GeoJSON FeatureCollection — one feature per record; properties carry data +
# description + a `source`/`layer` discriminator. Capping is explicit:
class SpatialFeatureCollection(BaseModel):
    type: Literal["FeatureCollection"] = "FeatureCollection"
    features: list[dict]                # GeoJSON Feature objects
    total_count: int                    # TRUE count (>= len(features) when capped)
    capped: bool = False
    geodesic_paths: dict[str, bool]     # per-dataset: was the executed path geodesic?
```

### New Public Interfaces

```python
# DatasetManager gains a thin toolkit method (LLM-visible, _pctx_var isolated):
class DatasetManager(AbstractToolkit):
    async def spatial_filter(self, spec: SpatialFilterSpec) -> SpatialFeatureCollection:
        ...
    def get_manifest(self) -> list[dict]:   # spatial datasets: layer, geodesic, property_cols
        ...

# Standalone registry (Option B):
SPATIAL_PROFILE_REGISTRY: dict[str, DatasetSpatialProfile]  # keyed by dataset name

# Deterministic compiler (compile = pure, execute = I/O):
class SpatialCompiler:
    def compile(self, spec: SpatialFilterSpec, profile: DatasetSpatialProfile) -> CompiledQuery:
        ...
    async def execute(self, compiled: CompiledQuery, source) -> list[dict]:  # GeoJSON features
        ...
```

---

## 3. Module Breakdown

> These map to Task Artifacts in Phase 2. Recommended sequence from brainstorm §7.

### Module 1: Spatial Contracts + Profile Registry + Manifest
- **Path**: `parrot/tools/dataset_manager/spatial/contracts.py`,
  `parrot/tools/dataset_manager/spatial/registry.py`
- **Responsibility**: Pydantic `SpatialFilterSpec`, `DatasetSpatialProfile`,
  `SpatialFeatureCollection`; `SPATIAL_PROFILE_REGISTRY` keyed by dataset name with
  validate-at-register/execute discipline; `DatasetManager.get_manifest()`.
- **Depends on**: existing `pydantic`; `_resolve_name` (tool.py:599). **No I/O** —
  unblocks the frontend immediately.

### Module 2: Ibis connection spike (decision gate)
- **Path**: spike notes + `parrot/tools/dataset_manager/spatial/_ibis_probe.py` (throwaway)
- **Responsibility**: Determine whether `_get_connection_args()`'s `(credentials_dict,
  dsn)` maps cleanly onto `ibis.postgres.connect` / `ibis.bigquery.connect`. Output:
  GO (use Ibis) or NO-GO (use hand-written dialect templates). Resolves the OQ
  "Ibis ⇄ navconfig connection mapping".
- **Depends on**: Module 1; `_get_connection_args` (table.py:311).

### Module 3: SpatialCompiler — engine push-down (`pg` + `bigquery`)
- **Path**: `parrot/tools/dataset_manager/spatial/compiler.py`
- **Responsibility**: `compile()` (pure, `syrupy`-snapshotable) emitting `ST_DWITHIN` +
  `ST_AsGeoJSON` projection; `execute()` via AsyncDB. Ibis-backed or template-backed per
  Module 2 outcome. Verifies `geodesic` against the actual column type (declare + verify).
- **Depends on**: Modules 1, 2; `driver` (table.py:157), `_get_connection_args` (table.py:311).

### Module 4: SpatialCompiler — Pandas bbox fallback
- **Path**: `parrot/tools/dataset_manager/spatial/compiler.py` (fallback branch),
  `parrot/tools/dataset_manager/table.py` (bbox `BETWEEN` predicate)
- **Responsibility**: Derive bbox from `(point, radius)`; teach `_build_filter_clause` a
  `BETWEEN`/range predicate without disturbing the equality/`IN` path; fetch box survivors;
  refine with vectorized haversine (numpy). Records `geodesic=False` (spherical-approx).
- **Depends on**: Module 1; `_build_filter_clause` (table.py:391), `_inject_permanent_filter`
  (table.py:414), `_apply_filter` staticmethod (tool.py:821).

### Module 5: `DatasetManager.spatial_filter` orchestration
- **Path**: `parrot/tools/dataset_manager/tool.py`
- **Responsibility**: Thin toolkit method — resolve profiles (validate) → group by
  `(driver, connection)` → `asyncio.gather` per group with `_pctx_var` propagation → merge
  into one `SpatialFeatureCollection` with hard cap + `total_count` (per-dataset).
- **Depends on**: Modules 1, 3, 4; `_pctx_var` (tool.py:41), `_pre_execute` (tool.py:2558).

### Module 6: Transport — HTTP handler + typed AgenTalk pass-through envelope
- **Path**: handler under `parrot/handlers/` (aiohttp); AgenTalk envelope wiring
- **Responsibility**: One handler serving the direct `(point,radius,datasets)` filter and
  the NL→spec synthesis (synthesizer in front). Typed AgenTalk envelope forwarding to the
  same `spatial_filter` — does NOT run the agent loop / carry memory.
- **Depends on**: Module 5.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_spec_roundtrip` | M1 | `SpatialFilterSpec` validates units/point; rejects malformed |
| `test_profile_registry_validates_dataset` | M1 | Registering/executing a profile for an unknown dataset raises descriptive `ValueError` (à la composite) |
| `test_manifest_shape` | M1 | `get_manifest()` lists layer, geodesic, property_cols per spatial dataset |
| `test_compile_pg_snapshot` | M3 | `compile()` for a `pg` profile matches `syrupy` snapshot (ST_DWITHIN + ST_AsGeoJSON), no DB |
| `test_compile_bigquery_snapshot` | M3 | Same for `bigquery` dialect |
| `test_geodesic_verify` | M3 | geography column → geodesic=True; non-geography pg column → geodesic=False recorded + warning |
| `test_bbox_predicate_isolated` | M4 | bbox `BETWEEN` clause does not disturb existing equality/`IN` path |
| `test_haversine_refine` | M4 | bbox survivors refined to exact circle; box corners excluded |
| `test_capping_total_count` | M5 | dense result capped at N; `total_count` reports true count; `capped=True` |
| `test_group_by_driver_connection` | M5 | datasets grouped correctly; one gather task per group |
| `test_pctx_isolation` | M5 | concurrent calls keep distinct `PermissionContext` via `_pctx_var` |

### Integration Tests
| Test | Description |
|---|---|
| `test_deterministic_mode_e2e` | `(point,radius,[datasets])` → handler → `FeatureCollection` |
| `test_llm_mode_e2e` | NL → synthesizer → same `FeatureCollection` shape (mode-agnostic) |
| `test_mixed_backend_merge` | datasets across pg + mysql merge into one collection |
| `test_agentalk_envelope_passthrough` | envelope forwards to `spatial_filter`, no agent loop invoked |

### Test Data / Fixtures
```python
@pytest.fixture
def warehouse_point():
    return (40.7128, -74.0060)  # (lat, lng)

@pytest.fixture
def pg_school_profile():
    return DatasetSpatialProfile(
        dataset="schools", geom_col="geog", layer="schools",
        property_cols=["name", "type"], description_template="{name} ({type})",
        geodesic=True,
    )
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] All unit tests pass (`pytest tests/unit/ -v`)
- [ ] All integration tests pass (`pytest tests/integration/ -v`)
- [ ] **G1** — LLM mode and deterministic mode return an identical
      `SpatialFeatureCollection` shape (verified by `test_*_mode_e2e`).
- [ ] **G2** — A single `SpatialFilterSpec` drives both modes; it carries no
      driver/DSN information.
- [ ] **G3** — `pg`/`bigquery` datasets execute `ST_DWITHIN` push-down; non-spatial
      backends use bbox prefilter + bounded haversine (no full-table scan).
- [ ] **G4** — Spatial queries do NOT route through `DatasetEntry.materialize` / the
      Redis Parquet cache for large tables.
- [ ] **G5** — Concurrent `spatial_filter` calls keep isolated `PermissionContext` via
      `_pctx_var` (verified by `test_pctx_isolation`).
- [ ] **G6** — Results are capped at N per dataset and report a true `total_count` with
      `capped` flag.
- [ ] **G7** — `SpatialCompiler.compile()` is I/O-free and snapshot-tested with `syrupy`.
- [ ] **G8** — `get_manifest()` serves layer id, `geodesic`, and `property_cols` per
      spatial dataset.
- [ ] Profile registry validates that a referenced dataset exists (descriptive error).
- [ ] `geodesic` is declared on the profile AND verified against the executed column type;
      mismatches recorded, not fatal.
- [ ] No breaking changes to existing `DatasetManager` / `TableSource` public API.
- [ ] `ibis-framework` is added as a dependency ONLY if the Module 2 spike resolves GO.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor.** All references verified 2026-06-03 against the
> live source under `packages/ai-parrot/src/parrot/tools/dataset_manager/`. Carried forward
> from the brainstorm Code Context (re-verified — unchanged).

### Verified Imports
```python
from parrot.tools.dataset_manager.tool import DatasetManager       # tool.py:492
from parrot.tools.dataset_manager.base import DataSource           # base.py:23
from parrot.tools.dataset_manager.table import TableSource         # table.py:113
from parrot.tools.dataset_manager.composite import CompositeDataSource  # composite.py:65
from parrot.tools.dataset_manager.memory import InMemorySource     # memory.py:14
```

### Existing Class Signatures
```python
# parrot/tools/dataset_manager/tool.py
class DatasetManager(AbstractToolkit):                          # l.492
    tool_prefix: str = "dataset"                               # l.512
    def to_info(self, alias: Optional[str] = None) -> DatasetInfo:   # l.397
        # _source_type_map is a LOCAL dict here (l.420-432), NOT a class attr
    def _resolve_name(self, identifier: str) -> str: ...       # l.599
    @staticmethod
    def _apply_filter(df: pd.DataFrame, filter_dict: Dict[str, Any]) -> pd.DataFrame:  # l.821
    def add_dataframe(self, name: str, df: pd.DataFrame, ...): ...        # l.982
    def add_query(self, name: str, query_slug: str, ...): ...            # l.1292
    async def add_table_source(self, name: str, table: str, driver: str, *, ...): ...  # l.1345
    async def _pre_execute(self, tool_name: str, **kwargs) -> None:      # l.2558
        ...
        _pctx_var.set(pctx)                                    # l.2580

_pctx_var: contextvars.ContextVar = contextvars.ContextVar(   # l.41
    "dataset_manager_pctx", default=None)

class DatasetEntry:                                            # l.115 (plain class, NOT @dataclass)
    async def materialize(self, force: bool = False, **params) -> pd.DataFrame: ...  # l.240

# parrot/tools/dataset_manager/base.py
class DataSource(ABC):                                         # l.23
    self.routing_meta: Dict = ...                             # l.46
    async def prefetch_schema(self) -> Dict[str, str]: ...    # l.54
    @abstractmethod
    async def fetch(self, **params) -> pd.DataFrame: ...      # l.68
    @abstractmethod
    def describe(self) -> str: ...                            # l.89
    @property
    def has_builtin_cache(self) -> bool: ...                  # l.102
    @property
    @abstractmethod
    def cache_key(self) -> str: ...                           # l.115

# parrot/tools/dataset_manager/table.py
def _normalize_driver(driver: str) -> str: ...                # l.50  (module-level)
def _resolve_credentials(driver: str) -> Tuple[Optional[Dict], Optional[str]]: ...  # l.55 (module-level)
class TableSource(DataSource):                                # l.113
    self.driver = _normalize_driver(driver)                   # l.157
    def _get_connection_args(self) -> Tuple[Optional[Dict], Optional[str]]: ...  # l.311
    def _build_schema_query(self) -> Tuple[str, bool]: ...    # l.325
    def _build_filter_clause(self) -> str: ...                # l.391
    def _inject_permanent_filter(self, sql: str) -> str: ...  # l.414

# parrot/tools/dataset_manager/composite.py
class CompositeDataSource(DataSource):                        # l.65
    def component_names(self) -> List[str]: ...               # l.106
    async def fetch(self, filters: Optional[Dict[str, Any]] = None, **params) -> pd.DataFrame:  # l.161 (validates components)

# parrot/tools/dataset_manager/memory.py
class InMemorySource(DataSource): ...                         # l.14 (no driver, no I/O)
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `spatial_filter` | `_resolve_name()` | dataset name resolution | `tool.py:599` |
| `spatial_filter` | `_pctx_var` | permission isolation in gather | `tool.py:41` / `2558` |
| `SpatialCompiler` (engine) | `_get_connection_args()` | build connection | `table.py:311` |
| `SpatialCompiler` (engine) | `source.driver` | route pg/bigquery vs fallback | `table.py:157` |
| `SpatialCompiler` (fallback) | `_build_filter_clause()` | bbox `BETWEEN` predicate | `table.py:391` |
| `SpatialCompiler` (fallback) | `_apply_filter` / haversine | in-memory refine | `tool.py:821` |
| profile registry | `CompositeDataSource.fetch` validation pattern | copy discipline | `composite.py:161` |

### Does NOT Exist (Anti-Hallucination)
- ~~`ibis` / `ibis-framework`~~ — **not currently a dependency**; not imported anywhere in
  `dataset_manager`. Add only if Module 2 spike resolves GO; otherwise use dialect templates.
- ~~Any existing PostGIS / `ST_*` / geometry / spatial code~~ — **none exists**; greenfield.
- ~~`DatasetManager.materialize`~~ — `materialize` lives on **`DatasetEntry`** (tool.py:240).
- ~~`DataSource.driver`~~ — no driver on the base class; `driver` is first-class only on
  `TableSource`. Use `getattr(source, "driver", None)`.
- ~~`DatasetEntry` as a `@dataclass`~~ — it is a **plain class** (tool.py:115).
- ~~`_apply_filter` as an instance method~~ — it is a **`@staticmethod`** (tool.py:821).
- ~~`_source_type_map` as a class attribute~~ — it is a **local dict** inside `to_info()`
  (tool.py:420-432).

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Reuse the dispatch-on-source-type precedent (`to_info` / `_source_type_map`) but key
  spatial routing on `getattr(source, "driver", None)` instead.
- Copy `CompositeDataSource.fetch`'s validate-every-component discipline for profile
  referential integrity (validate at execute time).
- Manager orchestrates; compiler translates — mirrors the loaders-vs-agents split. Keep
  `compile()` pure so it is `syrupy`-snapshotable without a DB.
- Async-first throughout; `asyncio.gather` per `(driver, connection)` group with
  `_pctx_var` propagated into each task.
- Pydantic v2 for all contracts; `self.logger` for logging.

### Known Risks / Gotchas
- **Ibis credential mapping is the single biggest unknown** — gate it behind the Module 2
  spike; fall back to ~2 hand-written SQL dialect templates if the shim is ugly. Contract
  + orchestration are unchanged either way.
- **bbox predicate must not disturb the equality/`IN` path** in `_build_filter_clause`;
  confirm injection order relative to `_inject_permanent_filter` (table.py:414).
- **Dense radii** (apartments at generous radius) — hard cap + `total_count` per dataset;
  never dump everything.
- **`geodesic` degrades to planar** when a pg table uses a non-`geography` column — declare
  on the profile, verify at compile time, record the true path; warn on mismatch.
- **Cross-backend concurrency** — `asyncio.gather` fan-out may hit an AsyncDB per-connection
  pool ceiling (open question — confirm during Module 5).
- **Partial backend failure** during gather — failure policy is an open question
  (surface partial + error marker vs. fail whole request).
- **Cross-feature overlap with FEAT-218 (structured-table)** on `tool.py`/`table.py` —
  the `_build_filter_clause` change is the main conflict risk. See Worktree Strategy.

### External Dependencies
| Package | Version | Reason |
|---|---|---|
| `pydantic` | `>=2` | contracts (already a core dependency) |
| `numpy` | (present) | vectorized haversine refine in the fallback path |
| `syrupy` | (dev) | snapshot-test the deterministic `compile` step |
| `ibis-framework` | `>=9` (TBD) | **conditional** — compile one expression to PostGIS + BigQuery `ST_DWITHIN`; added ONLY if Module 2 spike resolves GO |

---

…(truncated)…
