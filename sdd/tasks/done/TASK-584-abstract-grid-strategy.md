# TASK-584: Abstract Grid Strategy & NoGrid Default

**Feature**: parrot-pipelines-inconsistency
**Spec**: `sdd/specs/parrot-pipelines-inconsistency.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-583
**Assigned-to**: unassigned

---

## Context

Defines the `AbstractGridStrategy` ABC that all grid decomposition strategies implement, plus the `NoGrid` default strategy that preserves current single-image behavior. Implements Spec Module 2.

---

## Scope

- Implement `AbstractGridStrategy` ABC with abstract method `compute_cells(roi_bbox, image_size, planogram_description, grid_config) -> List[GridCell]`
- Implement `NoGrid(AbstractGridStrategy)` — returns a single `GridCell` covering the entire ROI with all expected products
- Add a `get_strategy(grid_type: GridType) -> AbstractGridStrategy` factory function with a strategy registry dict
- Write unit tests for `NoGrid`
- Update `grid/__init__.py` to export new classes

**NOT in scope**: HorizontalBands, MatrixGrid, or any concrete strategy beyond NoGrid.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/grid/strategy.py` | CREATE | AbstractGridStrategy ABC + NoGrid + registry |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/grid/__init__.py` | MODIFY | Add exports |
| `tests/pipelines/test_grid_strategy.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from abc import ABC, abstractmethod  # stdlib
from typing import Any, List, Tuple  # stdlib
# From TASK-583 (created in prior task):
from parrot_pipelines.planogram.grid.models import GridType, DetectionGridConfig, GridCell
```

### Existing Signatures to Use
```python
# From TASK-583 (will exist after prior task):
# parrot_pipelines/planogram/grid/models.py
class GridCell(BaseModel):
    cell_id: str
    bbox: Tuple[int, int, int, int]
    expected_products: List[str] = []
    reference_image_keys: List[str] = []
    level: Optional[str] = None

class DetectionGridConfig(BaseModel):
    grid_type: GridType = GridType.NO_GRID
    overlap_margin: float = 0.05
    max_image_size: int = 1024

# Planogram shelves structure (read-only, for extracting all product names):
# packages/ai-parrot/src/parrot/models/detections.py:301
class PlanogramDescription(BaseModel):
    shelves: List[ShelfConfig]
    brand: str
```

### Does NOT Exist
- ~~`AbstractGridStrategy`~~ — does not exist; this task creates it
- ~~`NoGrid`~~ — does not exist; this task creates it
- ~~`get_strategy()`~~ — does not exist; this task creates it
- ~~`HorizontalBands`~~ — does not exist (TASK-585)

---

## Implementation Notes

### Pattern to Follow
```python
class AbstractGridStrategy(ABC):
    @abstractmethod
    def compute_cells(
        self,
        roi_bbox: Tuple[int, int, int, int],
        image_size: Tuple[int, int],
        planogram_description: Any,
        grid_config: DetectionGridConfig,
    ) -> List[GridCell]:
        ...

class NoGrid(AbstractGridStrategy):
    def compute_cells(self, roi_bbox, image_size, planogram_description, grid_config) -> List[GridCell]:
        # Extract ALL product names from ALL shelves
        # Return single GridCell covering full ROI
        ...

_GRID_STRATEGIES = {
    GridType.NO_GRID: NoGrid,
}

def get_strategy(grid_type: GridType) -> AbstractGridStrategy:
    cls = _GRID_STRATEGIES.get(grid_type)
    if cls is None:
        raise ValueError(f"Unknown grid type: {grid_type}")
    return cls()
```

### Key Constraints
- `NoGrid.compute_cells()` must extract all product names from `planogram_description.shelves[].products[].name` as `expected_products`
- `NoGrid` returns exactly 1 `GridCell` with `cell_id="full_roi"` and `bbox=roi_bbox`
- Strategy registry must be extensible (other tasks add to `_GRID_STRATEGIES`)

---

## Acceptance Criteria

- [ ] `AbstractGridStrategy` is an ABC with `compute_cells()` abstract method
- [ ] `NoGrid` returns a single `GridCell` covering the full ROI
- [ ] `get_strategy(GridType.NO_GRID)` returns a `NoGrid` instance
- [ ] `get_strategy(GridType.HORIZONTAL_BANDS)` raises `ValueError` (not registered yet)
- [ ] All tests pass

---

## Test Specification

```python
import pytest
from parrot_pipelines.planogram.grid.strategy import AbstractGridStrategy, NoGrid, get_strategy
from parrot_pipelines.planogram.grid.models import GridType, DetectionGridConfig, GridCell


class TestNoGrid:
    def test_returns_single_cell(self):
        strategy = NoGrid()
        config = DetectionGridConfig()
        cells = strategy.compute_cells(
            roi_bbox=(100, 50, 900, 750),
            image_size=(1920, 1080),
            planogram_description=mock_planogram,
            grid_config=config,
        )
        assert len(cells) == 1
        assert cells[0].cell_id == "full_roi"
        assert cells[0].bbox == (100, 50, 900, 750)

    def test_collects_all_products(self):
        # All products from all shelves should be in expected_products
        ...


class TestStrategyRegistry:
    def test_no_grid_registered(self):
        strategy = get_strategy(GridType.NO_GRID)
        assert isinstance(strategy, NoGrid)

    def test_unknown_raises(self):
        with pytest.raises(ValueError):
            get_strategy(GridType.HORIZONTAL_BANDS)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/parrot-pipelines-inconsistency.spec.md`
2. **Check dependencies** — verify TASK-583 is in `tasks/completed/`
3. **Verify** that `parrot_pipelines.planogram.grid.models` exists with `GridType`, `GridCell`, `DetectionGridConfig`
4. **Implement** following scope above
5. **Run tests** to verify

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-04-05

Created `grid/strategy.py` with `AbstractGridStrategy` ABC and `NoGrid` concrete strategy.
`NoGrid.compute_cells()` returns a single `GridCell(cell_id="full_roi", bbox=roi_bbox)` collecting
all product names from `planogram_description.shelves[].products[].name` via `getattr` for safety.
Strategy registry `_GRID_STRATEGIES` and `get_strategy()` factory implemented.
`get_strategy(GridType.HORIZONTAL_BANDS)` correctly raises `ValueError` at this stage
(HorizontalBands is registered in TASK-585).
Unit tests at `tests/pipelines/test_grid_strategy.py` — all pass.

**No deviations from task scope.**
