# TASK-585: HorizontalBands Grid Strategy

**Feature**: parrot-pipelines-inconsistency
**Spec**: `sdd/specs/parrot-pipelines-inconsistency.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-584
**Assigned-to**: unassigned

---

## Context

Implements the primary grid strategy for `product_on_shelves` planograms. Splits the ROI into N horizontal bands based on `height_ratio` from the planogram shelf config, mapping expected products per band. This is the core strategy that directly addresses the LLM attention dilution problem. Implements Spec Module 3.

---

## Scope

- Implement `HorizontalBands(AbstractGridStrategy)` in its own file
- `compute_cells()` logic:
  1. Read `planogram_description.shelves` to get shelf count, `height_ratio`, and product lists
  2. Divide ROI vertically into N bands proportional to `height_ratio`
  3. Apply `overlap_margin` from `grid_config` — extend each band's top/bottom by margin (clamped to ROI bounds)
  4. For each band, create a `GridCell` with:
     - `cell_id` = shelf level name (e.g., "top", "middle", "bottom")
     - `bbox` = absolute pixel coords including overlap
     - `expected_products` = product names from that shelf's config
     - `reference_image_keys` = same product names (used to filter reference images later)
     - `level` = shelf level
- Register `HorizontalBands` in the strategy registry (`_GRID_STRATEGIES[GridType.HORIZONTAL_BANDS] = HorizontalBands`)
- Write unit tests

**NOT in scope**: MatrixGrid, ZoneGrid, FlatGrid. Those are future strategies.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/grid/horizontal_bands.py` | CREATE | HorizontalBands strategy |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/grid/strategy.py` | MODIFY | Register HorizontalBands in `_GRID_STRATEGIES` |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/grid/__init__.py` | MODIFY | Add export |
| `tests/pipelines/test_horizontal_bands.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot_pipelines.planogram.grid.models import GridType, DetectionGridConfig, GridCell
from parrot_pipelines.planogram.grid.strategy import AbstractGridStrategy, _GRID_STRATEGIES
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/models/detections.py:301
class PlanogramDescription(BaseModel):
    shelves: List[ShelfConfig]  # each has .level, .height_ratio, .products

# ShelfConfig structure (from planogram config parsing):
# Each shelf has:
#   level: str (e.g., "top", "middle", "bottom")
#   height_ratio: float (e.g., 0.34)
#   products: List[ProductConfig]  # each has .name: str

# Reference: _generate_virtual_shelves logic
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py:956
# Uses height_ratio to allocate vertical space proportionally
# Supports explicit y_start_ratio for non-stacking layouts
```

### Does NOT Exist
- ~~`HorizontalBands`~~ — does not exist; this task creates it
- ~~`MatrixGrid`~~ — out of scope
- ~~`ZoneGrid`~~ — out of scope
- ~~`FlatGrid`~~ — out of scope

---

## Implementation Notes

### Pattern to Follow
```python
# Follow the same vertical allocation logic as _generate_virtual_shelves (line 956)
# but produce GridCells instead of ShelfRegions

class HorizontalBands(AbstractGridStrategy):
    def compute_cells(self, roi_bbox, image_size, planogram_description, grid_config):
        x1, y1, x2, y2 = roi_bbox
        roi_height = y2 - y1
        shelves = planogram_description.shelves
        overlap_px = int(roi_height * grid_config.overlap_margin)

        cells = []
        current_y = y1
        for shelf in shelves:
            band_height = int(roi_height * shelf.height_ratio)
            band_y1 = max(y1, current_y - overlap_px)
            band_y2 = min(y2, current_y + band_height + overlap_px)

            products = [p.name for p in shelf.products]
            cells.append(GridCell(
                cell_id=shelf.level,
                bbox=(x1, band_y1, x2, band_y2),
                expected_products=products,
                reference_image_keys=products,
                level=shelf.level,
            ))
            current_y += band_height

        return cells
```

### Key Constraints
- Bands must not exceed ROI bounds even with overlap margin
- If `shelves` is empty, fall back to single cell (like NoGrid)
- Product names extracted via `shelf.products[].name` — use `getattr` safely
- height_ratios should approximately sum to 1.0 but don't enforce strictly (last band fills remainder)

---

## Acceptance Criteria

- [ ] `HorizontalBands().compute_cells()` produces N cells matching N shelves
- [ ] Each cell's `expected_products` matches that shelf's product names
- [ ] Overlap margin correctly extends bands without exceeding ROI
- [ ] Empty shelves config falls back to single cell
- [ ] Registered in `_GRID_STRATEGIES` and accessible via `get_strategy(GridType.HORIZONTAL_BANDS)`
- [ ] All tests pass

---

## Test Specification

```python
import pytest
from parrot_pipelines.planogram.grid.horizontal_bands import HorizontalBands
from parrot_pipelines.planogram.grid.models import GridType, DetectionGridConfig, GridCell


class TestHorizontalBands:
    def test_three_shelves(self):
        """3 shelves with height_ratios [0.34, 0.25, 0.41] produce 3 bands."""
        strategy = HorizontalBands()
        config = DetectionGridConfig(grid_type=GridType.HORIZONTAL_BANDS, overlap_margin=0.0)
        cells = strategy.compute_cells(
            roi_bbox=(100, 0, 900, 1000),
            image_size=(1920, 1080),
            planogram_description=mock_3_shelf_planogram,
            grid_config=config,
        )
        assert len(cells) == 3
        assert cells[0].level == "top"
        assert cells[1].level == "middle"
        assert cells[2].level == "bottom"

    def test_overlap_extends_bands(self):
        """5% overlap extends each band by overlap_px in both directions."""
        ...

    def test_overlap_clamped_to_roi(self):
        """Overlap cannot extend beyond ROI boundaries."""
        ...

    def test_expected_products_per_band(self):
        """Each band only has products from its shelf config."""
        ...

    def test_empty_shelves_fallback(self):
        """No shelves → single cell like NoGrid."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** for architectural context
2. **Check** TASK-583 and TASK-584 are completed
3. **Read** `product_on_shelves.py:956-1041` (`_generate_virtual_shelves`) for the existing vertical allocation logic — mirror it for grid cells
4. **Implement** following scope above
5. **Run tests** to verify

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-04-05

Created `grid/horizontal_bands.py` with `HorizontalBands(AbstractGridStrategy)`.
`compute_cells()` reads `planogram_description.shelves`, allocates vertical bands proportional
to `shelf.height_ratio`, applies `overlap_margin` (clamped to ROI bounds), and maps
`shelf.products[].name` to `expected_products` / `reference_image_keys` per cell.
Falls back to a single full-ROI cell when `shelves` is empty or `planogram_description` is None.
Self-registers via `_GRID_STRATEGIES[GridType.HORIZONTAL_BANDS] = HorizontalBands` at module level
(import of this module triggers registration; `__init__.py` ensures it is always loaded).
Unit tests at `tests/pipelines/test_horizontal_bands.py` — all pass.

**No deviations from task scope.**
