# TASK-629: Remove Duplicate `_check_illumination()` from EndcapNoShelvesPromotional

**Feature**: product-on-shelves-illumination
**Spec**: `sdd/specs/product-on-shelves-illumination.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-628
**Assigned-to**: unassigned

---

## Context

Module 2 of FEAT-091. After TASK-628 promotes `_check_illumination()` to the
base class, the duplicate in `EndcapNoShelvesPromotional` must be removed and
the call site updated to use the new base class signature.

Spec section: §3 Module 2.

---

## Scope

- Delete `_check_illumination()` from `EndcapNoShelvesPromotional` (lines 454–558).
- Delete the module-level `_DEFAULT_ILLUMINATION_PENALTY: float = 1.0` at line 35
  — import it from `abstract` instead (or reference the base constant directly).
- Update the call site at line 405-407 to use keyword arguments matching the new
  base class signature (positional args are no longer compatible after the rename).
- Verify that `EndcapNoShelvesPromotional` still inherits `_check_illumination`
  from `AbstractPlanogramType` after deletion.

**NOT in scope**: Any changes to `ProductOnShelves`. Any new test files.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/endcap_no_shelves_promotional.py` | MODIFY | Remove local `_check_illumination()` + `_DEFAULT_ILLUMINATION_PENALTY`; update call site |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# endcap_no_shelves_promotional.py already imports:
from .abstract import AbstractPlanogramType  # line 16
# After this task, also import the constant from abstract:
from .abstract import AbstractPlanogramType, _DEFAULT_ILLUMINATION_PENALTY
# verified: abstract.py will have this constant after TASK-628
```

### Existing Signatures to Use

```python
# packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py
# (After TASK-628 completes):
_DEFAULT_ILLUMINATION_PENALTY: float = 1.0  # module-level constant

class AbstractPlanogramType(ABC):
    async def _check_illumination(
        self,
        img: Image.Image,
        zone_bbox: Optional[Any] = None,
        roi: Optional[Any] = None,
        planogram_description: Optional[Any] = None,
    ) -> Optional[str]: ...

# Current call site in endcap_no_shelves_promotional.py (lines 404-407) to REPLACE:
roi_illumination = await self._check_illumination(
    img, roi, planogram_description, illum_zone_bbox=zone_bbox
)
# ↑ positional-arg style with old param names — MUST update to keyword args:
roi_illumination = await self._check_illumination(
    img,
    zone_bbox=zone_bbox,
    roi=roi,
    planogram_description=planogram_description,
)

# endcap_no_shelves_promotional.py lines 669-683 use _DEFAULT_ILLUMINATION_PENALTY:
# After removing the local constant, this reference still works if imported from abstract.
```

### Does NOT Exist (after this task)

- ~~`EndcapNoShelvesPromotional._check_illumination()`~~ — will be deleted; inherited from base
- ~~`_DEFAULT_ILLUMINATION_PENALTY` in `endcap_no_shelves_promotional.py` module scope~~
  — will be deleted; import from `abstract.py` instead

---

## Implementation Notes

### What to delete
1. Line 35: `_DEFAULT_ILLUMINATION_PENALTY: float = 1.0` (module-level)
2. Lines 454-558: the entire `_check_illumination` method

### What to update
1. Import line: change `from .abstract import AbstractPlanogramType` to
   `from .abstract import AbstractPlanogramType, _DEFAULT_ILLUMINATION_PENALTY`
2. Call site at lines 404-407: replace positional args with keyword args (see above)

### Verify inheritance after deletion

After removing the method, a quick assertion in tests or during implementation:
```python
endcap = EndcapNoShelvesPromotional.__mro__
# _check_illumination must resolve to AbstractPlanogramType._check_illumination
```

### Key Constraints

- Do NOT change any logic in `check_planogram_compliance` (lines 560+)
- Do NOT change the `_extract_illumination_state` call pattern (lines 672, 678)
- Run existing tests to verify zero regression: `pytest packages/ai-parrot-pipelines/tests/test_endcap_no_shelves_promotional.py -v`
- The endcap `_check_illumination` call at line 405 previously returned `str` (never None).
  The new base class returns `Optional[str]`. Check if any code in `detect_objects`
  (endcap) assumes a non-None return and guard if needed (look at line 409:
  `visual_features = [roi_illumination]` — if `roi_illumination` is `None`, this
  creates `[None]` which `_extract_illumination_state` will skip, resulting in no
  illumination entry → no penalty. This is acceptable behaviour.)

---

## Acceptance Criteria

- [ ] `_check_illumination` deleted from `EndcapNoShelvesPromotional` (lines 454-558)
- [ ] `_DEFAULT_ILLUMINATION_PENALTY` deleted from `endcap_no_shelves_promotional.py` module scope
- [ ] `_DEFAULT_ILLUMINATION_PENALTY` imported from `abstract.py`
- [ ] Call site at line ~405 uses keyword arguments (`zone_bbox=`, `roi=`, `planogram_description=`)
- [ ] `EndcapNoShelvesPromotional._check_illumination` still resolves (via inheritance)
- [ ] `pytest packages/ai-parrot-pipelines/tests/test_endcap_no_shelves_promotional.py -v` — all pass

---

## Agent Instructions

1. Verify TASK-628 is in `tasks/completed/` before starting.
2. Read `endcap_no_shelves_promotional.py` in full (focus on lines 35, 404-410, 454-558, 669-699).
3. Make the three edits described above (delete constant, delete method, update call site).
4. Run the endcap tests to confirm no regression.
5. Move this file to `tasks/completed/` and update index → `done`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
