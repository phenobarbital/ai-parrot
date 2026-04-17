# TASK-656: Pipeline integration — register type and add plan.py guards

**Feature**: endcap-backlit-multitier
**Spec**: `sdd/specs/endcap-backlit-multitier.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-655
**Assigned-to**: unassigned

---

## Context

This is Module 4 of FEAT-096. After the type class exists (TASK-655), it must be:
1. Registered in `_PLANOGRAM_TYPES` so `PlanogramCompliance` can dispatch to it.
2. Exported from the `types/__init__.py` package.

Additionally, `plan.py` currently calls `_generate_virtual_shelves()` and
`_assign_products_to_shelves()` unconditionally on every type handler. The new type
does NOT implement these methods (they belong to `ProductOnShelves`). Without guards,
`PlanogramCompliance.run()` will raise `AttributeError` when using the new type.

---

## Scope

- Add `"endcap_backlit_multitier": EndcapBacklitMultitier` to `_PLANOGRAM_TYPES` in `plan.py`.
- Add `from .endcap_backlit_multitier import EndcapBacklitMultitier` import in `plan.py`.
- Add `EndcapBacklitMultitier` to `types/__init__.py` exports.
- Wrap the `_generate_virtual_shelves()` call at `plan.py:277` with a `hasattr` guard.
- Wrap the `_assign_products_to_shelves()` call at `plan.py:291` with a `hasattr` guard.

**NOT in scope**: The type implementation (TASK-655). Tests (TASK-658).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py` | MODIFY | Add import, register type, add hasattr guards |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/__init__.py` | MODIFY | Export EndcapBacklitMultitier |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# plan.py line 17 — existing import line to extend:
from .types import ProductOnShelves, GraphicPanelDisplay, ProductCounter, EndcapNoShelvesPromotional
# BECOMES:
from .types import ProductOnShelves, GraphicPanelDisplay, ProductCounter, EndcapNoShelvesPromotional, EndcapBacklitMultitier

# types/__init__.py line 6 — existing exports to extend:
from .endcap_no_shelves_promotional import EndcapNoShelvesPromotional
# ADD:
from .endcap_backlit_multitier import EndcapBacklitMultitier
```

### Existing Signatures to Use

```python
# plan.py:33 — _PLANOGRAM_TYPES dict (ADD new entry):
_PLANOGRAM_TYPES = {
    "product_on_shelves": ProductOnShelves,
    "graphic_panel_display": GraphicPanelDisplay,
    "product_counter": ProductCounter,
    "endcap_no_shelves_promotional": EndcapNoShelvesPromotional,
    # ADD:
    "endcap_backlit_multitier": EndcapBacklitMultitier,
}

# plan.py:272-280 — CURRENT (unconditional, must add guard):
if endcap and endcap.bbox:
    self.logger.info("Generating virtual shelves from Endcap ROI...")
    virtual_shelves = self._type_handler._generate_virtual_shelves(
        endcap.bbox, img.size, planogram_description
    )
    shelf_regions = virtual_shelves

# plan.py:289-293 — CURRENT (unconditional, must add guard):
_use_y1 = _pg_cfg.get("use_fact_tag_boundaries", False)
self._type_handler._assign_products_to_shelves(
    identified_products, shelf_regions, use_y1_assignment=_use_y1
)

# types/__init__.py:1-14 — current content (verified):
from .abstract import AbstractPlanogramType
from .product_on_shelves import ProductOnShelves
from .graphic_panel_display import GraphicPanelDisplay
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

### Does NOT Exist

- ~~`EndcapBacklitMultitier._generate_virtual_shelves()`~~ — the new type does NOT implement this. The guard in plan.py prevents the crash.
- ~~`EndcapBacklitMultitier._assign_products_to_shelves()`~~ — same: not implemented, needs guard.
- ~~`EndcapBacklitMultitier._ocr_fact_tags()`~~ — not implemented in the new type.
- ~~`AbstractPlanogramType._generate_virtual_shelves()`~~ — not on the abstract base.

---

## Implementation Notes

### Guards pattern
Use `hasattr` to check before calling type-handler methods that are only on some types:

```python
# plan.py:272 area — replace unconditional call:
if endcap and endcap.bbox:
    if hasattr(self._type_handler, "_generate_virtual_shelves"):
        self.logger.info("Generating virtual shelves from Endcap ROI...")
        virtual_shelves = self._type_handler._generate_virtual_shelves(
            endcap.bbox, img.size, planogram_description
        )
        shelf_regions = virtual_shelves
    else:
        self.logger.debug(
            "Type %s does not use _generate_virtual_shelves; skipping.",
            type(self._type_handler).__name__,
        )

# plan.py:291 area — replace unconditional call:
if hasattr(self._type_handler, "_assign_products_to_shelves"):
    _use_y1 = _pg_cfg.get("use_fact_tag_boundaries", False)
    self._type_handler._assign_products_to_shelves(
        identified_products, shelf_regions, use_y1_assignment=_use_y1
    )
```

### __all__ extension in types/__init__.py
Add `"EndcapBacklitMultitier"` to the `__all__` tuple.

---

## Acceptance Criteria

- [ ] `PlanogramCompliance(planogram_config=cfg_with_type_endcap_backlit_multitier, ...)` instantiates without `ValueError`
- [ ] `from parrot_pipelines.planogram.types import EndcapBacklitMultitier` works
- [ ] `"endcap_backlit_multitier"` present in `_PLANOGRAM_TYPES`
- [ ] `plan.py` no longer calls `_generate_virtual_shelves` without `hasattr` guard
- [ ] `plan.py` no longer calls `_assign_products_to_shelves` without `hasattr` guard
- [ ] `ProductOnShelves` still dispatches through plan.py correctly (no regression)
- [ ] `ruff check packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/plan.py`

---

## Test Specification

```python
# Quick smoke test:
from parrot_pipelines.planogram.types import EndcapBacklitMultitier
from parrot_pipelines.planogram.plan import PlanogramCompliance

def test_type_registered():
    assert "endcap_backlit_multitier" in PlanogramCompliance._PLANOGRAM_TYPES
    assert PlanogramCompliance._PLANOGRAM_TYPES["endcap_backlit_multitier"] is EndcapBacklitMultitier
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/endcap-backlit-multitier.spec.md`.
2. **Check dependencies** — TASK-655 must be in `tasks/completed/`.
3. **Read plan.py** around lines 270-310 to identify the exact lines to wrap with guards.
4. **Update status** in `tasks/.index.json` → `"in-progress"`.
5. **Implement** the 4 changes: import, dict entry, two guards.
6. **Run** `source .venv/bin/activate && python -c "from parrot_pipelines.planogram.plan import PlanogramCompliance; print(PlanogramCompliance._PLANOGRAM_TYPES)"` to verify.
7. **Move this file** to `tasks/completed/TASK-656-plan-pipeline-integration.md`.
8. **Update index** → `"done"`.
9. **Commit** with message: `sdd: TASK-656 register EndcapBacklitMultitier and add plan.py guards`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: —
**Date**: —
**Notes**: —
**Deviations from spec**: none
