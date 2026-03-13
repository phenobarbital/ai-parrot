# TASK-337: PlanogramComplianceHandler — Registration & Export

**Feature**: Planogram Compliance Handler
**Spec**: `sdd/specs/planogram-compliance-handler.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 1h)
**Depends-on**: TASK-336
**Assigned-to**: —

---

## Context

> Register the `PlanogramComplianceHandler` in the handlers package export and document the route setup pattern for the main app.
> Implements spec Section 3 (Module 2).

---

## Scope

- Add lazy import for `PlanogramComplianceHandler` in `parrot/handlers/__init__.py` following the existing `__getattr__` pattern.

**NOT in scope**: Handler implementation (TASK-336), tests (TASK-338).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/handlers/__init__.py` | MODIFY | Add `PlanogramComplianceHandler` to `__getattr__` lazy imports |

---

## Implementation Notes

- Follow exact pattern of existing entries in `__getattr__`:
  ```python
  if name == "PlanogramComplianceHandler":
      from .planogram_compliance import PlanogramComplianceHandler
      return PlanogramComplianceHandler
  ```
- Place it alphabetically among existing entries (after `LyriaMusicHandler`, before `VideoReelHandler`).

---

## Acceptance Criteria

- [ ] `from parrot.handlers import PlanogramComplianceHandler` works.
- [ ] No circular imports introduced.
- [ ] Existing handler imports unaffected.

---

## Test Specification

```python
# Quick import check
from parrot.handlers import PlanogramComplianceHandler
assert PlanogramComplianceHandler is not None
```

---

## Agent Instructions

When you pick up this task:

1. **Read `parrot/handlers/__init__.py`** — understand the lazy import pattern.
2. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`.
3. **Add** the `PlanogramComplianceHandler` entry to `__getattr__`.
4. **Verify** import works: `python -c "from parrot.handlers import PlanogramComplianceHandler"`.
5. **Commit**: `sdd: complete TASK-337 — PlanogramComplianceHandler registration`
6. **Update index** → `"done"`.

---

## Completion Note

**Completed by**: Claude (sdd-worker)
**Date**: 2026-03-13
**Notes**: Added `PlanogramComplianceHandler` lazy import to `parrot/handlers/__init__.py`
in alphabetical position between `LyriaMusicHandler` and `VideoReelHandler`.
Verified `from parrot.handlers import PlanogramComplianceHandler` works.

**Deviations from spec**: None.
