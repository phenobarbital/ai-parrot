# TASK-654: Promote _check_illumination and _base_model_from_str to AbstractPlanogramType

**Feature**: FEAT-096 — Endcap Backlit Multitier Planogram Type
**Spec**: `sdd/specs/endcap-backlit-multitier.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

This is Module 2 of FEAT-096. `EndcapBacklitMultitier` needs two helpers that currently
live in concrete subclasses, not in `AbstractPlanogramType`:

1. **`_check_illumination()`** — defined in `EndcapNoShelvesPromotional` (line 454). Used
   to determine if the header backlit lightbox is ON or OFF. The new type needs this
   without inheriting from `EndcapNoShelvesPromotional`.

2. **`_base_model_from_str()`** — instance method in `ProductOnShelves` (line 872). Normalizes
   product model strings (e.g. "Epson ES-580W" → "ES-580W"). The new type needs this
   without inheriting from `ProductOnShelves`.

This task promotes both to `AbstractPlanogramType` so all types can inherit them.
`EndcapNoShelvesPromotional` must continue to work after the move.

---

## Scope

- Move `_check_illumination()` from `EndcapNoShelvesPromotional` to `AbstractPlanogramType`
  as a concrete `async` method with the SAME signature. Remove or delegate from the
  concrete class (keep a thin delegating method or remove, whichever avoids duplication).
- Move `_base_model_from_str()` from `ProductOnShelves` to `AbstractPlanogramType` as a
  `@staticmethod` (remove the `self` parameter; update all callers in `ProductOnShelves`
  to call `AbstractPlanogramType._base_model_from_str(s, brand, patterns)` or simply
  `self._base_model_from_str(s, brand, patterns)` — static methods are accessible via
  `self`).
- Run tests to confirm `EndcapNoShelvesPromotional` and `ProductOnShelves` continue to work.

**NOT in scope**: The `EndcapBacklitMultitier` type class (TASK-655). Tests in TASK-658.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py` | MODIFY | Add `_check_illumination` (concrete async) and `_base_model_from_str` (@staticmethod) |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_no_shelves_promotional.py` | MODIFY | Remove or delegate `_check_illumination` to super() |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py` | MODIFY | Remove `_base_model_from_str` instance method (or leave as a thin wrapper) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# abstract.py current imports (top of file):
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple, Union, TYPE_CHECKING
from PIL import Image
from parrot.models.detections import Detection, IdentifiedProduct, ShelfRegion
from parrot.models.compliance import ComplianceResult
# _ILLUMINATION_FEATURE_PREFIX = "illumination_status:"  ← already defined at line 7

# New imports needed in abstract.py for _check_illumination:
# self.pipeline.roi_client  ← already accessed via self.pipeline (PlanogramCompliance)
# self.pipeline._downscale_image()  ← already on PlanogramCompliance
# No new top-level imports needed if we use self.pipeline.roi_client for LLM calls
```

### Existing Signatures to Use

```python
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py

class AbstractPlanogramType(ABC):
    def __init__(self, pipeline: "PlanogramCompliance", config: "PlanogramConfig") -> None:
        # line 42
        self.pipeline = pipeline
        self.config = config
        self.logger = pipeline.logger

    # line 126 — already in abstract (static helper for parsing illumination state)
    @staticmethod
    def _extract_illumination_state(features: List[str]) -> Optional[str]:
        # parses "illumination_status: ON/OFF" from feature list
        ...

    # line 145 — already in abstract
    def get_render_colors(self) -> Dict[str, Tuple[int, int, int]]: ...

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_no_shelves_promotional.py:454
# SOURCE for _check_illumination — copy VERBATIM to abstract.py, then delegate here:
async def _check_illumination(
    self,
    img: Image.Image,
    roi: Any,
    planogram_description: Any,
    illum_zone_bbox: Optional[Any] = None,
) -> str:
    """Returns 'illumination_status: ON' or 'illumination_status: OFF'"""
    ...
    # Uses: self.pipeline._downscale_image(roi_crop, max_side=800, quality=82)
    # Uses: self.pipeline.roi_client (for LLM call)
    # Uses: planogram_description.brand (getattr fallback)

# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/product_on_shelves.py:872
# SOURCE for _base_model_from_str — convert to @staticmethod in abstract.py:
def _base_model_from_str(
    self, s: str, brand: str = None, patterns: Optional[List[str]] = None
) -> str:
    ...
```

### Does NOT Exist

- ~~`AbstractPlanogramType._check_illumination()`~~ — does NOT exist in abstract.py today.
  It lives only in `EndcapNoShelvesPromotional`. THIS task promotes it.
- ~~`AbstractPlanogramType._base_model_from_str()`~~ — does NOT exist in abstract.py today.
  It is an instance method on `ProductOnShelves`. THIS task promotes it as @staticmethod.
- ~~`AbstractPlanogramType._check_illumination_from_roi()`~~ — that method name belongs to
  `GraphicPanelDisplay`, not to what we need. Use `_check_illumination`.

---

## Implementation Notes

### Strategy for _check_illumination promotion

1. Copy the full method body from `endcap_no_shelves_promotional.py:454` into `abstract.py`.
2. Place it after `_extract_illumination_state` (after line 143).
3. In `EndcapNoShelvesPromotional`, replace the method body with:
   ```python
   async def _check_illumination(self, img, roi, planogram_description, illum_zone_bbox=None):
       return await super()._check_illumination(img, roi, planogram_description, illum_zone_bbox)
   ```
   Or simply delete the override if the signature is identical (Python MRO will find it in abstract).

### Strategy for _base_model_from_str promotion

1. Read the full method body from `product_on_shelves.py:872`.
2. Add `@staticmethod` decorator and remove `self` parameter in the signature.
3. In `ProductOnShelves`, update all calls:
   - `self._base_model_from_str(s, brand, patterns)` still works for static methods via `self`.
   - No call-site changes required.
4. Remove the instance method from `ProductOnShelves`.

### Key Constraints
- Do NOT change the method signatures (same params/return types as originals).
- The `_check_illumination` in abstract must use `self.pipeline.roi_client` and
  `self.pipeline._downscale_image()` — the same pipeline attributes used in the original.
- Google-style docstrings on promoted methods.
- After this task: `grep "_check_illumination" types/abstract.py` must show the definition.

---

## Acceptance Criteria

- [ ] `AbstractPlanogramType._check_illumination` defined in `abstract.py` (async)
- [ ] `AbstractPlanogramType._base_model_from_str` defined in `abstract.py` (@staticmethod)
- [ ] `EndcapNoShelvesPromotional` tests pass (no regression)
- [ ] `ProductOnShelves` tests pass (no regression)
- [ ] `grep "_check_illumination" packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py` returns a hit
- [ ] `ruff check packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py`

---

## Test Specification

```python
# Quick regression tests (run existing test suite):
# source .venv/bin/activate
# pytest packages/ai-parrot-pipelines/tests/ -v -k "illumination or endcap_no_shelves or product_on_shelves"

# Smoke test for promotion:
from parrot_pipelines.planogram.types.abstract import AbstractPlanogramType

def test_base_model_from_str_is_static():
    result = AbstractPlanogramType._base_model_from_str("Epson ES-580W")
    assert isinstance(result, str)

def test_check_illumination_exists():
    import inspect
    assert hasattr(AbstractPlanogramType, "_check_illumination")
    assert inspect.iscoroutinefunction(AbstractPlanogramType._check_illumination)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/endcap-backlit-multitier.spec.md`.
2. **Check dependencies** — none. Run in parallel with TASK-653.
3. **Read source files first**:
   - `endcap_no_shelves_promotional.py` lines 454-570 (full `_check_illumination` body)
   - `product_on_shelves.py` lines 872-940 (full `_base_model_from_str` body)
   - `abstract.py` lines 125-175 (insertion point)
4. **Update status** in `tasks/.index.json` → `"in-progress"`.
5. **Implement** following the scope above.
6. **Run** `source .venv/bin/activate && pytest packages/ai-parrot-pipelines/tests/ -v` to verify no regressions.
7. **Move this file** to `tasks/completed/TASK-654-promote-helpers-abstract.md`.
8. **Update index** → `"done"`.
9. **Commit** with message: `sdd: TASK-654 promote _check_illumination and _base_model_from_str to AbstractPlanogramType`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: —
**Date**: —
**Notes**: —
**Deviations from spec**: none
