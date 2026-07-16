---
type: Wiki Overview
title: 'TASK-1438: SpatialCompiler — engine push-down (pg + bigquery)'
id: doc:sdd-tasks-completed-task-1438-spatial-compiler-engine-pushdown-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Spec §3 Module 3. The engine push-down branch of `SpatialCompiler`: for
  `pg` and'
relates_to:
- concept: mod:parrot.tools.dataset_manager
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.spatial.compiler
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.spatial.contracts
  rel: mentions
---

# TASK-1438: SpatialCompiler — engine push-down (pg + bigquery)

**Feature**: FEAT-219 — Spatial Filtering for DatasetManager
**Spec**: `sdd/specs/spatial-dataset-filter.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1436, TASK-1437
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 3. The engine push-down branch of `SpatialCompiler`: for `pg` and
`bigquery` datasets, emit an `ST_DWITHIN` predicate + `ST_AsGeoJSON` projection so geometry
comes back as GeoJSON uniformly. `compile()` is pure (I/O-free, `syrupy`-snapshotable);
`execute()` does the I/O via AsyncDB. The implementation strategy (Ibis vs hand-written
dialect templates) is **dictated by TASK-1437's GO/NO-GO outcome** — read that decision
before starting.

---

## Scope

- Implement `SpatialCompiler.compile(spec, profile) -> CompiledQuery` for `driver in
  {"pg", "bigquery"}` — deterministic, no I/O, snapshot-testable.
- Implement `SpatialCompiler.execute(compiled, source) -> list[dict]` (GeoJSON features) via AsyncDB.
- Project geometry as GeoJSON in the SELECT (`ST_AsGeoJSON` / `ST_ASGEOJSON`).
- Implement geodesic **declare + verify**: profile declares `geodesic`; the compiler
  verifies against the actual column type (geography → geodesic; non-geography pg column →
  planar) and records the true path; warn on mismatch.
- If TASK-1437 == GO: use Ibis (one expression → both dialects) and add the `ibis-framework`
  extra to `pyproject.toml`. If NO-GO: ~2 hand-written SQL dialect templates.
- Write unit tests: `test_compile_pg_snapshot`, `test_compile_bigquery_snapshot`,
  `test_geodesic_verify` (spec §4).

**NOT in scope**: the Pandas/bbox fallback branch (TASK-1439), the `spatial_filter`
orchestration (TASK-1440), the HTTP handler (TASK-1441), the contracts (TASK-1436).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/dataset_manager/spatial/compiler.py` | CREATE | `SpatialCompiler` + `CompiledQuery` (engine branch) |
| `pyproject.toml` | MODIFY (conditional) | add `ibis-framework` extra ONLY if TASK-1437 == GO |
| `tests/unit/test_spatial_compiler_engine.py` | CREATE | snapshot + geodesic tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-06-03. Paths under `packages/ai-parrot/src/parrot/tools/dataset_manager/`.

### Verified Imports
```python
from parrot.tools.dataset_manager.table import TableSource  # table.py:113
from parrot.tools.dataset_manager.spatial.contracts import (  # created in TASK-1436
    SpatialFilterSpec, DatasetSpatialProfile,
)
```

### Existing Signatures to Use
```python
# parrot/tools/dataset_manager/table.py
class TableSource(DataSource):                          # l.113
    self.driver = _normalize_driver(driver)             # l.157  (route on this)
    def _get_connection_args(self) -> Tuple[Optional[Dict], Optional[str]]: ...  # l.311  → (credentials_dict, dsn)
    def _build_schema_query(self) -> Tuple[str, bool]: ...  # l.325  (column-type info source for geodesic verify)
```

### Does NOT Exist
- ~~`ibis` / `ibis-framework`~~ — present ONLY if TASK-1437 resolved GO and you add it here. Do not assume it is installed otherwise.
- ~~existing `ST_*` / spatial SQL helpers~~ — none; you are writing the first.
- ~~`DataSource.driver`~~ — `driver` is on `TableSource` only (table.py:157). Use `getattr(source, "driver", None)`.
- ~~`TableSource.materialize`~~ — `materialize` is on `DatasetEntry` (tool.py:240); spatial queries MUST NOT route through it (spec G4).

---

## Implementation Notes

### Pattern to Follow
- **Manager orchestrates, compiler translates** (spec §2). Keep `compile()` pure so it is
  `syrupy`-snapshotable without a DB connection.
- Build the connection from `_get_connection_args()` (table.py:311) — do not re-resolve
  credentials independently.
- Route on `getattr(source, "driver", None)`; this task handles only `pg` + `bigquery`.

### Key Constraints
- `compile()` returns a `CompiledQuery` (the SQL/Ibis expr + projection + metadata); NO I/O.
- `execute()` is async, uses AsyncDB, returns GeoJSON `dict` features.
- Geodesic: declared on profile, verified at compile time against the column type; the true
  path goes into `SpatialFeatureCollection.geodesic_paths` downstream. Warn (`self.logger`)
  on mismatch — never fatal.
- Do NOT route through `DatasetEntry.materialize` / Redis Parquet cache (spec G4).

### References in Codebase
- `parrot/tools/dataset_manager/table.py:311` — connection args.
- `parrot/tools/dataset_manager/table.py:325` — schema query (column types for geodesic).
- TASK-1437 Completion Note — GO/NO-GO + credentials mapping.

---

## Acceptance Criteria

- [ ] `compile()` for `pg` and `bigquery` emits `ST_DWITHIN` + `ST_AsGeoJSON`, is I/O-free.
- [ ] `compile()` output matches `syrupy` snapshots for both dialects.
- [ ] Geodesic declared+verified: geography → True; non-geography pg column → False + warning.
- [ ] `execute()` returns GeoJSON feature dicts via AsyncDB.
- [ ] `ibis-framework` added to `pyproject.toml` IFF TASK-1437 == GO (else not present).
- [ ] All tests pass: `pytest tests/unit/test_spatial_compiler_engine.py -v`
- [ ] No linting errors: `ruff check parrot/tools/dataset_manager/spatial/compiler.py`

---

## Test Specification

```python
# tests/unit/test_spatial_compiler_engine.py
import pytest
from parrot.tools.dataset_manager.spatial.compiler import SpatialCompiler
from parrot.tools.dataset_manager.spatial.contracts import SpatialFilterSpec, DatasetSpatialProfile


def test_compile_pg_snapshot(snapshot):
    c = SpatialCompiler()
    spec = SpatialFilterSpec(point=(40.7, -74.0), radius=5, unit="mi", datasets=["schools"])
    profile = DatasetSpatialProfile(dataset="schools", geom_col="geog", layer="schools",
                                    property_cols=["name"], description_template="{name}", geodesic=True)
    assert c.compile(spec, profile) == snapshot  # ST_DWITHIN + ST_AsGeoJSON, no DB

def test_compile_bigquery_snapshot(snapshot):
    ...

def test_geodesic_verify():
    """geography column → geodesic True; non-geography pg column → False + warning."""
    ...
```

---

## Agent Instructions

Standard SDD lifecycle. **Read TASK-1437's Completion Note first** — it determines whether
you use Ibis or hand-written dialect templates and whether to touch `pyproject.toml`.

---

## Completion Note

**Completed by**: Claude Sonnet (sdd-worker)
**Date**: 2026-06-03
**Notes**: Used hand-written SQL dialect templates (TASK-1437 NO-GO outcome). Two templates
per driver (geom_col path and lat/lng path): _PG_PUSHDOWN_GEOM_TEMPLATE,
_PG_PUSHDOWN_LATLON_TEMPLATE, _BQ_PUSHDOWN_GEOM_TEMPLATE, _BQ_PUSHDOWN_LATLON_TEMPLATE.
Geodesic declare+verify: pg geography → True, pg geometry → False + warning,
BigQuery GEOGRAPHY → always True. compile() is I/O-free (no AsyncDB import needed).
execute() uses AsyncDB via source._get_connection_args() following the TableSource._run_query
pattern. pyproject.toml NOT modified (ibis-framework not added per NO-GO decision).
**Deviations from spec**: none
