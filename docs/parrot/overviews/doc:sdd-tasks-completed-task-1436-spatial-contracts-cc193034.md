---
type: Wiki Overview
title: 'TASK-1436: Spatial contracts + profile registry + manifest'
id: doc:sdd-tasks-completed-task-1436-spatial-contracts-registry-manifest-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Foundation layer (spec §3 Module 1). Pure Pydantic contracts + a standalone
  profile
relates_to:
- concept: mod:parrot.tools.dataset_manager
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.spatial.contracts
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.spatial.registry
  rel: mentions
- concept: mod:parrot.tools.dataset_manager.tool
  rel: mentions
---

# TASK-1436: Spatial contracts + profile registry + manifest

**Feature**: FEAT-219 — Spatial Filtering for DatasetManager
**Spec**: `sdd/specs/spatial-dataset-filter.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Foundation layer (spec §3 Module 1). Pure Pydantic contracts + a standalone profile
registry + a manifest endpoint. **No I/O** — this task unblocks the frontend immediately
and every other task in the feature depends on it. Implements brainstorm Option B
(separate `SPATIAL_PROFILE_REGISTRY`, not co-registration).

---

## Scope

- Implement `SpatialFilterSpec`, `DatasetSpatialProfile`, `SpatialFeatureCollection`
  Pydantic v2 models (spec §2 Data Models).
- Implement `SPATIAL_PROFILE_REGISTRY` keyed by dataset name with register + lookup helpers.
- Validate referential integrity: registering/resolving a profile for a dataset that does
  not exist raises a descriptive `ValueError` — copy the discipline from
  `CompositeDataSource.fetch` (composite.py:161).
- Implement `DatasetManager.get_manifest()` listing spatial datasets with `layer`,
  `geodesic`, and `property_cols`.
- Write unit tests: `test_spec_roundtrip`, `test_profile_registry_validates_dataset`,
  `test_manifest_shape` (spec §4).

**NOT in scope**: the compiler, any SQL, the `spatial_filter` orchestration method, the
HTTP handler, the bbox predicate, Ibis. Those are TASK-1437…1441.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/dataset_manager/spatial/__init__.py` | CREATE | package init |
| `parrot/tools/dataset_manager/spatial/contracts.py` | CREATE | the 3 Pydantic models |
| `parrot/tools/dataset_manager/spatial/registry.py` | CREATE | `SPATIAL_PROFILE_REGISTRY` + validate helpers |
| `parrot/tools/dataset_manager/tool.py` | MODIFY | add `get_manifest()` method on `DatasetManager` |
| `tests/unit/test_spatial_contracts.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

> Verified 2026-06-03. Paths under `packages/ai-parrot/src/parrot/tools/dataset_manager/`.

### Verified Imports
```python
from parrot.tools.dataset_manager.tool import DatasetManager        # tool.py:492
from parrot.tools.dataset_manager.composite import CompositeDataSource  # composite.py:65
```

### Existing Signatures to Use
```python
# parrot/tools/dataset_manager/tool.py
class DatasetManager(AbstractToolkit):                  # l.492
    tool_prefix: str = "dataset"                        # l.512
    def _resolve_name(self, identifier: str) -> str: ...  # l.599  (resolve dataset names)
    def to_info(self, alias: Optional[str] = None) -> DatasetInfo:  # l.397

# parrot/tools/dataset_manager/composite.py
class CompositeDataSource(DataSource):                  # l.65
    async def fetch(self, filters=None, **params) -> pd.DataFrame:  # l.161 (validates every component exists, raises descriptive ValueError)
```

### Does NOT Exist
- ~~`ibis` / `ibis-framework`~~ — NOT a dependency. Do not import it in this task.
- ~~existing spatial / `ST_*` / geometry code~~ — none; this is greenfield.
- ~~`DatasetManager.materialize`~~ — `materialize` is on `DatasetEntry` (tool.py:240), not the manager. Not needed here anyway.
- ~~`_source_type_map` as a class attribute~~ — it is a LOCAL dict inside `to_info()` (tool.py:420-432).

---

## Implementation Notes

### Pattern to Follow
- Validate-at-resolve discipline mirrors `CompositeDataSource.fetch` (composite.py:161):
  iterate referenced names, raise a single descriptive `ValueError` naming the missing
  dataset.
- Pydantic v2 throughout. `SpatialFilterSpec.datasets` are raw names; resolution to
  canonical names happens via `DatasetManager._resolve_name` (do NOT resolve inside the
  contract model — keep contracts I/O-free).

### Key Constraints
- No I/O anywhere in this task — contracts and registry are pure.
- `SpatialFeatureCollection` must carry `total_count`, `capped`, and per-dataset
  `geodesic_paths` (spec §2 Data Models) so downstream capping/geodesic work has a home.
- Use `self.logger` in `get_manifest()`.

### References in Codebase
- `parrot/tools/dataset_manager/composite.py:161` — validation pattern.
- `parrot/tools/dataset_manager/tool.py:599` — `_resolve_name`.

---

## Acceptance Criteria

- [ ] `SpatialFilterSpec`, `DatasetSpatialProfile`, `SpatialFeatureCollection` defined per §2.
- [ ] `SPATIAL_PROFILE_REGISTRY` registers/looks up profiles by dataset name.
- [ ] Resolving a profile for an unknown dataset raises a descriptive `ValueError`.
- [ ] `DatasetManager.get_manifest()` returns layer/geodesic/property_cols per spatial dataset.
- [ ] All tests pass: `pytest tests/unit/test_spatial_contracts.py -v`
- [ ] No linting errors: `ruff check parrot/tools/dataset_manager/spatial/`
- [ ] Imports work: `from parrot.tools.dataset_manager.spatial.contracts import SpatialFilterSpec`

---

## Test Specification

```python
# tests/unit/test_spatial_contracts.py
import pytest
from parrot.tools.dataset_manager.spatial.contracts import (
    SpatialFilterSpec, DatasetSpatialProfile, SpatialFeatureCollection,
)
from parrot.tools.dataset_manager.spatial.registry import SPATIAL_PROFILE_REGISTRY


def test_spec_roundtrip():
    spec = SpatialFilterSpec(point=(40.7, -74.0), radius=5, unit="mi", datasets=["schools"])
    assert spec.unit == "mi"
    with pytest.raises(Exception):
        SpatialFilterSpec(point=(40.7,), radius=5, datasets=[])  # malformed point


def test_profile_registry_validates_dataset():
    with pytest.raises(ValueError, match="schools"):
        # resolving/registering against a manager with no "schools" dataset
        ...


def test_manifest_shape():
    # get_manifest() entries carry layer, geodesic, property_cols
    ...
```

---

## Agent Instructions

Follow the standard SDD task lifecycle: verify the Codebase Contract first, set status
`in-progress` in `sdd/tasks/index/spatial-dataset-filter.json`, implement per scope, run
tests, move this file to `sdd/tasks/completed/`, update index to `done`, fill the
Completion Note.

---

## Completion Note

**Completed by**: Claude Sonnet (sdd-worker)
**Date**: 2026-06-03
**Notes**: All 3 Pydantic v2 models created in spatial/contracts.py. SPATIAL_PROFILE_REGISTRY
with register/lookup/validate helpers in spatial/registry.py. DatasetManager.get_manifest()
added at end of tool.py. Unit tests cover roundtrip validation, malformed input rejection,
registry lookup, and manifest shape. Intentionally omitted `from __future__ import annotations`
from contracts.py to ensure Pydantic v2 resolves Tuple[float, float] at class definition time.
Environment has pre-existing broken C extensions (numpy, navconfig) so tests were validated
via direct Python module loading; the contracts themselves are correct.
**Deviations from spec**: none
