---
type: Wiki Overview
title: 'Feature Specification: DatasetManager Common-Field Filtering (`define_filters`)'
id: doc:sdd-specs-datasetmanager-filtering-spec-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: A `DatasetManager` holds **multiple heterogeneous datasets** (SQL tables,
  query
relates_to:
- concept: mod:parrot.handlers.spatial_filter_handler
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.filtering
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.spatial.contracts
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.spatial.registry
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.tool
  rel: mentions
---

---
type: feature
base_branch: dev
---

# Feature Specification: DatasetManager Common-Field Filtering (`define_filters`)

**Feature ID**: FEAT-225
**Date**: 2026-06-04
**Author**: Jesus Lara
**Status**: approved
**Target version**: 0.26.0

---

## 1. Motivation & Business Requirements

> Why does this feature exist? What problem does it solve?

### Problem Statement

A `DatasetManager` holds **multiple heterogeneous datasets** (SQL tables, query
slugs, in-memory DataFrames, composites). Today each dataset is filtered
independently and ad-hoc: a SQL `WHERE`/`permanent_filter` on SQL-backed sources,
or a `filter={...}` dict (equality / `isin`) materialized through `_apply_filter()`
for in-memory frames. There is **no declarative way** to say *"these columns are
common across most datasets and these are the filtering semantics for each one"*,
and **no single call** that applies one filter request recursively to every
dataset that supports it.

Driving use cases:

1. **Geospatial** — 3 datasets all carry `latitude` / `longitude`; a single
   radius / proximity filter should hit all three. This already exists as the
   FEAT-219 spatial subsystem (`spatial_filter()` + `SpatialCompiler`); we want to
   fold it into the new unified surface rather than leave it a parallel island.
2. **Categorical** — a `region` column present in most datasets; the frontend
   needs the list of **unique regions** to build a combo selector, sends
   `region = "North"`, and the manager applies it (`eq` / `ne` / `in`)
   **recursively** to every dataset that has the column. Datasets **without** the
   column are skipped.

Who is affected: frontend developers (need a filter schema + value lists to build
UI), the LLM agent (gains a clean filtering tool), and framework users wiring
multi-dataset dashboards/maps.

### Goals

- Declarative `define_filters([...])` that names common columns, their filter
  `kind`, allowed operators, a `required` flag, and an optional value catalog
  source — stored **on the manager instance**.
- `apply_filters(request, persist=False)` that applies a filter request
  **recursively** across every dataset that has the target column(s).
- **Auto execution strategy**: SQL-backed sources get the predicate pushed into
  the `WHERE` clause; in-memory DataFrames are filtered with pandas — chosen per
  source type.
- **Per-filter `required`**: `required=False` → silently skip datasets lacking the
  column; `required=True` → raise if any target dataset lacks it.
- **Value catalogs**: declared `values_source` preferred; inferred
  `DISTINCT`/`unique()` (cached) fallback — to populate frontend combos.
- **Result model**: ephemeral by default; `persist=True` registers filtered
  datasets back into the manager.
- **Generalize, don't duplicate** FEAT-219: `spatial` is one filter kind that
  **delegates** to the existing `spatial_filter()` / `SpatialCompiler`.
- Surface as programmatic API **and** `AbstractToolkit` tools, plus
  `get_filter_schema()` for the frontend and an HTTP/AgenTalk transport.
- Opt-in **auto-discovery** (`suggest_filters()`) that proposes filter
  definitions from existing column introspection.

### Non-Goals (explicitly out of scope)

- Reimplementing geodesic/radius math — `kind="spatial"` delegates to the
  existing FEAT-219 engine; no second implementation.
- A **global** filter-definition registry — rejected in brainstorm (Option A) for
  cross-instance state leakage; definitions are instance-scoped. See
  `proposals/datasetmanager-filtering.brainstorm.md` Option A.
- Text-search operators (`like`/`contains`/`startswith`) — deferred; v1 operator
  set is `eq, ne, in, not_in, range, radius`.
- Cross-dataset JOINs (already covered by `CompositeDataSource`).

---

## 2. Architectural Design

### Overview

Adopt **Option B** from the brainstorm: filter definitions live **on the
`DatasetManager` instance** (`self._filter_defs: Dict[str, FilterDefinition]`).
`define_filters([...])` validates each definition against the registered datasets
and stores it. `apply_filters(request, persist)` resolves the request against the
catalog and, for each affected dataset, routes execution by source type:

- **SQL sources** (table / query) → predicate pushed into the `WHERE` clause,
  extending the existing `permanent_filter`/WHERE machinery.
- **In-memory DataFrames** → extended `_apply_filter()` (adds `ne`/`not_in`/`range`).
- **`kind="spatial"`** → **delegates** to the existing `spatial_filter()` using a
  bridged `DatasetSpatialProfile`; returns the existing `SpatialResult` shape.

Datasets missing the target column are skipped (recorded in `result.skipped`)
unless the definition is `required=True` (→ `ValueError`). New non-spatial filter
compilation lives in a new `parrot/tools/dataset_manager/filtering/` submodule to
keep `tool.py` from growing; only `_apply_filter` extension and the new public
methods edit `tool.py` directly.

`get_filter_schema()` serializes the catalog for the frontend; `get_filter_values()`
returns declared catalog values, else a cached `UNION DISTINCT`/`unique()` over the
datasets that have the column. `suggest_filters()` (opt-in) proposes
`FilterDefinition`s from `categorize_columns()` / `_column_types`.

### Component Diagram

```
Frontend / LLM agent
      │  (HTTP / @tool)
      ▼
DatasetFilterHandler ──→ DatasetManager.apply_filters(request, persist)
                              │
        ┌─────────────────────┼───────────────────────────┐
        ▼                     ▼                           ▼
  FilterCompiler        _apply_filter()             spatial_filter()  (FEAT-219)
  (SQL push-down)       (in-memory pandas)          └─ SpatialCompiler / registry
        │                     │                           │
        └─────────────────────┴───────────────────────────┘
                              ▼
                        FilterResult  (applied / skipped / per-dataset data)
                              │  persist=True
                              ▼
                  DatasetManager._datasets (new filtered entries)

DatasetManager.define_filters([...])  ──→ self._filter_defs
DatasetManager.get_filter_schema()    ──→ catalog for frontend
DatasetManager.get_filter_values(name)──→ values_source | inferred DISTINCT (cached)
DatasetManager.suggest_filters()      ──→ proposals from categorize_columns()
```

### Integration Points

| Existing Component | Integration Type | Notes |
|---|---|---|
| `DatasetManager` (`tool.py:500`) | extends | new instance store `_filter_defs` + public methods |
| `DatasetManager._apply_filter` (`tool.py:829`) | modifies | add `ne`/`not_in`/`range` operators (keeps `eq`/`in`) |
| `permanent_filter` WHERE injection (`tool.py:1388`, QuerySlug merge `tool.py:948`) | uses | push-down path for SQL sources |
| `DatasetManager.spatial_filter` (`tool.py:4186`) | delegates to | `kind="spatial"` requests |
| `SPATIAL_PROFILE_REGISTRY` / `DatasetSpatialProfile` (spatial/registry.py, contracts.py) | uses | bridge for spatial kind |
| `DatasetEntry._column_types` / `categorize_columns` (`tool.py:123`, `:633`) | reads | column presence + kind inference / `suggest_filters` |
| `materialize()` (`tool.py:3953`) + Redis/Parquet cache | uses | in-memory fetch + value-catalog caching |
| PBAC `_policy_guard` | depends on | filterable columns must respect column policy |
| `AbstractToolkit.get_tools` | extends | new `@tool`s on the manager |
| `spatial_filter_handler.py` | mirrors | transport pattern for new `DatasetFilterHandler` |

### Data Models

```python
# parrot/tools/dataset_manager/filtering/contracts.py  (NEW)
from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, Field

FilterKind = Literal["categorical", "numeric", "temporal", "text", "spatial"]
FilterOp = Literal["eq", "ne", "in", "not_in", "range", "radius"]

class ValuesSource(BaseModel):
    """Where to obtain the distinct values that populate a frontend combo."""
    query_slug: Optional[str] = None
    column: Optional[str] = None          # column to DISTINCT over
    dataset: Optional[str] = None         # restrict inference to one dataset

class FilterDefinition(BaseModel):
    """A declarative common-field filter over the manager's datasets."""
    name: str = Field(..., description="Stable filter id used in requests/schema.")
    columns: List[str] = Field(..., min_length=1,
        description="Column(s); spatial uses [lat, lng] or a single geom col.")
    kind: FilterKind
    ops: List[FilterOp] = Field(..., min_length=1)
    required: bool = Field(default=False,
        description="True → error if a target dataset lacks the column(s).")
    values_source: Optional[ValuesSource] = None
    label: Optional[str] = None
    description: Optional[str] = None

class FilterCondition(BaseModel):
    """A single applied condition in a request."""
    op: FilterOp
    value: Any = None                     # scalar | list | {min,max} | radius spec

class FilterResult(BaseModel):
    """Ephemeral per-dataset outcome of apply_filters."""
    applied: List[str] = Field(default_factory=list)
    skipped: List[str] = Field(default_factory=list)   # missing column (required=False)
    # per-dataset payload is returned alongside (DataFrames not serialized here)
```

`apply_filters` accepts a request mapping `{filter_name: scalar | list |
FilterCondition | dict}`; a bare scalar/list is sugar for `eq`/`in`.

### New Public Interfaces

```python
# parrot/tools/dataset_manager/tool.py  (additions to DatasetManager)
class DatasetManager(AbstractToolkit):
    self._filter_defs: Dict[str, FilterDefinition]   # NEW instance store

    def define_filters(self, definitions: List[FilterDefinition]) -> None:
        """Validate against registered datasets and store filter definitions."""

    async def apply_filters(
        self,
        request: Dict[str, Any],
        *,
        persist: bool = False,
    ) -> "FilterResult":
        """Apply a filter request recursively across all matching datasets.

        SQL sources → WHERE push-down; in-memory → pandas; spatial → spatial_filter().
        Ephemeral by default; persist=True registers filtered datasets.
        """

    def get_filter_schema(self) -> List[Dict[str, Any]]:
        """Serialize the filter catalog for the frontend (names, kinds, ops, datasets)."""

    async def get_filter_values(self, name: str) -> List[Any]:
        """Distinct values for a filter: values_source if declared, else cached DISTINCT."""

    def suggest_filters(self) -> List[FilterDefinition]:
        """Opt-in: propose FilterDefinitions from column introspection (no side effects)."""
```

---

## 3. Module Breakdown

> These map directly to Task Artifacts in Phase 2.

### Module 1: Filter Contracts
- **Path**: `parrot/tools/dataset_manager/filtering/contracts.py` (new)
- **Responsibility**: Pydantic models — `FilterDefinition`, `ValuesSource`,
  `FilterCondition`, `FilterResult`; op⇄kind validation (e.g. `radius`⇒`spatial`,
  `range`⇒`numeric`/`temporal`). I/O-free, mirrors `spatial/contracts.py` style.
- **Depends on**: existing `pydantic` only.

### Module 2: Instance Store + `define_filters` Validation
- **Path**: `parrot/tools/dataset_manager/tool.py` (extend) + helpers in
  `filtering/store.py` (new, optional)
- **Responsibility**: `self._filter_defs` init; `define_filters()` validates each
  definition against registered datasets (column presence, op/kind, `required`
  semantics deferred to apply time but contract-validated here), stores them.
  `kind="spatial"` requires/bridges a `DatasetSpatialProfile`.
- **Depends on**: Module 1.

### Module 3: Filter Compiler (SQL push-down + pandas)
- **Path**: `parrot/tools/dataset_manager/filtering/compiler.py` (new) + extend
  `_apply_filter` in `tool.py`
- **Responsibility**: Translate `FilterCondition` → SQL `WHERE` fragment for SQL
  sources (reuse `permanent_filter` injection precedent) and → pandas mask for
  in-memory frames. Add `ne`/`not_in`/`range` to `_apply_filter`. `compile()`
  I/O-free where feasible.
- **Depends on**: Modules 1, 2.

### Module 4: `apply_filters` Orchestration + Spatial Delegation
- **Path**: `parrot/tools/dataset_manager/tool.py` (extend)
- **Responsibility**: Resolve request vs catalog; per dataset decide path
  (SQL/pandas/spatial); skip-or-error per `required`; assemble `FilterResult`;
  `persist=True` registers filtered datasets (naming policy — see §8).
  `kind="spatial"` delegates to `spatial_filter()`.
- **Depends on**: Modules 1–3.

### Module 5: Value Catalogs (`get_filter_values`) + Cache
- **Path**: `parrot/tools/dataset_manager/filtering/values.py` (new) + `tool.py`
- **Responsibility**: Return declared `values_source` values (query slug / column);
  else infer `UNION DISTINCT`/`unique()` across datasets having the column, with
  cardinality cap + TTL caching (reuse manager cache).
- **Depends on**: Modules 1, 2.

### Module 6: Schema + Suggest (`get_filter_schema`, `suggest_filters`)
- **Path**: `parrot/tools/dataset_manager/tool.py` (extend)
- **Responsibility**: `get_filter_schema()` serializes catalog (which datasets each
  filter applies to). `suggest_filters()` proposes definitions from
  `categorize_columns()`/`_column_types` (opt-in, no side effects).
- **Depends on**: Modules 1, 2.

### Module 7: LLM Tools + HTTP/AgenTalk Transport
- **Path**: `parrot/tools/dataset_manager/tool.py` (`@tool` wiring) +
  `parrot/handlers/dataset_filter_handler.py` (new)
- **Responsibility**: Expose `define_filters`/`apply_filters`/`list_filters`/
  `get_filter_values` as `AbstractToolkit` tools; HTTP routes
  (`filters/schema`, `filters/{name}/values`, `POST filters`) + AgenTalk envelope,
  modeled on `spatial_filter_handler.py`.
- **Depends on**: Modules 4, 5, 6.

---

## 4. Test Specification

### Unit Tests
| Test | Module | Description |
|---|---|---|
| `test_filter_definition_op_kind_validation` | 1 | `radius` rejected unless `kind=spatial`; `range` requires numeric/temporal |
| `test_filter_definition_serialization` | 1 | round-trips via Pydantic |
| `test_define_filters_stores_on_instance` | 2 | definitions land in `_filter_defs`; no global state |
| `test_define_filters_spatial_requires_profile` | 2 | `kind=spatial` without `DatasetSpatialProfile` → `ValueError` |
| `test_apply_filter_pandas_ne_range_notin` | 3 | extended `_apply_filter` handles new ops; `eq`/`in` unchanged |
| `test_compiler_sql_where_pushdown` | 3 | `eq`/`in`/`range` produce expected WHERE fragments per driver |
| `test_apply_filters_recursive_skip` | 4 | dataset without column skipped; `result.skipped` populated (required=False) |
| `test_apply_filters_required_raises` | 4 | `required=True` + missing column → `ValueError` naming dataset |
| `test_apply_filters_spatial_delegates` | 4 | `kind=spatial` routes to `spatial_filter()`, returns `SpatialResult` |
| `test_apply_filters_persist_registers` | 4 | `persist=True` adds new dataset entries; default leaves manager untouched |
| `test_get_filter_values_declared_source` | 5 | declared `values_source` wins |
| `test_get_filter_values_inferred_cached` | 5 | inference unions DISTINCT, caps cardinality, caches |
| `test_get_filter_schema_lists_applicable_datasets` | 6 | schema shows per-filter dataset applicability |
| `test_suggest_filters_from_introspection` | 6 | proposes categorical/numeric/spatial candidates; no side effects |

### Integration Tests
| Test | Description |
|---|---|
| `test_end_to_end_region_filter_mixed_sources` | define `region`, apply `in [North,West]` across a SQL source + an in-memory DF + a source lacking the column → correct rows, correct skip |
| `test_end_to_end_spatial_via_define_filters` | define `geo` spatial filter, apply radius → matches existing `spatial_filter` output |
| `test_filter_handler_schema_values_apply` | HTTP: GET schema, GET values, POST apply return expected payloads |

### Test Data / Fixtures
```python
@pytest.fixture
def manager_with_three_datasets():
    # stores (SQL/in-memory with region+lat/lng), sites (region+lat/lng),
    # weather (lat/lng only, NO region) — to exercise recursive skip.
    ...
```

---

## 5. Acceptance Criteria

> This feature is complete when ALL of the following are true:

- [ ] All unit tests pass (`pytest tests/unit/ -v`)
- [ ] All integration tests pass (`pytest tests/integration/ -v`)
- [ ] `define_filters([...])` stores definitions **on the instance** (no global registry).
- [ ] `apply_filters(request)` applies **recursively** to all datasets with the column;
      datasets lacking the column are **skipped** and reported in `result.skipped`.
- [ ] A `required=True` filter raises `ValueError` (naming the dataset) when a target
      dataset lacks the column.
- [ ] SQL-backed sources use **WHERE push-down**; in-memory frames use **pandas** —
      chosen automatically per source type.
- [ ] Operator set `eq, ne, in, not_in, range, radius` is supported; `radius` delegates
      to the existing `spatial_filter()` and returns the existing `SpatialResult` shape.
- [ ] `apply_filters` is **ephemeral by default**; `persist=True` registers filtered datasets.
- [ ] `get_filter_values(name)` returns declared `values_source` values, else inferred
      cached `DISTINCT`/`unique()`.
- [ ] `get_filter_schema()` returns the catalog with per-filter dataset applicability.
- [ ] `suggest_filters()` proposes definitions from column introspection (opt-in, no side effects).
- [ ] Filtering is exposed both as programmatic API and `AbstractToolkit` tools, plus an
      HTTP/AgenTalk handler (`filters/schema`, `filters/{name}/values`, `POST filters`).
- [ ] No breaking changes to existing `DatasetManager` or FEAT-219 spatial public API.
- [ ] Documentation updated in `docs/`.

---

## 6. Codebase Contract

> **CRITICAL — Anti-Hallucination Anchor**
> Implementation agents MUST NOT reference imports, attributes, or methods not
> listed here without first verifying via `grep`/`read`.
> Base path for all `parrot/...` references:
> `packages/ai-parrot/src/parrot/...` (re-verified 2026-06-04).

### Verified Imports
```python
from parrot.tools.dataset_manager.tool import DatasetManager  # tool.py:500
from parrot.tools.dataset_manager.spatial.contracts import (   # spatial/contracts.py
    SpatialFilterSpec,          # :25
    DatasetSpatialProfile,      # :111
    SpatialResult,              # :266
    SpatialFeatureCollection,   # :316
)
from parrot.tools.dataset_manager.spatial.registry import (    # spatial/registry.py
    SPATIAL_PROFILE_REGISTRY,   # :29
    register_spatial_profile,   # :32
    get_spatial_profile,        # :54
    validate_profiles_exist,    # :79
)
from parrot.handlers.spatial_filter_handler import (           # handlers/spatial_filter_handler.py
    SpatialFilterHandler,
    SpatialFilterEnvelope,
)
```

### Existing Class Signatures
```python
# packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py
class DatasetManager(AbstractToolkit):                              # line 500
    self._datasets: Dict[str, DatasetEntry]                        # line 533

    @staticmethod
    def _apply_filter(df: pd.DataFrame,
                      filter_dict: Dict[str, Any]) -> pd.DataFrame: # line 829
        # scalar -> ==, list/tuple/set -> isin(); ANDed; ValueError if col missing
        # EXTEND HERE: ne / not_in / range (keep eq / in semantics)

    async def add_dataset(self, name: str, *, ...,
                          filter: Optional[Dict[str, Any]] = None,
                          permanent_filter: Optional[Dict[str, Any]] = None,
                          ...) -> str:                              # line 864

    @staticmethod
    def categorize_columns(df: pd.DataFrame) -> Dict[str, str]:     # line 633
        # -> boolean|integer|float|datetime|categorical|categorical_text|text

    async def materialize(self, name: str, force_refresh: bool = False,
                          **params) -> pd.DataFrame:                # line 3953
    def get_manifest(self) -> List[Dict[str, Any]]:                # line 4139
    async def spatial_filter(self, spec: "SpatialFilterSpec",
                             cap_per_dataset: int = 1000) -> "SpatialResult":  # line 4186

class DatasetEntry:                                                # line 123
    _df: Optional[pd.DataFrame]
    _column_types: Dict[str, str]
    _column_metadata: Dict[str, Dict[str, Any]]

# spatial/contracts.py
class SpatialFilterSpec(BaseModel):           # line 25
    point: Tuple[float, float]; radius: float
    unit: Literal["mi","km","m"]; datasets: List[str]
class DatasetSpatialProfile(BaseModel):       # line 111
    dataset: str
    lat_col: Optional[str]; lng_col: Optional[str]; geom_col: Optional[str]
    layer: str; property_cols: List[str]; geodesic: bool = True
class SpatialResult(BaseModel):               # line 266
    version: Literal[2]; layers: Dict[str, "SpatialLayerResult"]

# spatial/compiler.py
class SpatialCompiler:    # compile() I/O-free + async execute()
_ENGINE_DRIVERS = frozenset({"pg", "bigquery"})   # pandas bbox+haversine fallback otherwise
```

### Integration Points
| New Component | Connects To | Via | Verified At |
|---|---|---|---|
| `apply_filters` (pandas path) | `DatasetManager._apply_filter` | extended static method | `tool.py:829` |
| `apply_filters` (SQL path) | `permanent_filter` WHERE injection | reuse predicate building | `tool.py:1388`, `:948` |
| `apply_filters` (spatial path) | `DatasetManager.spatial_filter` | method call w/ `SpatialFilterSpec` | `tool.py:4186` |
| spatial kind bridge | `get_spatial_profile` / `validate_profiles_exist` | registry lookup | `spatial/registry.py:54,79` |
| `suggest_filters` | `categorize_columns` / `_column_types` | introspection | `tool.py:633`, `:123` |
| `get_filter_values` (materialized) | `materialize()` + cache | fetch + DISTINCT/unique | `tool.py:3953` |
| `DatasetFilterHandler` | `spatial_filter_handler.py` pattern | new aiohttp handler | `handlers/spatial_filter_handler.py:1` |

### Does NOT Exist (Anti-Hallucination)
- ~~`DatasetManager.define_filters` / `apply_filters` / `get_filter_schema` /
  `get_filter_values` / `suggest_filters`~~ — created by this feature.
- ~~`DatasetManager.get_distinct` / `get_unique`~~ — no distinct-value method exists today.
- ~~A "common fields" or filter-definition registry~~ — only the **spatial** profile
  registry (`SPATIAL_PROFILE_REGISTRY`) exists.
- ~~Generic `ne` / `range` / `not_in` operators in `_apply_filter`~~ — only `==` and `isin` today.
- ~~A non-spatial filter HTTP handler~~ — only `spatial_filter_handler.py` exists.
- ~~`parrot.tools.dataset_manager.filtering`~~ submodule — does not exist yet; created here.
- Ibis as a compile target — explicitly **NO-GO** (TASK-1437, noted in `spatial/compiler.py`);
  use hand-written SQL dialects.

---

## 7. Implementation Notes & Constraints

### Patterns to Follow
- Mirror the FEAT-219 spatial subsystem layout: I/O-free Pydantic `contracts.py`,
  `compile()` deterministic / `execute()` async split in `compiler.py`.
- Put all new non-spatial logic under `parrot/tools/dataset_manager/filtering/`;
  touch `tool.py` only for the public methods, `_filter_defs` init, and the
  `_apply_filter` operator extension.
- Async-first; Pydantic for all structured data; `self.logger`, no `print`.
- Reuse the manager's existing Redis/Parquet cache for value catalogs (TTL).
- `@tool` docstrings become LLM tool descriptions — write them clearly.
- Respect PBAC: a column dropped/forbidden by `_policy_guard` must not become
  filterable nor leak via `get_filter_values`.

### Known Risks / Gotchas
- **`tool.py` is a shared hotspot** also touched by in-flight FEAT-224
  (structured-config-homologation). Coordinate to avoid merge collisions; keep
  edits surgical and concentrated in the new submodule.
- **Empty result after filtering** is valid (empty DataFrame), not an error.
- **Op not allowed for a definition** → validate at `define_filters` time, not apply.

…(truncated)…
