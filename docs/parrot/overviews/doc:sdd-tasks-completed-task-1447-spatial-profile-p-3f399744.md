---
type: Wiki Overview
title: 'TASK-1447: Presentation hints on DatasetSpatialProfile'
id: doc:sdd-tasks-completed-task-1447-spatial-profile-presentation-hints-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §3 Module 5 (G5). The renderer (TASK-1449) derives each layer's presentation
---

# TASK-1447: Presentation hints on DatasetSpatialProfile

**Feature**: FEAT-221 — Structured Map Output Mode (`STRUCTURED_MAP`)
**Spec**: `sdd/specs/structured-map-output.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1446
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5 (G5). The renderer (TASK-1449) derives each layer's presentation
metadata deterministically from the dataset's `DatasetSpatialProfile`. Today the
profile only carries `property_cols` + `description_template`. This task adds the
OPTIONAL presentation hints the renderer needs — all backward-compatible
(defaults preserve current FEAT-219 behaviour).

---

## Scope

- In `packages/ai-parrot/src/parrot/tools/dataset_manager/spatial/contracts.py`,
  extend `DatasetSpatialProfile` with OPTIONAL fields:
  - `label_col: Optional[str] = None` — property key for the marker label.
  - `tooltip_template: Optional[str] = None` — per-layer tooltip template
    (distinct from `description_template`; falls back to `description_template`
    when unset). Compact, applied client-side over `feature.properties` (G8).
  - `column_titles: Dict[str, str] = Field(default_factory=dict)` — optional
    human titles per `property_cols` entry (renderer default = column name).
  - `column_formats: Dict[str, str] = Field(default_factory=dict)` — optional
    format hints per column (`currency|percent|...`).
  - `default_data_shape: Literal["geojson","rows"] = "geojson"` — per-dataset
    default for `MapLayer.data_shape` (G6).
- Update any registry seed/sample profiles so the new fields are demonstrated
  (without changing existing behaviour).

**NOT in scope**: the renderer itself (TASK-1449), `SpatialResult` (TASK-1446 —
already done as a dependency), config models (TASK-1445).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `.../tools/dataset_manager/spatial/contracts.py` | MODIFY | add optional presentation fields to `DatasetSpatialProfile` |
| `.../tools/dataset_manager/spatial/registry.py` | MODIFY | (if profiles are seeded here) demonstrate new fields |
| `packages/ai-parrot/tests/.../test_profile_presentation_hints.py` | CREATE | unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from typing import Dict, List, Literal, Optional, Tuple  # contracts.py:15
from pydantic import BaseModel, Field, field_validator, model_validator  # contracts.py:17
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/tools/dataset_manager/spatial/contracts.py
class DatasetSpatialProfile(BaseModel):              # line 106
    dataset: str                                     # line 127
    lat_col: Optional[str] = None                    # line 128
    lng_col: Optional[str] = None                    # line 129
    geom_col: Optional[str] = None                   # line 130
    layer: str                                       # line 134
    property_cols: List[str] = Field(default_factory=list)  # line 135
    description_template: str = Field(default="")    # line 139
    geodesic: bool = Field(default=True)             # line 143
    @model_validator(mode="after")
    def _validate_geometry_source(self): ...         # line 148  (must keep working)
```

### Does NOT Exist
- ~~`DatasetSpatialProfile.label_col` / `.tooltip_template` / `.column_titles` / `.column_formats` / `.default_data_shape`~~ — this task adds them.
- ~~a separate `PresentationProfile` model~~ — extend `DatasetSpatialProfile` in place; do not create a parallel model.

### Dependency note
- `SpatialLayerResult` / `SpatialResult` (TASK-1446) must be present in
  `contracts.py` before starting — confirm TASK-1446 is in `sdd/tasks/completed/`.

---

## Implementation Notes

### Key Constraints
- ALL new fields OPTIONAL with safe defaults — existing registered profiles and
  the FEAT-219 deterministic path must keep working unchanged.
- Keep the existing `_validate_geometry_source` validator intact.
- `tooltip_template` and `column_*` use the SAME format vocabulary as `MapColumn`
  (TASK-1445): `currency|percent|email|uri|enum|id|code`.

### References in Codebase
- `.../spatial/contracts.py:106` — `DatasetSpatialProfile`.
- `packages/ai-parrot/src/parrot/models/outputs.py:472` — `TableColumn.format` vocabulary.

---

## Acceptance Criteria

- [ ] `DatasetSpatialProfile` accepts the new optional fields and still validates geometry source.
- [ ] Profiles WITHOUT the new fields construct exactly as before (defaults applied).
- [ ] `pytest packages/ai-parrot/tests/ -k profile_presentation -v` passes.
- [ ] `ruff check` clean.

---

## Test Specification

```python
def test_optional_presentation_fields_default():
    p = DatasetSpatialProfile(dataset="schools", lat_col="lat", lng_col="lng", layer="schools")
    assert p.label_col is None
    assert p.tooltip_template is None
    assert p.default_data_shape == "geojson"


def test_presentation_fields_set():
    p = DatasetSpatialProfile(
        dataset="schools", lat_col="lat", lng_col="lng", layer="schools",
        property_cols=["name", "enrollment"],
        label_col="name", tooltip_template="{name} ({enrollment})",
        column_titles={"enrollment": "Students"}, column_formats={"enrollment": "id"},
        default_data_shape="rows",
    )
    assert p.column_titles["enrollment"] == "Students"
    assert p.default_data_shape == "rows"
```

---

## Agent Instructions

1. Read spec §3 Module 5.
2. Confirm TASK-1446 is completed (contracts.py has `SpatialResult`).
3. Update index → `in-progress`.
4. Implement; run tests; `ruff check`.
5. Move to `sdd/tasks/completed/`, update index → `done`, fill the note.

---

## Completion Note

**Completed by**: Claude Sonnet 4.6 (sdd-worker)
**Date**: 2026-06-04
**Notes**: Extended `DatasetSpatialProfile` with 5 optional presentation hint fields:
`label_col`, `tooltip_template`, `column_titles`, `column_formats`, `default_data_shape`.
All have safe defaults; existing profiles and FEAT-219 deterministic path unaffected.
The existing `_validate_geometry_source` validator was preserved intact. registry.py
had no seed profiles to update. 12 tests pass.
**Deviations from spec**: none
