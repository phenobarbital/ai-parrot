# TASK-589: AbstractPlanogramType Grid Integration

**Feature**: parrot-pipelines-inconsistency
**Spec**: `sdd/specs/parrot-pipelines-inconsistency.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-584
**Assigned-to**: unassigned

---

## Context

Extends `AbstractPlanogramType` with a `get_grid_strategy()` method that returns the appropriate grid strategy for each planogram type. The default implementation returns `NoGrid`, ensuring backward compatibility. Concrete types override to return their specific strategy. Implements Spec Module 7.

---

## Scope

- Add `get_grid_strategy() -> AbstractGridStrategy` method to `AbstractPlanogramType` with default `NoGrid` implementation (NOT abstract — concrete default)
- This is a non-breaking addition: existing concrete types (`ProductOnShelves`, `GraphicPanelDisplay`) automatically get `NoGrid` behavior
- Write a simple test

**NOT in scope**: Overriding `get_grid_strategy()` in `ProductOnShelves` (that's TASK-590).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py` | MODIFY | Add get_grid_strategy() method |
| `tests/pipelines/test_abstract_type_grid.py` | CREATE | Test default returns NoGrid |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# Add to abstract.py imports:
from parrot_pipelines.planogram.grid.strategy import AbstractGridStrategy, NoGrid
```

### Existing Signatures to Use
```python
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py:21
class AbstractPlanogramType(ABC):
    def __init__(self, pipeline: "PlanogramCompliance", config: "PlanogramConfig") -> None:
        self.pipeline = pipeline  # line 44
        self.config = config  # line 45
        self.logger = pipeline.logger  # line 46

    # Existing concrete method (pattern to follow):
    def get_render_colors(self) -> Dict[str, Tuple[int, int, int]]:  # line 122
        return {...}
```

### Does NOT Exist
- ~~`AbstractPlanogramType.get_grid_strategy()`~~ — does not exist; this task adds it

---

## Implementation Notes

### Change to abstract.py
```python
# Add after get_render_colors() method (after line 136):
def get_grid_strategy(self) -> "AbstractGridStrategy":
    """Return the grid decomposition strategy for this planogram type.

    Override in concrete types to return a type-specific strategy.
    Default returns NoGrid (single cell = full ROI, current behavior).

    Returns:
        AbstractGridStrategy instance.
    """
    from parrot_pipelines.planogram.grid.strategy import NoGrid
    return NoGrid()
```

### Key Constraints
- Use lazy import (`from ... import NoGrid` inside method) to avoid circular imports
- Method is concrete (not abstract) — existing types get it for free
- Return a new instance each time (strategies are stateless)

---

## Acceptance Criteria

- [ ] `AbstractPlanogramType` has `get_grid_strategy()` method
- [ ] Default returns `NoGrid` instance
- [ ] Existing `ProductOnShelves` and `GraphicPanelDisplay` get NoGrid by default
- [ ] No circular import issues
- [ ] All existing tests still pass

---

## Test Specification

```python
from parrot_pipelines.planogram.grid.strategy import NoGrid


class TestAbstractTypeGridIntegration:
    def test_default_returns_no_grid(self):
        """Default get_grid_strategy returns NoGrid."""
        # Create a mock/concrete subclass and verify
        type_handler = create_mock_planogram_type()
        strategy = type_handler.get_grid_strategy()
        assert isinstance(strategy, NoGrid)
```

---

## Agent Instructions

When you pick up this task:

1. **Check** TASK-584 is completed
2. **Read** `abstract.py` — add method after `get_render_colors()` (line 136)
3. **Use lazy import** to avoid circular deps
4. **Run existing tests** to verify no breakage

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-04-05

Added `get_grid_strategy()` as a concrete (non-abstract) method to `AbstractPlanogramType`
in `planogram/types/abstract.py`, after `get_render_colors()`. Uses a lazy import
(`from parrot_pipelines.planogram.grid.strategy import NoGrid` inside the method body)
to avoid circular imports. Returns `NoGrid()` by default, giving all existing concrete
types (`ProductOnShelves`, `GraphicPanelDisplay`) backward-compatible single-image behavior.

**Post-review fix**: return type annotation corrected from `Any` to `"AbstractGridStrategy"`
via a `TYPE_CHECKING`-guarded import in `abstract.py` (applied during code review of FEAT-084).
Unit tests at `tests/pipelines/test_abstract_type_grid.py` — all pass.
