---
type: Wiki Overview
title: 'Brainstorm: DatasetManager Common-Field Filtering (`define_filters`)'
id: doc:sdd-proposals-datasetmanager-filtering-brainstorm-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: A `DatasetManager` holds **multiple heterogeneous datasets** (SQL tables,
  query
relates_to:
- concept: mod:parrot.handlers.spatial_filter_handler
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.spatial.contracts
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.spatial.registry
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.tool
  rel: mentions
---

---
# SDD flow type and base branch (FEAT-145).
type: feature
base_branch: dev
---

# Brainstorm: DatasetManager Common-Field Filtering (`define_filters`)

**Date**: 2026-06-04
**Author**: Jesus Lara
**Status**: exploration
**Recommended Option**: B (with C as an optional convenience layer)

---

## Problem Statement

A `DatasetManager` holds **multiple heterogeneous datasets** (SQL tables, query
slugs, in-memory DataFrames, composites). Today each dataset is filtered
independently and ad-hoc: a SQL `WHERE`/`permanent_filter` on SQL-backed sources,
or a `filter={...}` dict (equality / `isin`) materialized through
`_apply_filter()` for in-memory frames. There is **no declarative way** to say
*"these columns are common across most datasets and these are the filtering
semantics for each one"*, and **no single call** that applies one filter request
recursively to every dataset that supports it.

Concrete use cases driving this:

1. **Geospatial** — 3 datasets all carry `latitude` / `longitude`; a single
   radius / proximity filter should hit all three. *(This already exists as the
   FEAT-219 spatial subsystem — see Code Context — and we want to fold it into
   the new unified surface rather than leave it as a parallel island.)*
2. **Categorical** — a `region` column present in most datasets; the frontend
   needs the list of **unique regions** to build a combo selector, sends
   `region = "North"`, and the manager applies it (`eq` / `ne` / `in`)
   **recursively** to every dataset that has the column. Datasets **without**
   the column are skipped.

The pain: there is no shared filter vocabulary, no recursive application, no
catalog of filterable fields for the frontend, and no method to obtain the
distinct values that populate a combo.

**Who is affected**: frontend developers (need a filter schema + value lists to
build UI), the LLM agent (would gain a clean filtering tool), and framework
users wiring up multi-dataset dashboards/maps.

## Constraints & Requirements

- **Generalize, don't duplicate** the FEAT-219 spatial subsystem: radius/proximity
  becomes one *filter kind* inside the new layer, delegating to the existing
  `SpatialCompiler` / `SPATIAL_PROFILE_REGISTRY` rather than reimplementing it.
- **Auto execution strategy**: SQL-backed sources (table/query) get the predicate
  pushed down into the `WHERE` clause; in-memory DataFrames are filtered with
  pandas. The manager chooses per source type.
- **Per-filter `required` flag**: `required=False` → silently skip datasets
  lacking the column; `required=True` → raise if any target dataset lacks it.
- **Value catalogs**: each filter may declare a `values_source` (query slug /
  source / column); when absent, the manager infers values via
  `DISTINCT`/`unique()` over the datasets that have the column (cached).
- **Result model**: `apply_filters()` is **ephemeral by default** (returns
  filtered results, manager untouched); `persist=True` registers filtered
  datasets back into the manager.
- **Surface**: programmatic API (`define_filters`, `apply_filters`,
  `get_filter_schema`, `get_filter_values`) **and** `AbstractToolkit` tools so the
  agent can filter; `get_filter_schema()` feeds the frontend.
- Async-first; Pydantic models for all contracts; no blocking I/O.
- Must coexist with PBAC (`_policy_guard`), `permanent_filter`, and
  `computed_columns` already on the manager.

---

## Options Explored

### Option A: Global Filter-Definition Registry (mirror FEAT-219 spatial)

Add a **module-level `FILTER_DEFINITION_REGISTRY`** plus a `FilterCompiler`,
structurally identical to the spatial subsystem: `register_filter_definition()`,
`get_filter_definition()`, `validate_definitions_exist()`. `define_filters()` is a
thin façade that registers `FilterDefinition` objects into that global dict; the
`spatial` kind reuses `SPATIAL_PROFILE_REGISTRY` directly.

✅ **Pros:**
- Maximum symmetry with FEAT-219 — same mental model, same test patterns
  (`compile()` I/O-free + `execute()` async, syrupy snapshots).
- Compiler is reusable outside a manager instance.

❌ **Cons:**
- **Global mutable state**: definitions keyed only by dataset/column leak across
  `DatasetManager` instances — bad for multi-tenant / multi-agent isolation
  (the spatial registry already has this smell; `get_manifest()` works around it
  by intersecting with `self._datasets`).
- "Common fields across *this* manager's datasets" is inherently
  instance-scoped; a global registry models the wrong ownership.

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` (v2) | Filter contracts | already core |
| `pandas` | in-memory filtering | already core |
| `asyncdb` | SQL push-down execution | already used by sources |

🔗 **Existing Code to Reuse:**
- `parrot/tools/dataset_manager/spatial/registry.py` — registry pattern to clone
- `parrot/tools/dataset_manager/spatial/compiler.py` — `compile()`/`execute()` split
- `parrot/tools/dataset_manager/spatial/contracts.py` — Pydantic contract style

---

### Option B: Manager-Owned Unified Filter Catalog *(recommended core)*

Store filter definitions **on the `DatasetManager` instance** (`self._filter_defs:
Dict[str, FilterDefinition]`). `define_filters([...])` is an **instance method**
that validates each definition against the registered datasets and stores it.
`apply_filters({...})` iterates the manager's datasets, and for each definition:

- resolves which datasets have the target column(s);
- routes SQL sources → push-down (extend the existing `permanent_filter`/WHERE
  machinery), in-memory frames → `_apply_filter()` (extended with `ne`/`range`);
- for `kind="spatial"`, **delegates to the existing `spatial_filter()`** using a
  bridged `DatasetSpatialProfile`.

`FilterDefinition` (Pydantic) carries: `column(s)`, `kind`
(`categorical`/`numeric`/`temporal`/`text`/`spatial`), allowed `ops`
(`eq`/`ne`/`in`/`not_in`/`range`/`radius`/…), `required: bool`, and optional
`values_source`. `get_filter_schema()` serializes the catalog for the frontend;
`get_filter_values(name)` returns the (cached) distinct values.

✅ **Pros:**
- Correct ownership: filters describe **this manager's** datasets; no global
  leakage, clean multi-tenant isolation.
- Directly extends machinery already on the manager (`_apply_filter`,
  `permanent_filter`, `_resolve_name`, `_column_types`, Redis cache).
- Spatial stays authoritative in its own subsystem; we only *delegate* to it —
  zero duplication, satisfies the "generalize/absorb" decision at the API level.
- `apply_filters(..., persist=False|True)` maps cleanly to ephemeral-vs-registered.

❌ **Cons:**
- Filter compilation logic lives closer to the (already large) `tool.py`; needs
  careful extraction into a `filtering/` submodule to avoid bloat.
- Slightly less symmetric with spatial's global registry (intentional divergence).

📊 **Effort:** Medium

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pydantic` (v2) | `FilterDefinition`, `FilterRequest`, `FilterResult` | core |
| `pandas` | in-memory filter execution | core |
| `asyncdb` | SQL `DISTINCT` + push-down | already wired into sources |
| `redis` (via existing cache) | cache distinct-value catalogs | reuse manager's Parquet/TTL cache |

🔗 **Existing Code to Reuse:**
- `parrot/tools/dataset_manager/tool.py:829` — `_apply_filter()` (extend with `ne`/`range`)
- `parrot/tools/dataset_manager/tool.py:864` — `add_dataset(..., permanent_filter=)` push-down precedent
- `parrot/tools/dataset_manager/tool.py:1388` — TableSource WHERE injection
- `parrot/tools/dataset_manager/tool.py:4186` — `spatial_filter()` (delegate for `kind=spatial`)
- `parrot/tools/dataset_manager/tool.py:633` — `categorize_columns()` for kind inference
- `parrot/handlers/spatial_filter_handler.py` — HTTP/AgenTalk transport pattern to mirror

---

### Option C: Capability Auto-Discovery (introspection-first) *(optional layer on B)*

Instead of declaring every column explicitly, the manager **introspects** each
dataset's columns (it already computes `_column_types` via `categorize_columns`)
and **auto-derives candidate common filters**: a column present in ≥N datasets,
typed `categorical` → `eq/ne/in`; `integer/float/datetime` → `range`; a declared
lat/lng pair → `radius`. `define_filters()` then only **overrides/annotates**
(restrict `ops`, mark `required`, attach `values_source`, rename label).

✅ **Pros:**
- Near-zero boilerplate for the common case ("just expose region & status").
- Leverages metadata the manager already maintains.
- Great default for the LLM agent (discoverability without configuration).

❌ **Cons:**
- "Common across most datasets" needs a heuristic threshold (ambiguous; surfaces
  noisy/unwanted filters).
- Auto-inferring value catalogs over many datasets can be expensive without the
  declared `values_source` short-circuit.
- Magic behavior can surprise; needs an explicit opt-in.

📊 **Effort:** Low (as an additive layer on top of B)

📦 **Libraries / Tools:**
| Package | Purpose | Notes |
|---|---|---|
| `pandas` | dtype/cardinality introspection | core |

🔗 **Existing Code to Reuse:**
- `parrot/tools/dataset_manager/tool.py:633` — `categorize_columns()`
- `DatasetEntry._column_types` / `_column_metadata` — already populated on fetch

---

## Recommendation

**Option B as the core, with Option C offered as an opt-in convenience layer.**

Reasoning, grounded in the Round 1/2 decisions:

- **Ownership matches the domain.** "Common fields across the datasets *in this
  manager*" is instance-scoped. Option A's global registry models the wrong
  ownership and re-introduces the cross-instance leakage the spatial subsystem
  already has to defend against in `get_manifest()`. B keeps definitions on the
  instance — clean multi-tenant/multi-agent isolation.
- **Generalize without duplicating (the explicit Round 1 decision).** B unifies
  the *API surface* (`define_filters`/`apply_filters`) while **delegating** the
  `spatial` kind to the existing, battle-tested `spatial_filter()` +
  `SpatialCompiler`. We absorb spatial at the façade, not by rewriting it — no
  second geodesic implementation to maintain.
- **Reuses what's there.** The auto push-down/pandas split (Round 1) is exactly
  the `permanent_filter`-WHERE vs `_apply_filter` distinction that already
  exists; B extends them rather than inventing a parallel engine.
- **C is cheap insurance for ergonomics** but stays opt-in so the "common across
  *most*" heuristic never fires surprising filters; the trade-off accepted is a
  little more upfront declaration in exchange for predictability.

What we trade off: slightly less structural symmetry with FEAT-219's global
registry, and we must carve filtering into its own `filtering/` submodule to keep
`tool.py` from growing. Both are acceptable and arguably improvements.

---

## Feature Description

### User-Facing Behavior

**For framework users (Python):**
```python
dm.define_filters([
    FilterDefinition(name="region", columns=["region"], kind="categorical",
                     ops=["eq", "ne", "in"], required=False,
                     values_source=QuerySlug("regions_catalog")),
    FilterDefinition(name="geo", columns=["latitude", "longitude"],
                     kind="spatial", ops=["radius"], required=False),
])

# ephemeral (default): manager untouched
result = await dm.apply_filters({"region": {"op": "in", "value": ["North", "West"]}})
result.applied   # ["stores", "sites"]
result.skipped   # ["weather"]  (no 'region' column)
result.datasets  # {"stores": <df>, "sites": <df>}

# persisted: registers filtered copies
await dm.apply_filters({"region": "North"}, persist=True)  # -> 'stores__North', ...
```

**For the frontend (HTTP):**
- `GET …/filters/schema` → the filter catalog (names, kinds, allowed ops, which
  datasets each applies to) to build the UI controls.
- `GET …/filters/{name}/values` → distinct values (from `values_source`, else
  inferred + cached) to populate a combo.
- `POST …/filters` → a filter request, returns per-dataset filtered results
  (spatial requests return the existing `SpatialResult`/GeoJSON shape unchanged).

**For the LLM agent:** the same operations exposed as `AbstractToolkit` tools
(`define_filters`, `apply_filters`, `list_filters`, `get_filter_values`).

### Internal Behavior

1. `define_filters()` validates each `FilterDefinition` against registered
   datasets (column presence, op⇄kind compatibility, `required` enforcement) and
   stores it on `self._filter_defs`. `kind="spatial"` bridges to / requires a
   `DatasetSpatialProfile`.
2. `apply_filters(request, persist)` resolves the request against the catalog,
   then for each affected dataset decides the execution path by source type:
   SQL → push-down predicate (extend WHERE/`permanent_filter` machinery);
   in-memory → extended `_apply_filter`; spatial → delegate to `spatial_filter()`.
3. Datasets missing the column are skipped (recorded in `result.skipped`) unless
   the definition is `required=True` (→ `ValueError`).
4. `get_filter_values()` returns declared catalog values, else a cached
   `UNION DISTINCT`/`unique()` over datasets carrying the column.
5. Results returned per dataset; `persist=True` registers filtered DataFrames as
   new entries.

### Edge Cases & Error Handling

- **Column absent everywhere** for a `required=True` filter → `ValueError` naming
  the filter and the offending datasets (mirror `validate_profiles_exist`).
- **Op not allowed** for a definition → `ValueError` listing allowed ops.
- **Mixed types** (e.g. `range` on a text column) → validated at `define_filters`
  time, not at apply time.
- **Empty result** after filtering → valid empty DataFrame, not an error.
- **`persist=True` name collision** → suffix policy + overwrite guard.
- **Value-catalog cost** → declared `values_source` short-circuits inference;
  inferred catalogs are cached with TTL and a cardinality cap.
- **PBAC interaction** → filtered columns must still pass `_policy_guard`
  (dropped/forbidden columns can't become filterable).

---

## Capabilities

### New Capabilities
- `datasetmanager-filtering`: declarative common-field filter definitions
  (`define_filters`) + recursive multi-dataset application (`apply_filters`) with
  auto push-down/pandas execution, per-filter `required`, value catalogs, and an
  ephemeral/persist result model.
- `dataset-filter-transport`: HTTP + AgenTalk surface exposing
  `filters/schema`, `filters/{name}/values`, and `POST filters` (mirrors the
  spatial handler).

### Modified Capabilities
- FEAT-219 spatial filtering — *no behavioral change*; surfaced as the `spatial`
  filter kind and delegated to. Touches only the integration seam, not the engine.

---

## Impact & Integration

| Affected Component | Impact Type | Notes |
|---|---|---|
| `parrot/tools/dataset_manager/tool.py` | extends | new `define_filters`/`apply_filters`/`get_filter_schema`/`get_filter_values`; extend `_apply_filter` (`ne`/`not_in`/`range`) |
| `parrot/tools/dataset_manager/filtering/` (new) | new | `contracts.py`, `registry`-free instance store, `compiler.py` (SQL push-down + pandas) |
| `parrot/tools/dataset_manager/spatial/*` | depends on | delegated to for `kind=spatial`; no edits expected |
| `parrot/handlers/` (new `filter_handler.py`) | new | HTTP + AgenTalk transport, modeled on `spatial_filter_handler.py` |
| `DatasetEntry` (`tool.py:123`) | depends on | reads `_column_types`/`_column_metadata` for kind inference & column presence |
| PBAC `_policy_guard` | depends on | filterable columns must respect column policy |
| LLM tool surface (`AbstractToolkit.get_tools`) | extends | new `@tool`s registered on the manager |

No breaking changes. No new third-party dependencies (all reuse `pydantic`,
`pandas`, `asyncdb`, existing cache).

---

## Code Context

### User-Provided Code
The user described the feature in prose (no code pasted). Verbatim intent:
> definir en "define_filters" que "latitude" y "longitude" son columnas por las
> que se pueden filtrar los 3 datasets y que el tipo de filtrado es por radio y/o
> proximidad … otro ejemplo sería una columna "region" donde el filtrado sería de
> igualdad, no-igualdad o "IN" … de dónde obtener ese listado de regiones únicas
> para … un selector combo … aplicar recursivamente el filtrado a todos los
> datasets; si un dataset no posee la columna se ignora.

### Verified Codebase References

#### Classes & Signatures
```python
# From parrot/tools/dataset_manager/tool.py
class DatasetManager(AbstractToolkit):                       # line 500
    self._datasets: Dict[str, DatasetEntry]                  # line 533

    @staticmethod
    def _apply_filter(df: pd.DataFrame,
                      filter_dict: Dict[str, Any]) -> pd.DataFrame:   # line 829
        # scalar -> ==, list/tuple/set -> isin(); ANDed; ValueError if col missing

    async def add_dataset(self, name: str, *, ...,
                          filter: Optional[Dict[str, Any]] = None,
                          permanent_filter: Optional[Dict[str, Any]] = None,
                          ...) -> str:                        # line 864
    @staticmethod
    def categorize_columns(df: pd.DataFrame) -> Dict[str, str]:       # line 633
        # -> boolean|integer|float|datetime|categorical|categorical_text|text

    async def materialize(self, name: str, force_refresh: bool = False,
                          **params) -> pd.DataFrame:          # line 3953
    def get_manifest(self) -> List[Dict[str, Any]]:           # line 4139
    async def spatial_filter(self, spec: "SpatialFilterSpec",
                             cap_per_dataset: int = 1000) -> "SpatialResult":  # line 4186

class DatasetEntry:                                           # line 123
    _df: Optional[pd.DataFrame]
    _column_types: Dict[str, str]
    _column_metadata: Dict[str, Dict[str, Any]]

# From parrot/tools/dataset_manager/spatial/contracts.py
class SpatialFilterSpec(BaseModel):                          # line 25
    point: Tuple[float, float]; radius: float; unit: Literal["mi","km","m"]
    datasets: List[str]
class DatasetSpatialProfile(BaseModel):                      # line 111
    dataset: str; lat_col/lng_col/geom_col: Optional[str]; layer: str
    property_cols: List[str]; geodesic: bool = True
class SpatialResult(BaseModel):                              # line 266
    version: Literal[2]; layers: Dict[str, SpatialLayerResult]

# From parrot/tools/dataset_manager/spatial/registry.py
SPATIAL_PROFILE_REGISTRY: Dict[str, DatasetSpatialProfile]   # line 29
def register_spatial_profile(profile) -> None                # line 32
def get_spatial_profile(dataset_name) -> DatasetSpatialProfile  # line 54
def validate_profiles_exist(dataset_names: List[str]) -> None   # line 79

# From parrot/tools/dataset_manager/spatial/compiler.py
class SpatialCompiler:   # compile() I/O-free + async execute(); pg/bigquery push-down,
                         # pandas bbox+haversine fallback for mysql/InMemory
_ENGINE_DRIVERS = frozenset({"pg", "bigquery"})              # compiler.py
```

#### Verified Imports
```python
from parrot.tools.dataset_manager.tool import DatasetManager
from parrot.tools.dataset_manager.spatial.contracts import (
    SpatialFilterSpec, DatasetSpatialProfile, SpatialResult, SpatialFeatureCollection,
)
from parrot.tools.dataset_manager.spatial.registry import (
    SPATIAL_PROFILE_REGISTRY, register_spatial_profile, get_spatial_profile,
    validate_profiles_exist,
)
from parrot.handlers.spatial_filter_handler import SpatialFilterHandler, SpatialFilterEnvelope
```

#### Key Attributes & Constants
- `DatasetManager._datasets` → `Dict[str, DatasetEntry]` (tool.py:533)
- `DatasetEntry._column_types` → `Dict[str, str]` (tool.py:123)
- `_ALLOWED_COLUMN_FORMATS` (spatial/contracts.py:20) — format-hint precedent for validation
- TableSource WHERE injection of `permanent_filter` (tool.py:1388); QuerySlug merge (tool.py:948)

### Does NOT Exist (Anti-Hallucination)
- ~~`DatasetManager.define_filters`~~ / ~~`apply_filters`~~ / ~~`get_filter_schema`~~ — **do not exist**; this feature creates them.
- ~~`DatasetManager.get_distinct` / `get_unique` / `get_filter_values`~~ — no distinct-value method exists today.
- ~~A "common fields" or filter-definition registry~~ — only the **spatial** profile registry exists.
- ~~Generic `ne` / `range` / `not_in` filter operators~~ — `_apply_filter` supports only `==` and `isin`.
- ~~A non-spatial filter HTTP handler~~ — only `spatial_filter_handler.py` exists.
- Ibis as a compile target — explicitly **NO-GO** (TASK-1437, noted in `compiler.py`); use hand-written SQL dialects.

---

## Parallelism Assessment

- **Internal parallelism**: Moderate. Natural task seams: (1) `FilterDefinition`/
  `FilterRequest`/`FilterResult` Pydantic contracts; (2) instance store +
  `define_filters` validation; (3) `apply_filters` execution engine (SQL
  push-down + pandas, extend `_apply_filter`); (4) spatial delegation bridge;
  (5) value-catalog (`get_filter_values`) + cache; (6) HTTP/AgenTalk transport;
  (7) LLM tool wiring. (1)→(2)→(3) are sequential; (5), (6), (7) can branch once
  contracts land.
- **Cross-feature independence**: Shares `tool.py` and the `dataset_manager/`
  package — **the** hotspot. The recent FEAT-224 (structured-config-homologation)
  worktree also touches dataset_manager/spatial; coordinate to avoid collisions.
  Putting new logic under a fresh `filtering/` submodule minimizes overlap; only
  `_apply_filter` extension and the new public methods edit `tool.py` directly.
- **Recommended isolation**: `per-spec` (all tasks sequential in one worktree).
- **Rationale**: The tasks are tightly coupled around shared `tool.py` state and
  the contracts they all consume; parallel worktrees would fight over `tool.py`.
  One worktree, dependency-ordered tasks is safer than the merge overhead.

---

## Open Questions

- [x] Flow type & base branch — *Owner: Jesus*: `feature` → `dev`.
- [x] Relationship to spatial subsystem — *Owner: Jesus*: generalize/absorb at the
  API surface; `spatial` is a filter kind delegating to existing `spatial_filter()`.
- [x] Execution location — *Owner: Jesus*: auto — SQL push-down for table/query
  sources, pandas for in-memory frames.
- [x] Missing-column behavior — *Owner: Jesus*: configurable per filter via
  `required` (skip when False, error when True).
- [x] Value catalog source — *Owner: Jesus*: declared `values_source` preferred;
  infer `UNION DISTINCT`/`unique()` (cached) as fallback.
- [x] Result model — *Owner: Jesus*: ephemeral by default; `persist=True` registers
  filtered datasets.
- [x] API surface — *Owner: Jesus*: programmatic API + `AbstractToolkit` tools +
  `get_filter_schema()` for the frontend.
- [ ] Definition storage: instance-scoped (`self._filter_defs`, Option B) vs global
  registry (Option A). Recommended **instance-scoped** — confirm at spec time. — *Owner: Jesus*
- [ ] Adopt Option C auto-discovery now (opt-in) or defer to a follow-up? — *Owner: Jesus*
- [ ] Operator vocabulary v1: confirm set (`eq, ne, in, not_in, range, radius`) and
  whether `like`/`contains` for text is in scope. — *Owner: Jesus*
- [ ] `persist=True` naming convention for filtered datasets (`<name>__<value>`?). — *Owner: Jesus*
- [ ] Inferred value-catalog cardinality cap + cache TTL defaults. — *Owner: Jesus*
- [ ] Coordinate `tool.py` edits with the in-flight FEAT-224 worktree. — *Owner: Jesus*
