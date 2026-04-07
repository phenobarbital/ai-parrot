# TASK-624: Move `_extract_illumination_state` to AbstractPlanogramType

**Feature**: endcap-no-shelves-promotional-fix
**Spec**: `sdd/specs/endcap-no-shelves-promotional-fix.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

`_extract_illumination_state` is a static helper that parses a `visual_features` list
and returns the illumination state string (`"on"` / `"off"` / `None`). It is currently
defined only in `GraphicPanelDisplay` (line 849 of `graphic_panel_display.py`).

`EndcapNoShelvesPromotional` needs this helper too. Rather than duplicating it, it must
be moved to `AbstractPlanogramType` so all types inherit it. This is the foundation
for TASK-625 and TASK-626.

Implements **Module 1** of FEAT-090.

---

## Scope

- Move `_extract_illumination_state` from `graphic_panel_display.py` to `abstract.py`
- Remove it from `graphic_panel_display.py` (it will inherit from base class)
- Verify `GraphicPanelDisplay` still works — it inherits the method, zero behavior change

**NOT in scope**: any changes to `endcap_no_shelves_promotional.py` or compliance logic.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/abstract.py` | MODIFY | Add `_extract_illumination_state` as static method |
| `packages/ai-parrot-pipelines/src/parrot_pipelines/planogram/types/graphic_panel_display.py` | MODIFY | Remove `_extract_illumination_state` (now inherited) |

---

## Implementation Notes

### Method to move (from `graphic_panel_display.py` line 849)

```python
@staticmethod
def _extract_illumination_state(features: List[str]) -> Optional[str]:
    """Extract illumination state from a visual_features list.
    Returns the value after 'illumination_status:' (e.g. 'on', 'off'),
    or None if not present. Uses first-match.
    """
```

Move this method verbatim into `AbstractPlanogramType` in `abstract.py`.
Then delete it from `graphic_panel_display.py` — the class inherits it from base.

### Key Constraints

- Do NOT change the method signature or logic
- Do NOT change any call sites — they all use `self._extract_illumination_state(...)`
  which works identically whether defined in the class or inherited from base

---

## Acceptance Criteria

- [ ] `_extract_illumination_state` exists in `AbstractPlanogramType`
- [ ] Method removed from `GraphicPanelDisplay` (no duplication)
- [ ] `GraphicPanelDisplay` tests still pass (inherits method transparently)
- [ ] `from parrot_pipelines.planogram.types.abstract import AbstractPlanogramType` exposes the method

## Test Specification

```python
# packages/ai-parrot-pipelines/tests/test_endcap_no_shelves_promotional.py

def test_extract_illumination_state_in_base():
    """Helper is accessible from AbstractPlanogramType."""
    from parrot_pipelines.planogram.types.abstract import AbstractPlanogramType
    result = AbstractPlanogramType._extract_illumination_state(
        ["illumination_status: ON", "ocr: Hello"]
    )
    assert result == "on"

def test_extract_illumination_state_off():
    from parrot_pipelines.planogram.types.abstract import AbstractPlanogramType
    result = AbstractPlanogramType._extract_illumination_state(
        ["illumination_status: OFF"]
    )
    assert result == "off"

def test_extract_illumination_state_none():
    from parrot_pipelines.planogram.types.abstract import AbstractPlanogramType
    result = AbstractPlanogramType._extract_illumination_state(["ocr: Hello"])
    assert result is None
```

---

## Agent Instructions

1. Read `abstract.py` and `graphic_panel_display.py` fully before editing
2. Copy `_extract_illumination_state` verbatim into `AbstractPlanogramType`
3. Delete it from `GraphicPanelDisplay`
4. Run existing `graphic_panel_display` tests to confirm no regression
5. Move this file to `tasks/completed/` and update index

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none
