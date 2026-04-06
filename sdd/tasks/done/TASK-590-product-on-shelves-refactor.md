# TASK-590: ProductOnShelves Grid-Based Detection Refactor

**Feature**: parrot-pipelines-inconsistency
**Spec**: `sdd/specs/parrot-pipelines-inconsistency.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-585, TASK-587, TASK-588, TASK-589
**Assigned-to**: unassigned

---

## Context

This is the integration task that wires everything together. Refactors `ProductOnShelves.detect_objects()` to use the grid detection system when `detection_grid` is configured, while preserving the current single-image behavior as fallback. Implements Spec Module 8.

---

## Scope

- Override `get_grid_strategy()` in `ProductOnShelves` to return `HorizontalBands` when `self.config.detection_grid` is set with `grid_type=HORIZONTAL_BANDS`
- Refactor `detect_objects()` to:
  1. Check if `self.config.detection_grid` is set and not `NoGrid`
  2. If YES (grid mode): resolve strategy → compute cells → delegate to `GridDetector` → return merged results
  3. If NO (legacy mode): execute current single-image detection logic unchanged
- Ensure the `GridDetector` receives `self.pipeline.llm` and `self.pipeline.reference_images`
- Ensure coordinate offsets from ROI crop are still applied correctly (grid cells are relative to ROI, which is relative to full image)
- Write integration-style tests with mocked LLM

**NOT in scope**: Changing the compliance scoring logic, modifying the rendering stage, or implementing other planogram types.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py` | MODIFY | Refactor detect_objects(), override get_grid_strategy() |
| `tests/pipelines/test_product_on_shelves_grid.py` | CREATE | Tests for grid mode and legacy fallback |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Add to product_on_shelves.py:
from parrot_pipelines.planogram.grid.models import DetectionGridConfig, GridType
from parrot_pipelines.planogram.grid.horizontal_bands import HorizontalBands
from parrot_pipelines.planogram.grid.detector import GridDetector
from parrot_pipelines.planogram.grid.strategy import NoGrid
```

### Existing Signatures to Use
```python
# Current detect_objects flow to preserve as legacy path:
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py:102
async def detect_objects(self, img, roi, macro_objects):
    planogram_description = self.config.get_planogram_description()  # line 123
    # ROI crop with offset_x, offset_y (lines 125-132)
    offset_x, offset_y = 0, 0
    target_image = img
    if roi and hasattr(roi, "bbox"):
        w, h = img.size
        x1, y1, x2, y2 = roi.bbox.get_pixel_coordinates(width=w, height=h)
        target_image = img.crop((x1, y1, x2, y2))
        offset_x, offset_y = x1, y1
    # Build hints (lines 134-142)
    # Build prompt (lines 143-154)
    # Get refs (line 160): refs = list(self.pipeline.reference_images.values())
    # Single LLM call (lines 172-177)

# Pipeline attributes available via self.pipeline:
# self.pipeline.llm — LLM client instance (GoogleGenAIClient)
# self.pipeline.reference_images — Dict[str, Union[str, Path, Image]]
# self.pipeline.logger — logging.Logger

# self.config — PlanogramConfig instance
# self.config.detection_grid — Optional[DetectionGridConfig] (added by TASK-588)
# self.config.get_planogram_description() — returns PlanogramDescription
```

### Does NOT Exist
- ~~`ProductOnShelves._detect_with_grid()`~~ — does not exist; may be created as private method
- ~~`ProductOnShelves._detect_legacy()`~~ — does not exist; may be extracted from current code

---

## Implementation Notes

### Refactoring Strategy
```python
async def detect_objects(self, img, roi, macro_objects):
    planogram_description = self.config.get_planogram_description()

    # Determine crop offset
    offset_x, offset_y = 0, 0
    target_image = img
    if roi and hasattr(roi, "bbox"):
        w, h = img.size
        x1, y1, x2, y2 = roi.bbox.get_pixel_coordinates(width=w, height=h)
        target_image = img.crop((x1, y1, x2, y2))
        offset_x, offset_y = x1, y1

    # Grid detection path
    grid_config = self.config.detection_grid
    if grid_config and grid_config.grid_type != GridType.NO_GRID:
        products = await self._detect_with_grid(
            target_image, planogram_description, grid_config
        )
        # Apply ROI offset to grid results (grid coords are relative to ROI crop)
        for p in products:
            if p.detection_box:
                p.detection_box.x1 += offset_x
                p.detection_box.y1 += offset_y
                p.detection_box.x2 += offset_x
                p.detection_box.y2 += offset_y
        # Continue with shelf generation...
    else:
        # Legacy single-image path (existing code, untouched)
        products = await self._detect_legacy(target_image, planogram_description, offset_x, offset_y)

    # Rest of the method (shelf generation, etc.) remains unchanged
    ...

async def _detect_with_grid(self, target_image, planogram_description, grid_config):
    strategy = self.get_grid_strategy()
    roi_bbox = (0, 0, target_image.size[0], target_image.size[1])
    cells = strategy.compute_cells(roi_bbox, target_image.size, planogram_description, grid_config)

    detector = GridDetector(
        llm=self.pipeline.llm,
        reference_images=self.pipeline.reference_images,
        logger=self.logger,
    )
    return await detector.detect_cells(cells, target_image, grid_config)

def get_grid_strategy(self):
    grid_config = self.config.detection_grid
    if grid_config and grid_config.grid_type == GridType.HORIZONTAL_BANDS:
        return HorizontalBands()
    return NoGrid()
```

### Key Constraints
- **CRITICAL**: The legacy path must remain 100% unchanged — extract it into `_detect_legacy()` without modifying any logic
- Grid coords are relative to the cropped ROI image, NOT the full image. The ROI offset must be applied after grid merge.
- The rest of `detect_objects()` (shelf generation, fact-tag refinement, OCR corroboration) must work unchanged with the merged product list
- Log which detection path was taken: "Using grid detection (N cells)" vs "Using legacy single-image detection"

---

## Acceptance Criteria

- [ ] `detection_grid=None` → legacy path executes, identical behavior to before
- [ ] `detection_grid=DetectionGridConfig(grid_type=HORIZONTAL_BANDS)` → grid path executes with parallel per-cell detection
- [ ] ROI offset correctly applied to grid detection results
- [ ] Merged products fed to existing shelf generation / compliance unchanged
- [ ] All existing planogram compliance tests still pass (zero regression)
- [ ] New tests verify both paths

---

## Test Specification

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestProductOnShelvesGridRefactor:
    async def test_legacy_path_no_grid(self):
        """detection_grid=None uses legacy single-image detection."""
        # Verify only 1 LLM call made (not parallel cells)
        ...

    async def test_grid_path_horizontal_bands(self):
        """detection_grid with horizontal_bands triggers grid detection."""
        # Verify N LLM calls made in parallel
        ...

    async def test_roi_offset_applied_to_grid(self):
        """Grid detection results get ROI offset correction."""
        ...

    def test_get_grid_strategy_returns_horizontal_bands(self):
        """Override returns HorizontalBands for HORIZONTAL_BANDS config."""
        ...

    def test_get_grid_strategy_returns_no_grid_default(self):
        """No config returns NoGrid."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** for the full detection flow
2. **Check** all dependency tasks are completed
3. **Read** `product_on_shelves.py:102-222` carefully — the current `detect_objects()` method in full
4. **Extract** the current logic into `_detect_legacy()` WITHOUT modifying it
5. **Add** the grid path as a branch at the top of `detect_objects()`
6. **Run ALL existing planogram tests** to verify zero regression
7. This is the most critical task — take extra care with the refactor

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-04-06

Refactored `ProductOnShelves.detect_objects()` into three methods:
- `detect_objects()` — branch selector (grid path vs legacy path)
- `_detect_with_grid()` — resolves strategy, computes cells, instantiates `GridDetector`,
  returns merged products; applies ROI coordinate offset after merge
- `_detect_legacy()` — unchanged original logic extracted verbatim with a "Do NOT modify" notice

Overrode `get_grid_strategy()` to return `HorizontalBands` when `detection_grid.grid_type
== HORIZONTAL_BANDS`, `NoGrid` otherwise.

Grid path returns `(products, [])` — empty shelf_regions is correct since
`_generate_virtual_shelves` is called later by `PlanogramCompliance.run()` (plan.py:239).

**Post-review fixes applied**:
1. `get_grid_strategy()` return type corrected from `Any` to `AbstractGridStrategy`
2. `_detect_legacy` multi-reference image flattening added (regression fix for TASK-588
   type widening)
3. FIXME comment added to coordinate swap in `_detect_legacy` for tech-debt tracking

Unit tests at `tests/pipelines/test_product_on_shelves_grid.py` — all pass.
