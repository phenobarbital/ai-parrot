---
type: Wiki Overview
title: 'Brainstorm: Spatial Filtering for DatasetManager (deterministic + LLM-driven)'
id: doc:sdd-proposals-spatial-dataset-filter-brainstorm-md
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

# Brainstorm: Spatial Filtering for DatasetManager (deterministic + LLM-driven)

**Date**: 2026-06-03
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: B (separate spatial-profile registry) + Ibis-gated compiler

---

## Problem Statement

A `PandasAgent` over live geospatial datasets (USA apartments ~879k, public/private
schools ~133k, hospitals, hotels, malls, universities, warehouses, US Census) must serve
**two consumption modes that produce the same structured output**:

1. **LLM mode** — natural language ("show universities, colleges and schools within
   5 miles of warehouse XYZ") → the LLM emits a spatial filter spec → executed →
   structured features returned.
2. **Deterministic mode** — the frontend sends `(point, radius, [datasets])` directly,
   no LLM in the loop → executed → structured features returned.

The backend returns **structured data only** (point lists with properties + description).
It never renders maps — the frontend builds the map (one Leaflet layer per
dataset/`source`).

Datasets live in **heterogeneous backends**: some PostgreSQL (PostGIS-capable), some
BigQuery (`GEOGRAPHY`), some without spatial functions. Filter execution must be
backend-aware: push the predicate down to the engine where possible, fall back to a
bounded Pandas computation otherwise. **Never pull 879k rows into memory.**

Who is affected: end users (chat + map UX), frontend developers (need a single stable
contract regardless of mode), and ops (heterogeneous DB connections, concurrency).

## Constraints & Requirements

- **One output contract** — GeoJSON `FeatureCollection` identical for both modes; the
  frontend cannot tell whether a spec came from a user drag or LLM parsing.
- **Backend-agnostic intent** — a single `SpatialFilterSpec` emitted identically by LLM
  or frontend; it knows nothing about drivers/DSNs.
- **Push-down first** — execute the predicate in the engine (PostGIS / BigQuery
  `ST_DWITHIN`); Pandas haversine only as a *bounded* fallback after a bbox prefilter.
- **No full materialization** — large tables must NOT go through `DatasetEntry.materialize`
  / the Redis Parquet cache path for spatial queries.
- **Per-call permission isolation** — reuse the existing `_pctx_var` ContextVar so
  scatter-gather across backends keeps each request's `PermissionContext`.
- **Result capping** — hard cap + `total_count` (return N features + the true count);
  never dump everything for dense radii.
- **Deterministic, testable compilation** — the `compile(spec, profile) -> CompiledQuery`
  step is pure (no I/O) and `syrupy`-snapshotable without a DB.
- **No map rendering, ever** — features only.

---

## Options Explored

> Three axes were explored: (1) **profile registration shape**, (2) **backend
> compilation strategy**, (3) **transport**. The options below are framed around the
> primary architectural decision — *how spatial intent is registered and dispatched* —
> because that choice drives the rest.

### Option A: Co-registered profiles (`spatial=` kwarg)

Attach `DatasetSpatialProfile` at registration time via a `spatial=...` kwarg on
`add_table_source` / `add_query`, stored on the existing `DatasetEntry`. Dispatch still
keys on `source.driver`.

✅ **Pros:**
- Automatic lifecycle — evict the dataset, the profile is gone with it.
- A profile can never reference a missing dataset (referential integrity is free).
- No new registry object to maintain.

❌ **Cons:**
- Every registration call grows another parameter.
- Cannot profile datasets that were registered elsewhere / out of band.
- Does not directly serve the **manifest** requirement (frontend layer toggles need a
  standalone, queryable source of truth).

📊 **Effort:** Low

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` (v2) | `DatasetSpatialProfile` model | already a core dependency |

🔗 **Existing Code to Reuse:**
- `parrot/tools/dataset_manager/tool.py` — `add_table_source` (l.1345), `add_query`
  (l.1292), `add_dataframe` (l.982); `DatasetEntry` (l.115).

---

### Option B: Separate spatial-profile registry  ⭐ recommended

A standalone `SPATIAL_PROFILE_REGISTRY` keyed by dataset name, declarable in a manifest,
independent of registration order. Dispatch keys on `getattr(source, "driver", None)`.
Compilation lives in a separate `SpatialCompiler` (deterministic `compile` + I/O
`execute`); the manager only orchestrates (resolve → group → gather → merge).

✅ **Pros:**
- Matches the project's fractal registry pattern ("declarativo y registrado").
- **Manifest-driven** — `get_manifest()` serves one source of truth to three consumers
  (frontend layer toggles, LLM dataset awareness, manager routing).
- Independent of registration order; can profile datasets registered anywhere.
- Clean **manager-orchestrates / compiler-translates** split mirrors the
  loaders-vs-agents separation and keeps `compile` snapshot-testable.

❌ **Cons:**
- Referential integrity becomes ours — must validate the dataset exists before executing
  (copy `CompositeDataSource.fetch`'s validate-every-component discipline, l.161).
- One more object to keep in sync with dataset lifecycle (mitigated: validate at execute
  time, à la composite).

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` (v2) | `SpatialFilterSpec`, `DatasetSpatialProfile`, `FeatureCollection` | core dependency |
| `ibis-framework` | compile one expression to PostGIS + BigQuery `ST_DWITHIN` | **NOT yet a dependency** — gated behind a spike (OQ1) |
| `numpy` | vectorized haversine in the Pandas fallback | already present |
| `syrupy` | snapshot-test the deterministic `compile` step | dev dependency |

🔗 **Existing Code to Reuse:**
- `parrot/tools/dataset_manager/tool.py` — `_pctx_var` (l.41), `_pre_execute` (l.2558),
  `_resolve_name` (l.599), `_apply_filter` staticmethod (l.821), `to_info`/`_source_type_map`
  (l.397/420).
- `parrot/tools/dataset_manager/table.py` — `driver`/`_normalize_driver` (l.157/50),
  `_get_connection_args` (l.311), `_build_filter_clause` (l.391), `_inject_permanent_filter`
  (l.414).
- `parrot/tools/dataset_manager/composite.py` — validation discipline (l.161).

---

### Option C: Per-driver hand-written SQL dialect registry (no Ibis)

Skip Ibis entirely. Maintain a small registry of per-driver SQL templates: a `pg`
`ST_DWithin(geography, ...)` template and a BigQuery `ST_DWITHIN(GEOGRAPHY, ...)`
template, each a `BETWEEN`/`ST_*` extension of the existing `_build_filter_clause`
machinery. Still uses Option B's separate registry + orchestration.

✅ **Pros:**
- Zero new heavyweight dependency; fully under our control.
- ~2 small SQL templates — completely deterministic and `syrupy`-friendly.
- Sidesteps OQ1 (the navconfig→Ibis credential-mapping unknown) entirely.

❌ **Cons:**
- We own dialect drift — every new backend = another template + tests.
- More surface area than a single Ibis expression that compiles to both dialects.
- Re-implements what Ibis gives for free if the credential shim turns out clean.

📊 **Effort:** Medium (low per-template, but grows per backend)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` (v2) | shared contracts | core |
| (none new) | hand-written SQL templates | uses existing `asyncdb` execution |

🔗 **Existing Code to Reuse:**
- `parrot/tools/dataset_manager/table.py` — `_build_filter_clause` (l.391) as the template
  base; `_build_schema_query` (l.325) confirms `pg`/`bigquery`/`mysql` are the live drivers.

---

## Recommendation

**Option B** is recommended — a separate `SPATIAL_PROFILE_REGISTRY` with a
manager-orchestrates / compiler-translates split — **with Ibis gated behind a spike, and
Option C (hand-written dialect templates) as the pre-approved fallback** if the spike
shows the navconfig→Ibis credential mapping is ugly.

Reasoning:
- B directly satisfies the **manifest** requirement (frontend toggles + LLM awareness +
  routing from one source of truth), which A cannot serve cleanly and which is a hard
  requirement here.
- The registry's only real cost — referential integrity — is already solved in the
  codebase by `CompositeDataSource`'s validate-at-fetch discipline, so we copy a proven
  pattern rather than invent one.
- Ibis collapses the dialect work to a single expression for `pg`+`bigquery`, **but** its
  viability hinges entirely on OQ1 (credential mapping). Rather than bet the architecture
  on an unproven shim, the spec gates Ibis behind a time-boxed spike (task #2) and keeps
  Option C as the deterministic fallback. Either way the *contract* and *orchestration*
  (Option B) are unchanged — only the compiler's internals differ. This is the cheap
  insurance: the risky dependency is isolated behind a stable seam.

Trade-off accepted: we take on referential-integrity bookkeeping (validate dataset exists
at execute time) in exchange for a manifest-driven, order-independent design that serves
three consumers from one place.

---

## Feature Description

### User-Facing Behavior

- **Chat user**: asks "show schools and universities within 5 mi of warehouse XYZ"; the
  LLM synthesizes a `SpatialFilterSpec`; the backend returns a `FeatureCollection` the
  frontend renders as Leaflet layers grouped by `source`.
- **Map user (deterministic)**: drags a radius on the map; the frontend POSTs
  `(point, radius, [datasets])` to the same handler; gets back the *same*
  `FeatureCollection`. The frontend is **mode-agnostic**.
- **Integrated UX (this feature, per decision)**: AgenTalk gains a **typed pass-through
  envelope** so chat can reference a live map selection. The envelope forwards to the
  same `spatial_filter` — it does **not** run the agent loop or carry memory/lifecycle.
- **Manifest**: `get_manifest()` lists available spatial datasets, each with its `layer`
  id, `geodesic` flag, and `property_cols` — driving frontend layer toggles and LLM
  dataset awareness.

### Internal Behavior

Three layers; transport lives only in layer 3.

1. **Contracts (pure types, no I/O)** — `SpatialFilterSpec` (point, radius, unit,
   datasets), `DatasetSpatialProfile` (geo-semantics only: lat/lng or geom column, layer,
   property_cols, description_template, geodesic), `FeatureCollection` (GeoJSON, one
   feature per record, `properties` carrying data + description + `source`/`layer`
   discriminator + `total_count`).
2. **`SpatialCompiler`** — `compile(spec, profile) -> CompiledQuery` is deterministic and
   I/O-free (snapshot-testable); `execute(...)` performs I/O. Routing keys on
   `getattr(source, "driver", None)`:
   - `driver in {"pg", "bigquery"}` → **engine push-down** (`ST_DWITHIN`), connection
     built from `_get_connection_args()`. *Compiler internals = Ibis (if spike passes) or
     hand-written templates (fallback).*
   - everything else (`mysql`, unknown, `InMemorySource`) → **bbox prefilter + Pandas
     haversine**: derive bbox from `(point, radius)`, push as a `BETWEEN` predicate
     (extends `_build_filter_clause`), fetch only box survivors, refine with exact
     haversine in memory.
   - Each query projects geometry as GeoJSON in the SELECT (`ST_AsGeoJSON` /
     `ST_ASGEOJSON`) so feature assembly is identical across backends.
3. **`DatasetManager.spatial_filter`** — a thin toolkit method (so the LLM sees it as a
   tool, and `_pctx_var` gives permission isolation for free). It orchestrates only:
   `resolve profiles (validate) → group datasets by (driver, connection) →
   asyncio.gather per group (RequestContext via _pctx_var) → merge into one
   FeatureCollection (with hard cap + total_count)`.
4. **Transport** — one thin HTTP handler serves both the direct filter and the NL→spec
   synthesis (a synthesizer sits in front of the direct path); plus the typed AgenTalk
   pass-through envelope forwarding to the same `spatial_filter`.

### Edge Cases & Error Handling

- **Unknown / unprofiled dataset** → descriptive `ValueError` at resolve time (copy
  `CompositeDataSource` discipline); never silently drop.
- **Dense radius (apartments, large radius)** → hard cap on returned features +
  `total_count` reporting the true count (per-dataset cap).
- **`geodesic` mismatch** → profile *declares* intent; compiler *verifies* against the
  actual column type at compile time and records the true path in the result (geography →
  geodesic; planar/haversine → spherical-approximate). Mismatch is recorded, not fatal.
- **Backend without spatial functions** → bbox prefilter + bounded haversine; never pull
  the full table.
- **Partial backend failure during gather** → decide per-group failure policy in spec
  (surface partial results + error, vs. fail whole request) — see Open Questions.
- **CompositeDataSource targets** → explicitly rejected in v1 (geometry column ambiguous
  after JOIN).

---

## Capabilities

### New Capabilities
- `spatial-dataset-filter`: backend-aware radius filtering over registered datasets,
  emitting a unified GeoJSON `FeatureCollection` for both LLM and deterministic modes.
- `spatial-profile-registry`: standalone, manifest-backed registry of
  `DatasetSpatialProfile` entries keyed by dataset name.
- `spatial-manifest`: `get_manifest()` endpoint listing spatial datasets, layer ids,
  geodesic flags, and property columns.

### Modified Capabilities
- `dataset-manager` (`parrot/tools/dataset_manager/`): gains the `spatial_filter` toolkit
  method + bbox `BETWEEN` predicate support in the filter-clause machinery.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/tools/dataset_manager/tool.py` | extends | new `spatial_filter` thin method; reuses `_pctx_var`, `_resolve_name`, `_apply_filter` |
| `parrot/tools/dataset_manager/table.py` | extends | bbox `BETWEEN` predicate via `_build_filter_clause`; connection args via `_get_connection_args` |
| `parrot/tools/dataset_manager/composite.py` | depends on (pattern) | copies validate-every-component discipline; spatial filter NOT applied to composites in v1 |
| New: `SpatialCompiler`, `SPATIAL_PROFILE_REGISTRY`, contracts | new | Pydantic contracts + compiler module |
| HTTP handler (aiohttp) | new | direct filter + NL→spec synthesis |
| AgenTalk envelope | new (typed pass-through) | forwards to `spatial_filter`; no agent loop |
| `ibis-framework` dependency | new (conditional) | added only if OQ1 spike passes; else not added |
| `pyproject.toml` | modifies | conditional `ibis-framework` extra |

---

## Code Context

### User-Provided Code

```python
# Source: user-provided (draft brainstorm) — proposed contracts, NOT yet implemented

class SpatialFilterSpec(BaseModel):
    point: tuple[float, float]          # (lat, lng)
    radius: float
    unit: Literal["mi", "km", "m"] = "mi"
    datasets: list[str]                 # resolved via _resolve_name
    # bbox/polygon variants deferred — see Non-Goals

class DatasetSpatialProfile(BaseModel):
    dataset: str                        # FK to a registered dataset name
    lat_col: str | None = None          # naive lat/lng pair, OR…
    lng_col: str | None = None
    geom_col: str | None = None         # …a native geometry/geography column
    layer: str                          # Leaflet layer / GeoJSON `source` id
    property_cols: list[str]            # → feature.properties
    description_template: str           # e.g. "{name} ({type})"
    geodesic: bool = True               # hint; compiler verifies (OQ3)
```

### Verified Codebase References

> All paths are under `packages/ai-parrot/src/parrot/tools/dataset_manager/`.
> Verified 2026-06-03 against the live source.

#### Classes & Signatures
```python
# From parrot/tools/dataset_manager/tool.py
class DatasetManager(AbstractToolkit):                          # l.492
    tool_prefix: str = "dataset"                                # l.512

_pctx_var: contextvars.ContextVar = contextvars.ContextVar(    # l.41
    "dataset_manager_pctx", default=None)

class DatasetManager:
    async def _pre_execute(self, tool_name: str, **kwargs) -> None:  # l.2558
        ...
        _pctx_var.set(pctx)                                     # l.2580
    def to_info(self, alias: Optional[str] = None) -> DatasetInfo:   # l.397
        # _source_type_map is a LOCAL dict here, l.420-432 (not a class attr)
    def _resolve_name(self, identifier: str) -> str: ...        # l.599
    @staticmethod
    def _apply_filter(df: pd.DataFrame, filter_dict: Dict[str, Any]) -> pd.DataFrame:  # l.821
    def add_dataframe(self, name: str, df: pd.DataFrame, ...): ...        # l.982
    def add_query(self, name: str, query_slug: str, ...): ...            # l.1292
    async def add_table_source(self, name: str, table: str, driver: str, *, ...): ...  # l.1345

class DatasetEntry:                                            # l.115 (plain class, NOT @dataclass)
    async def materialize(self, force: bool = False, **params) -> pd.DataFrame: ...  # l.240

# From parrot/tools/dataset_manager/base.py
class DataSource(ABC):                                         # l.23
    self.routing_meta: Dict = ...                              # l.46
    async def prefetch_schema(self) -> Dict[str, str]: ...     # l.54
    @abstractmethod
    async def fetch(self, **params) -> pd.DataFrame: ...       # l.68
    @abstractmethod
    def describe(self) -> str: ...                             # l.89
    @property
    def has_builtin_cache(self) -> bool: ...                   # l.102
    @property
    @abstractmethod
    def cache_key(self) -> str: ...                            # l.115

# From parrot/tools/dataset_manager/table.py
def _normalize_driver(driver: str) -> str: ...                 # l.50  (module-level)
def _resolve_credentials(driver: str) -> Tuple[Optional[Dict], Optional[str]]: ...  # l.55 (module-level)
class TableSource(DataSource):                                 # l.113
    self.driver = _normalize_driver(driver)                    # l.157
    def _get_connection_args(self) -> Tuple[Optional[Dict], Optional[str]]: ...  # l.311
    def _build_schema_query(self) -> Tuple[str, bool]: ...     # l.325
    def _build_filter_clause(self) -> str: ...                 # l.391
    def _inject_permanent_filter(self, sql: str) -> str: ...   # l.414

# From parrot/tools/dataset_manager/composite.py
class CompositeDataSource(DataSource):                         # l.65
    def component_names(self) -> List[str]: ...                # l.106
    async def fetch(self, filters: Optional[Dict[str, Any]] = None, **params) -> pd.DataFrame:  # l.161 (validates components)

# From parrot/tools/dataset_manager/memory.py
class InMemorySource(DataSource): ...                          # l.14 (no driver, no I/O → Pandas path)
```

#### Verified Imports
```python
# Confirmed to resolve (module: parrot.tools.dataset_manager):
from parrot.tools.dataset_manager.tool import DatasetManager      # tool.py:492
from parrot.tools.dataset_manager.base import DataSource          # base.py:23
from parrot.tools.dataset_manager.table import TableSource        # table.py:113
from parrot.tools.dataset_manager.composite import CompositeDataSource  # composite.py:65
from parrot.tools.dataset_manager.memory import InMemorySource    # memory.py:14
```

#### Key Attributes & Constants
- `TableSource.driver` → normalized str (`pg`, `bigquery`, `mysql`, …) — **the backend
  discriminator** (table.py:157).
- `_pctx_var` → module-level `ContextVar(default=None)` set in `_pre_execute` (tool.py:41/2580).
- `DatasetManager.tool_prefix` → `"dataset"` (tool.py:512).
- `_apply_filter` is a **`@staticmethod`** (tool.py:821) — basis for the Pandas-fallback refine.
- `_source_type_map` is a **local dict inside `to_info()`** (tool.py:420-432), not a class attribute.

### Does NOT Exist (Anti-Hallucination)
- ~~`ibis` / `ibis-framework`~~ — **not currently a dependency**; not imported anywhere in
  `dataset_manager`. Must be added (gated on OQ1 spike) or avoided (Option C).
- ~~Any existing PostGIS / `ST_*` / geometry / spatial code~~ — **none exists** in the
  `dataset_manager` sources; this is greenfield.
- ~~`DatasetManager.materialize`~~ — `materialize` lives on **`DatasetEntry`**
  (tool.py:240), not on the manager.
- ~~`DataSource.driver`~~ — **no driver/connection on the base class**; `driver` is
  first-class only on `TableSource` (use `getattr(source, "driver", None)`).
- ~~`DatasetEntry` as a `@dataclass`~~ — it is a **plain class** (tool.py:115).

---

## Parallelism Assessment

- **Internal parallelism**: Moderate. The pure contracts + manifest (task 1) unblock the
  frontend and can land first. The Ibis spike (task 2), the Pandas bbox-fallback backend
  (task 3), and the handler/envelope (tasks 5–6) have some independence, but the
  `SpatialCompiler` is a shared seam they all touch — so most work serializes through it.
- **Cross-feature independence**: Touches `parrot/tools/dataset_manager/{tool,table}.py`,
  which is also the focus of in-flight FEAT-218 (structured-table). **Shared files** =
  `tool.py`, `table.py` → coordinate to avoid conflicts; the bbox change to
  `_build_filter_clause` is the main overlap risk.
- **Recommended isolation**: `per-spec` (all tasks sequential in one worktree).
- **Rationale**: The shared `SpatialCompiler` seam plus overlap with FEAT-218 on
  `tool.py`/`table.py` means independent worktrees would conflict more than they
  parallelize. Sequential execution in one worktree keeps the filter-clause and compiler
  changes coherent.

---

## Open Questions

- [x] **Profile registration shape (A vs B)** — *Owner: Jesus*: **B — separate
  `SPATIAL_PROFILE_REGISTRY`**, manifest-driven, validate dataset exists at execute time
  (copy `CompositeDataSource.fetch` discipline).
- [x] **Result capping / clustering policy** — *Owner: Jesus*: **Hard cap +
  `total_count`** for v1, applied per-dataset; server-side clustering deferred (contract
  shaped to admit it later).
- [x] **Transport envelope** — *Owner: Jesus*: **HTTP handler + typed AgenTalk
  pass-through envelope** (integrated UX). Envelope forwards to `spatial_filter`; it does
  NOT run the agent loop.
- [x] **Ibis adoption** — *Owner: Jesus*: **Gate behind a time-boxed spike** (spec task
  #2). If the navconfig→Ibis credential mapping is clean, use Ibis for `pg`+`bigquery`;
  otherwise fall back to Option C (~2 hand-written SQL dialect templates,
  `syrupy`-snapshotable). The Option B contract + orchestration are unchanged either way.
- [x] **`geodesic` resolution per path** — *Owner: Jesus*: **Declare + verify.** Profile
  declares `geodesic` as a hint; the compiler verifies against the actual column type at
  compile time and records the true path (geodesic vs spherical-approximate) in the
  result, warning on mismatch.
- [ ] **bbox prefilter as a range predicate** — *Owner: spec*: Can `_build_filter_clause`
  (or a sibling) gain `BETWEEN`/range predicates for the fallback push-down without
  disturbing the existing equality/`IN` path? Confirm where the bbox WHERE injection sits
  relative to `_inject_permanent_filter` (table.py:414).
- [ ] **Ibis ⇄ navconfig connection mapping** — *Owner: spike (task #2)*: Does
  `_get_connection_args()`'s `(credentials_dict, dsn)` map cleanly onto
  `ibis.postgres.connect` (host/port/user/password/database) and `ibis.bigquery.connect`
  (project_id + credentials), or is a translation shim required? This is the decision
  gate for Ibis vs Option C.
- [ ] **Cross-backend concurrency limits** — *Owner: spec*: Does `asyncio.gather` across
  grouped backends hit any per-connection pool ceiling in AsyncDB that bounds fan-out?
- [ ] **Partial backend-failure policy during gather** — *Owner: spec*: On one group
  failing, surface partial results + an error marker, or fail the whole request?

---

…(truncated)…
