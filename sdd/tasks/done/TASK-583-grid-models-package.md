# TASK-583: Detection Grid Models & Package Init

**Feature**: parrot-pipelines-inconsistency
**Spec**: `sdd/specs/parrot-pipelines-inconsistency.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is the foundational task for FEAT-084. It creates the Pydantic data models and package structure that all subsequent grid tasks depend on. Implements Spec Modules 1 and 10.

---

## Scope

- Create the `parrot_pipelines/planogram/grid/` package directory
- Implement `GridType` enum with values: `no_grid`, `horizontal_bands`, `matrix_grid`, `zone_grid`, `flat_grid`
- Implement `DetectionGridConfig` Pydantic model with fields: `grid_type`, `overlap_margin`, `max_image_size`, `rows`, `cols`, `flat_divisions`, `zones`
- Implement `GridCell` Pydantic model with fields: `cell_id`, `bbox` (Tuple[int,int,int,int]), `expected_products`, `reference_image_keys`, `level`
- Create `__init__.py` with `__all__` exports for `GridType`, `DetectionGridConfig`, `GridCell`
- Write unit tests for model construction, validation, and defaults

**NOT in scope**: Grid strategies, merger, detector, or modifications to existing files.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/grid/__init__.py` | CREATE | Package init with exports |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/grid/models.py` | CREATE | GridType, DetectionGridConfig, GridCell |
| `tests/pipelines/test_grid_models.py` | CREATE | Unit tests for models |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from enum import Enum  # stdlib
from typing import Dict, List, Optional, Tuple, Any, Union  # stdlib
from pydantic import BaseModel, Field  # pydantic (already a project dependency)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/models/detections.py:62
class ShelfRegion(BaseModel):
    shelf_id: str
    bbox: DetectionBox
    level: str  # "top", "middle", "bottom"
    objects: List[DetectionBox] = []
    is_background: bool = False

# packages/ai-parrot/src/parrot/models/detections.py:71
class IdentifiedProduct(BaseModel):
    detection_id: int = None
    product_type: str
    product_model: Optional[str] = None
    confidence: float  # 0.0-1.0
    detection_box: Optional[DetectionBox] = None
```

### Does NOT Exist
- ~~`parrot_pipelines.planogram.grid`~~ — package does not exist yet; this task creates it
- ~~`DetectionGridConfig`~~ — does not exist; this task creates it
- ~~`GridCell`~~ — does not exist; this task creates it
- ~~`GridType`~~ — does not exist; this task creates it

---

## Implementation Notes

### Pattern to Follow
```python
# Follow the existing Pydantic model pattern from models.py:11
class EndcapGeometry(BaseModel):
    aspect_ratio: float = Field(default=1.35, description="...")
    # ... optional fields with defaults
```

### Key Constraints
- All fields must have descriptive `Field(description=...)` annotations
- `GridType` enum must use `str, Enum` base for JSON serialization
- `DetectionGridConfig` defaults must produce NoGrid behavior (backward compat)
- `bbox` in `GridCell` is `Tuple[int, int, int, int]` = (x1, y1, x2, y2) absolute pixels
- `overlap_margin` must be constrained: `ge=0.0, le=0.20`

---

## Acceptance Criteria

- [ ] `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/grid/` package exists
- [ ] `from parrot_pipelines.planogram.grid import GridType, DetectionGridConfig, GridCell` works
- [ ] `DetectionGridConfig()` defaults to `grid_type=GridType.NO_GRID, overlap_margin=0.05`
- [ ] `GridCell` validates bbox as 4-tuple of ints
- [ ] All unit tests pass
- [ ] No linting errors

---

## Test Specification

```python
import pytest
from parrot_pipelines.planogram.grid.models import GridType, DetectionGridConfig, GridCell


class TestGridType:
    def test_enum_values(self):
        assert GridType.NO_GRID == "no_grid"
        assert GridType.HORIZONTAL_BANDS == "horizontal_bands"
        assert GridType.MATRIX_GRID == "matrix_grid"

    def test_json_serializable(self):
        assert GridType.NO_GRID.value == "no_grid"


class TestDetectionGridConfig:
    def test_defaults(self):
        config = DetectionGridConfig()
        assert config.grid_type == GridType.NO_GRID
        assert config.overlap_margin == 0.05
        assert config.max_image_size == 1024
        assert config.rows is None
        assert config.cols is None

    def test_overlap_margin_bounds(self):
        with pytest.raises(Exception):
            DetectionGridConfig(overlap_margin=0.5)  # exceeds 0.20


class TestGridCell:
    def test_construction(self):
        cell = GridCell(
            cell_id="shelf_top",
            bbox=(100, 50, 900, 250),
            expected_products=["ES-C220", "ES-580W"],
            reference_image_keys=["ES-C220", "ES-580W"],
            level="top",
        )
        assert cell.cell_id == "shelf_top"
        assert cell.bbox == (100, 50, 900, 250)

    def test_defaults(self):
        cell = GridCell(cell_id="test", bbox=(0, 0, 100, 100))
        assert cell.expected_products == []
        assert cell.reference_image_keys == []
        assert cell.level is None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/parrot-pipelines-inconsistency.spec.md` for full context
2. **Check dependencies** — this task has no dependencies
3. **Verify the Codebase Contract** — confirm imports and patterns still match
4. **Create the grid package** directory and files
5. **Implement** models following the scope above
6. **Run tests** to verify
7. **Update status** in `tasks/.index.json` → `"in-progress"` / `"done"`
8. **Move this file** to `tasks/completed/`

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-04-05

Created `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/grid/` as a new package.
Implemented `GridType` (str enum), `DetectionGridConfig` (Pydantic, defaults to `NO_GRID`/`0.05`/`1024`),
and `GridCell` (Pydantic, `bbox` as 4-tuple of ints). All fields have `Field(description=...)`.
Package `__init__.py` exports all three symbols in `__all__`.
Unit tests at `tests/pipelines/test_grid_models.py` cover enum values, defaults, boundary
validation (`overlap_margin` ≤ 0.20), and bbox tuple constraints — all pass.

**No deviations from task scope.**
