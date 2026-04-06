# TASK-586: Cell Result Merger

**Feature**: parrot-pipelines-inconsistency
**Spec**: `sdd/specs/parrot-pipelines-inconsistency.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-583
**Assigned-to**: unassigned

---

## Context

After parallel per-cell detection, results from multiple grid cells must be merged into a unified product list. This task implements coordinate offset correction, IoU-based boundary deduplication, and out-of-place tagging. Implements Spec Module 4.

---

## Scope

- Implement `CellResultMerger` class with:
  - `merge(cell_results: List[Tuple[GridCell, List[IdentifiedProduct]]], iou_threshold: float = 0.5) -> List[IdentifiedProduct]`
  - Per-cell coordinate offset correction: convert cell-relative detection_box coords to absolute image coords using cell's bbox origin
  - IoU-based boundary deduplication: when the same object appears in overlapping cells, keep the higher-confidence detection
  - Out-of-place tagging: products whose `product_model` is not in the cell's `expected_products` get `out_of_place=True` on `IdentifiedProduct`
- Implement `_compute_iou(box_a, box_b) -> float` helper for IoU calculation between two `DetectionBox` instances
- Write unit tests

**NOT in scope**: Modifying `IdentifiedProduct` model (that's TASK-588). This task works with the field assuming TASK-588 adds it. If TASK-588 hasn't run yet, the merger sets `extra["out_of_place"] = "true"` as fallback.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/grid/merger.py` | CREATE | CellResultMerger + IoU helper |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/grid/__init__.py` | MODIFY | Add export |
| `tests/pipelines/test_cell_merger.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_pipelines.planogram.grid.models import GridCell  # from TASK-583
from parrot.models.detections import IdentifiedProduct, DetectionBox  # verified: detections.py:71, :30
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/models/detections.py:71
class IdentifiedProduct(BaseModel):
    detection_id: int = None
    product_type: str
    product_model: Optional[str] = None
    confidence: float  # 0.0-1.0
    detection_box: Optional[DetectionBox] = None
    extra: Dict[str, str] = {}  # fallback for out_of_place flag

# packages/ai-parrot/src/parrot/models/detections.py (DetectionBox):
class DetectionBox(BaseModel):
    x1: float
    y1: float
    x2: float
    y2: float
    # has get_pixel_coordinates(width, height) method
```

### Does NOT Exist
- ~~`CellResultMerger`~~ — does not exist; this task creates it
- ~~`IdentifiedProduct.out_of_place`~~ — does not exist YET (TASK-588 adds it); use `extra` dict as fallback
- ~~`_compute_iou`~~ — does not exist; this task creates it

---

## Implementation Notes

### Pattern to Follow
```python
class CellResultMerger:
    def merge(
        self,
        cell_results: List[Tuple[GridCell, List[IdentifiedProduct]]],
        iou_threshold: float = 0.5,
    ) -> List[IdentifiedProduct]:
        all_products = []
        for cell, products in cell_results:
            for product in products:
                # 1. Offset correction
                self._apply_offset(product, cell.bbox)
                # 2. Out-of-place tagging
                if product.product_model and product.product_model not in cell.expected_products:
                    # Use extra dict as fallback if out_of_place field doesn't exist
                    if hasattr(product, 'out_of_place'):
                        product.out_of_place = True
                    else:
                        product.extra["out_of_place"] = "true"
                all_products.append(product)
        # 3. Deduplicate boundary objects
        return self._deduplicate(all_products, iou_threshold)
```

### Key Constraints
- Offset correction: `detection_box.x1 += cell.bbox[0]`, `detection_box.y1 += cell.bbox[1]`, etc.
- IoU formula: `intersection_area / union_area`
- Deduplication: when two detections overlap above `iou_threshold`, keep the one with higher `confidence`
- Must handle products with `detection_box=None` gracefully (skip dedup for those)
- The `out_of_place` flag is informational only — it doesn't affect compliance scoring

---

## Acceptance Criteria

- [ ] Coordinate offsets correctly applied from cell bbox origin
- [ ] IoU calculation is correct for overlapping DetectionBox pairs
- [ ] Boundary objects deduplicated (higher confidence wins)
- [ ] Products not in cell's expected_products tagged as out_of_place
- [ ] Products with `detection_box=None` pass through without error
- [ ] All tests pass

---

## Test Specification

```python
import pytest
from parrot_pipelines.planogram.grid.merger import CellResultMerger
from parrot_pipelines.planogram.grid.models import GridCell


class TestCellResultMerger:
    def test_offset_correction(self):
        """Cell-relative coords become absolute after merge."""
        ...

    def test_iou_deduplication(self):
        """Overlapping detections from adjacent cells merged, higher confidence kept."""
        ...

    def test_no_dedup_below_threshold(self):
        """Non-overlapping detections from different cells both kept."""
        ...

    def test_out_of_place_tagging(self):
        """Product not in cell's expected_products gets out_of_place flag."""
        ...

    def test_none_detection_box_handled(self):
        """Products without detection_box pass through without error."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** for context on boundary deduplication rationale
2. **Check** TASK-583 is completed
3. **Read** `parrot/models/detections.py` to confirm `DetectionBox` and `IdentifiedProduct` signatures
4. **Implement** following scope
5. **Run tests**

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-04-05

Created `grid/merger.py` with `CellResultMerger` and `_compute_iou()` helper.
`merge()` applies per-cell coordinate offsets, tags out-of-place products (uses
`IdentifiedProduct.out_of_place` attribute; `extra["out_of_place"]` fallback retained for
forward-compat but is currently dead code since TASK-588 always adds the field),
then deduplicates overlapping detections by sorting descending by confidence and
keeping the highest-confidence detection when IoU ≥ threshold.
Products with `detection_box=None` are passed through without error.

**Post-review fix**: removed module-level `logger`; `CellResultMerger` now uses `self.logger`
per AI-Parrot convention (applied during code review of FEAT-084).
