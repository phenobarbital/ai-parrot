# TASK-588: PlanogramConfig & IdentifiedProduct Extensions

**Feature**: parrot-pipelines-inconsistency
**Spec**: `sdd/specs/parrot-pipelines-inconsistency.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-583
**Assigned-to**: unassigned

---

## Context

Extends existing Pydantic models to support the grid detection system. Adds the optional `detection_grid` field to `PlanogramConfig` and the `out_of_place` flag to `IdentifiedProduct`. Both are backward compatible additions. Implements Spec Modules 6 and 9.

The user explicitly decided that `out_of_place` should be a flag on `IdentifiedProduct` (not a list on `ComplianceResult`).

---

## Scope

- Add `detection_grid: Optional[DetectionGridConfig] = None` to `PlanogramConfig`
- Widen `reference_images` type to `Dict[str, Union[str, Path, List[str], List[Path], Image.Image]]` for multi-reference per product
- Add `out_of_place: bool = Field(default=False, description="True if product was detected in a cell where it was not expected")` to `IdentifiedProduct`
- Write unit tests for backward compatibility

**NOT in scope**: Database migration, changing how reference images are loaded from DB.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/models.py` | MODIFY | Add detection_grid field, widen reference_images type |
| `packages/ai-parrot/src/parrot/models/detections.py` | MODIFY | Add out_of_place field to IdentifiedProduct |
| `tests/pipelines/test_config_extensions.py` | CREATE | Backward compat tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# For models.py modification:
from parrot_pipelines.planogram.grid.models import DetectionGridConfig  # from TASK-583

# Existing imports in models.py (line 1-9):
from typing import Optional, Dict, List, Any, Union
from pathlib import Path
from PIL import Image
from pydantic import BaseModel, Field
from parrot.models.detections import PlanogramDescription, PlanogramDescriptionFactory
```

### Existing Signatures to Use
```python
# packages/ai-parrot-pipelines/src/parrot_pipelines/models.py:28
class PlanogramConfig(BaseModel):
    planogram_id: Optional[int] = None  # line 33
    config_name: str = "default_planogram_config"  # line 38
    planogram_type: str = "product_on_shelves"  # line 43
    planogram_config: Dict[str, Any]  # line 49
    roi_detection_prompt: str  # line 54
    object_identification_prompt: str  # line 59
    reference_images: Dict[str, Union[str, Path, Image.Image]] = {}  # line 64
    confidence_threshold: float = 0.25  # line 70
    detection_model: str = "yolo11l.pt"  # line 75
    endcap_geometry: EndcapGeometry  # line 80

# packages/ai-parrot/src/parrot/models/detections.py:71
class IdentifiedProduct(BaseModel):
    detection_id: int = None
    product_type: str
    product_model: Optional[str] = None
    brand: Optional[str] = None
    confidence: float
    # ... (many fields)
    extra: Dict[str, str] = {}
    # NOTE: out_of_place field does NOT exist yet — this task adds it
```

### Does NOT Exist
- ~~`PlanogramConfig.detection_grid`~~ — does not exist; this task adds it
- ~~`IdentifiedProduct.out_of_place`~~ — does not exist; this task adds it

---

## Implementation Notes

### Changes to models.py
```python
# Add import at top:
from parrot_pipelines.planogram.grid.models import DetectionGridConfig

# Add field to PlanogramConfig (after endcap_geometry, line ~82):
detection_grid: Optional[DetectionGridConfig] = Field(
    default=None,
    description="Detection grid configuration. None = current single-image behavior."
)

# Widen reference_images type:
reference_images: Dict[str, Union[str, Path, List[str], List[Path], Image.Image]] = Field(
    default_factory=dict,
    description="Reference images for object identification. Supports single image or list per product."
)
```

### Changes to detections.py
```python
# Add to IdentifiedProduct (after extra field):
out_of_place: bool = Field(
    default=False,
    description="True if product was detected in a cell where it was not expected"
)
```

### Key Constraints
- Both additions have defaults (`None` and `False`) so existing code/data is unaffected
- `reference_images` type widening is backward compatible — existing `Dict[str, str]` still valid
- No changes to `get_planogram_description()` method
- Import of `DetectionGridConfig` in models.py requires TASK-583 to be complete

---

## Acceptance Criteria

- [ ] `PlanogramConfig()` with existing fields (no `detection_grid`) still works
- [ ] `PlanogramConfig(detection_grid=DetectionGridConfig())` works
- [ ] `reference_images={"product": ["/path/1.jpg", "/path/2.jpg"]}` accepted
- [ ] `reference_images={"product": "/path/1.jpg"}` still works (backward compat)
- [ ] `IdentifiedProduct(product_type="product", confidence=0.9).out_of_place == False`
- [ ] `IdentifiedProduct(product_type="product", confidence=0.9, out_of_place=True).out_of_place == True`
- [ ] All existing tests still pass

---

## Test Specification

```python
import pytest
from parrot_pipelines.models import PlanogramConfig
from parrot_pipelines.planogram.grid.models import DetectionGridConfig, GridType
from parrot.models.detections import IdentifiedProduct


class TestPlanogramConfigExtension:
    def test_backward_compat_no_grid(self):
        """Existing config without detection_grid still works."""
        config = PlanogramConfig(
            planogram_config={"brand": "test", "shelves": []},
            roi_detection_prompt="test",
            object_identification_prompt="test",
        )
        assert config.detection_grid is None

    def test_with_detection_grid(self):
        config = PlanogramConfig(
            planogram_config={"brand": "test", "shelves": []},
            roi_detection_prompt="test",
            object_identification_prompt="test",
            detection_grid=DetectionGridConfig(grid_type=GridType.HORIZONTAL_BANDS),
        )
        assert config.detection_grid.grid_type == GridType.HORIZONTAL_BANDS

    def test_multi_reference_images(self):
        config = PlanogramConfig(
            planogram_config={"brand": "test", "shelves": []},
            roi_detection_prompt="test",
            object_identification_prompt="test",
            reference_images={"ES-C220": ["/path/1.jpg", "/path/2.jpg"]},
        )
        assert isinstance(config.reference_images["ES-C220"], list)


class TestIdentifiedProductOutOfPlace:
    def test_default_false(self):
        p = IdentifiedProduct(product_type="product", confidence=0.9)
        assert p.out_of_place is False

    def test_set_true(self):
        p = IdentifiedProduct(product_type="product", confidence=0.9, out_of_place=True)
        assert p.out_of_place is True
```

---

## Agent Instructions

When you pick up this task:

1. **Check** TASK-583 is completed (need `DetectionGridConfig` import)
2. **Read** `models.py` and `detections.py` to confirm current signatures
3. **Make minimal changes** — only add new fields, don't restructure
4. **Run existing tests** to verify no regression

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-04-05

Added `detection_grid: Optional[DetectionGridConfig] = Field(default=None, ...)` to
`PlanogramConfig` in `packages/ai-parrot-pipelines/src/parrot_pipelines/models.py`.
Widened `reference_images` type to `Dict[str, Union[str, Path, List[str], List[Path], Image.Image]]`
for multi-reference per product support.
Added `out_of_place: bool = Field(default=False, ...)` to `IdentifiedProduct` in
`packages/ai-parrot/src/parrot/models/detections.py` — this implements the user's
explicit decision (spec §8 open questions) to place the flag on `IdentifiedProduct`
rather than as a list on `ComplianceResult`.
Both changes are fully backward-compatible (default values).
Unit tests at `tests/pipelines/test_config_extensions.py` — all pass.

**Note**: the `reference_images` type widening introduced a regression in `_detect_legacy`
(nested lists passed to LLM). Fixed post-review in the same PR.
