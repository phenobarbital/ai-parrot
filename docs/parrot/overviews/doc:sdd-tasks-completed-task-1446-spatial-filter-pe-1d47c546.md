---
type: Wiki Overview
title: 'TASK-1446: FEAT-219 per-dataset spatial result refactor'
id: doc:sdd-tasks-completed-task-1446-spatial-filter-per-dataset-result-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §2 Data Models + §3 Module 2 (G4). Today `DatasetManager.spatial_filter`
relates_to:
- concept: mod:parrot.tools.dataset_manager.spatial
  rel: mentions
---

# TASK-1446: FEAT-219 per-dataset spatial result refactor

**Feature**: FEAT-221 — Structured Map Output Mode (`STRUCTURED_MAP`)
**Spec**: `sdd/specs/structured-map-output.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Spec §2 Data Models + §3 Module 2 (G4). Today `DatasetManager.spatial_filter`
merges all datasets into ONE `SpatialFeatureCollection` with a per-feature
`properties.source` discriminator. This task changes it to return results
**grouped per dataset** (`SpatialResult`) so the renderer (TASK-1449) gets clean
layers and per-layer capping/`geodesic`. A back-compat helper preserves the legacy
merged shape for the transport handler (TASK-1448).

---

## Scope

- In `packages/ai-parrot/src/parrot/tools/dataset_manager/spatial/contracts.py`:
  - Add `SpatialLayerResult` — `layer: str`, `features: List[Dict]`,
    `total_count: int = 0`, `capped: bool = False`, `geodesic: bool = True`.
  - Add `SpatialResult` — `version: Literal[2] = 2`,
    `layers: Dict[str, SpatialLayerResult]` (keyed by resolved dataset name),
    plus a method `as_feature_collection() -> SpatialFeatureCollection` that
    reproduces the legacy merged shape (concatenate features, sum `total_count`,
    OR the `capped` flags, build `geodesic_paths` from each layer's `geodesic`).
  - Export both from `spatial/__init__.py`.
- In `packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py`:
  - Change `spatial_filter` to build and return a `SpatialResult` (one
    `SpatialLayerResult` per resolved dataset, using each profile's `layer`).
  - Keep the existing push-down / Pandas-fallback execution logic; only change
    the **assembly/merge** step (spec §2 Component Diagram).

**NOT in scope**: handler changes (TASK-1448), profile presentation-hint fields
(TASK-1447), renderer (TASK-1449). Do NOT change `SpatialFilterSpec`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.../tools/dataset_manager/spatial/contracts.py` | MODIFY | add `SpatialLayerResult`, `SpatialResult` + `as_feature_collection()` |
| `.../tools/dataset_manager/spatial/__init__.py` | MODIFY | export the new models |
| `.../tools/dataset_manager/tool.py` | MODIFY | `spatial_filter` returns `SpatialResult` |
| `packages/ai-parrot/tests/.../test_spatial_per_dataset_result.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from typing import Dict, List, Literal, Optional, Tuple  # contracts.py:15
from pydantic import BaseModel, Field, field_validator, model_validator  # contracts.py:17
# spatial/__init__.py currently exports (line 8):
from .contracts import SpatialFilterSpec, DatasetSpatialProfile, SpatialFeatureCollection
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/dataset_manager/spatial/contracts.py
class SpatialFeatureCollection(BaseModel):          # line 168
    type: Literal["FeatureCollection"] = Field(default="FeatureCollection")  # line 187
    features: List[Dict] = Field(default_factory=list)  # line 191
    total_count: int = Field(default=0, ge=0)        # line 195
    capped: bool = Field(default=False)              # line 200
    geodesic_paths: Dict[str, bool] = Field(default_factory=dict)  # line 204

class DatasetSpatialProfile(BaseModel):              # line 106
    dataset: str                                     # line 127
    layer: str                                       # line 134  GeoJSON source discriminator (key for grouping)
    property_cols: List[str]                         # line 135
    description_template: str = ""                   # line 139
    geodesic: bool = True                            # line 143

# packages/ai-parrot/src/parrot/tools/dataset_manager/tool.py
async def spatial_filter(self, spec: "SpatialFilterSpec",
                         cap_per_dataset: int = 1000) -> "SpatialFeatureCollection":  # line 4186
    # imports inside the method (line 4222-4225):
    #   from .spatial.contracts import SpatialFeatureCollection
    #   from .spatial.registry import get_spatial_profile, validate_profiles_exist
    #   from .spatial.compiler import SpatialCompiler
    # resolves names via self._resolve_name; profiles via get_spatial_profile(name)
```

### Does NOT Exist
- ~~`SpatialResult` / `SpatialLayerResult`~~ — this task adds them.
- ~~`SpatialFeatureCollection.layers`~~ — the current collection is flat (features only).
- ~~per-dataset `total_count`~~ — today `total_count` is a single collection-level int.

---

## Implementation Notes

### Pattern to Follow
- Keep `from __future__ import annotations` ABSENT in `contracts.py` (the file
  header explains Pydantic v2 needs `Tuple` resolvable at class-def time).
- Group by the resolved dataset name; use `profile.layer` as the
  `SpatialLayerResult.layer` value (the GeoJSON `source` discriminator).
- `as_feature_collection()` must be loss-tolerant and deterministic so
  `test_spatial_result_back_compat_collection` and the handler keep working.

### Key Constraints
- Async throughout; do not pull full tables into memory (FEAT-219 invariant).
- Preserve per-dataset hard cap + true `total_count` (G10).
- This is a BREAKING return-type change — TASK-1448 adapts the handler. Within
  this task, ensure `as_feature_collection()` exactly reproduces the prior shape.

### References in Codebase
- `.../dataset_manager/tool.py:4186` — current `spatial_filter` merge logic.
- `.../spatial/contracts.py:168` — `SpatialFeatureCollection`.
- FEAT-219 spec `sdd/specs/spatial-dataset-filter.spec.md` for execution semantics.

---

## Acceptance Criteria

- [ ] `from parrot.tools.dataset_manager.spatial import SpatialResult, SpatialLayerResult` works.
- [ ] `spatial_filter(...)` returns a `SpatialResult` keyed by dataset with per-layer `total_count`/`capped`/`geodesic`.
- [ ] `SpatialResult.as_feature_collection()` reproduces the legacy merged `SpatialFeatureCollection` (features concatenated, counts summed, `geodesic_paths` populated).
- [ ] `pytest packages/ai-parrot/tests/ -k spatial_per_dataset -v` passes.
- [ ] `ruff check` clean on edited files.

---

## Test Specification

```python
def test_spatial_result_keyed_per_dataset(two_dataset_spatial_result):
    res = two_dataset_spatial_result
    assert set(res.layers.keys()) == {"schools", "malls"}
    assert res.layers["schools"].total_count >= len(res.layers["schools"].features)


def test_as_feature_collection_back_compat(two_dataset_spatial_result):
    fc = two_dataset_spatial_result.as_feature_collection()
    assert fc.type == "FeatureCollection"
    assert len(fc.features) == sum(len(l.features) for l in two_dataset_spatial_result.layers.values())
    assert set(fc.geodesic_paths.keys()) == set(two_dataset_spatial_result.layers.keys())
```

---

## Agent Instructions

1. Read spec §2 (Data Models, Component Diagram) and §3 Module 2.
2. Re-verify the `spatial_filter` merge block (tool.py:4186+) before editing.
3. Update index → `in-progress`.
4. Implement; run tests; `ruff check`.
5. Move to `sdd/tasks/completed/`, update index → `done`, fill the note.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-06-04
**Notes**: Added `SpatialLayerResult` and `SpatialResult` (with `as_feature_collection()`)
to `contracts.py`. Updated `spatial/__init__.py` to export both. Changed `spatial_filter`
return type from `SpatialFeatureCollection` to `SpatialResult`, grouping results per
dataset (one `SpatialLayerResult` per dataset). The `as_feature_collection()` shim
preserves full backward compat. Removed the now-unused `SpatialFeatureCollection` import
from the module-level runtime import in `tool.py`. All 15 tests pass.
**Deviations from spec**: none
