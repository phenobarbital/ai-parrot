# TASK-594: Register New Planogram Types and Update Exports

**Feature**: planogram-new-types
**Spec**: `sdd/specs/planogram-new-types.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-592, TASK-593
**Assigned-to**: unassigned

---

## Context

This task wires up the two new planogram types (`ProductCounter` and `EndcapNoShelvesPromotional`) into the pipeline's type registry and module exports so they are usable via the `planogram_type` config field.

Implements Spec Section 3 — Module 3.

---

## Scope

- Add `ProductCounter` and `EndcapNoShelvesPromotional` to `__init__.py` exports.
- Add both types to `PlanogramCompliance._PLANOGRAM_TYPES` dict in `plan.py`.
- Verify that `PlanogramCompliance` can resolve both new types from config.

**NOT in scope**:
- Implementation of the type classes themselves (TASK-592, TASK-593)
- Example configs (TASK-595)
- Tests beyond smoke verification (TASK-596)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/__init__.py` | MODIFY | Add imports and exports for both new types |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py` | MODIFY | Add entries to `_PLANOGRAM_TYPES` dict |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/__init__.py (current):
from .abstract import AbstractPlanogramType
from .product_on_shelves import ProductOnShelves
from .graphic_panel_display import GraphicPanelDisplay

__all__ = (
    "AbstractPlanogramType",
    "ProductOnShelves",
    "GraphicPanelDisplay",
)
```

```python
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py:16
from .types import ProductOnShelves, GraphicPanelDisplay
```

### Existing Signatures to Use
```python
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py:32-35
_PLANOGRAM_TYPES = {
    "product_on_shelves": ProductOnShelves,
    "graphic_panel_display": GraphicPanelDisplay,
}
```

### Does NOT Exist
- ~~`PlanogramCompliance.register_type()`~~ — no dynamic registration method; types are added to the `_PLANOGRAM_TYPES` dict directly

---

## Implementation Notes

### Exact Changes Required

**`__init__.py`** — add two imports and exports:
```python
from .product_counter import ProductCounter
from .endcap_no_shelves_promotional import EndcapNoShelvesPromotional

__all__ = (
    "AbstractPlanogramType",
    "ProductOnShelves",
    "GraphicPanelDisplay",
    "ProductCounter",
    "EndcapNoShelvesPromotional",
)
```

**`plan.py`** — add to import line and dict:
```python
from .types import ProductOnShelves, GraphicPanelDisplay, ProductCounter, EndcapNoShelvesPromotional

_PLANOGRAM_TYPES = {
    "product_on_shelves": ProductOnShelves,
    "graphic_panel_display": GraphicPanelDisplay,
    "product_counter": ProductCounter,
    "endcap_no_shelves_promotional": EndcapNoShelvesPromotional,
}
```

---

## Acceptance Criteria

- [ ] Both types importable: `from parrot_pipelines.planogram.types import ProductCounter, EndcapNoShelvesPromotional`
- [ ] Both types resolvable from `PlanogramCompliance._PLANOGRAM_TYPES`
- [ ] Existing types (`product_on_shelves`, `graphic_panel_display`) still work
- [ ] No import errors when loading the module

---

## Test Specification

```python
def test_type_registration():
    from parrot_pipelines.planogram.plan import PlanogramCompliance
    assert "product_counter" in PlanogramCompliance._PLANOGRAM_TYPES
    assert "endcap_no_shelves_promotional" in PlanogramCompliance._PLANOGRAM_TYPES

def test_imports():
    from parrot_pipelines.planogram.types import ProductCounter, EndcapNoShelvesPromotional
    assert ProductCounter is not None
    assert EndcapNoShelvesPromotional is not None
```

---

## Agent Instructions

When you pick up this task:

1. **Verify dependencies** — TASK-592 and TASK-593 must be completed first
2. **Verify the files exist** — `product_counter.py` and `endcap_no_shelves_promotional.py`
3. **Update status** in `tasks/.index.json` → `"in-progress"`
4. **Implement** the exact changes listed above
5. **Verify** all acceptance criteria
6. **Move this file** to `tasks/completed/`
7. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
