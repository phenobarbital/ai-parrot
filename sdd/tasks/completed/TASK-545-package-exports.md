# TASK-545: Package Exports for DatabaseFormTool

**Feature**: Form Builder from Database Definition
**Spec**: `sdd/specs/formbuilder-database.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-544
**Assigned-to**: unassigned

---

## Context

After `DatabaseFormTool` is implemented (TASK-544), it must be exported from the
`parrot.forms.tools` and `parrot.forms` packages so users can import it.

Implements **Module 2** from the spec.

---

## Scope

- Add `DatabaseFormTool` to `parrot/forms/tools/__init__.py` exports
- Add `DatabaseFormTool` to `parrot/forms/__init__.py` exports
- Verify import works: `from parrot.forms import DatabaseFormTool`

**NOT in scope**: Tool implementation (TASK-544), example UI (TASK-546), tests (TASK-547)

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/forms/tools/__init__.py` | MODIFY | Add DatabaseFormTool import and __all__ entry |
| `packages/ai-parrot/src/parrot/forms/__init__.py` | MODIFY | Add DatabaseFormTool to public exports |

---

## Implementation Notes

### Pattern to Follow
```python
# In tools/__init__.py — follow existing pattern:
from .database_form import DatabaseFormTool

__all__ = [
    "RequestFormTool",
    "CreateFormTool",
    "DatabaseFormTool",
]
```

### References in Codebase
- `packages/ai-parrot/src/parrot/forms/tools/__init__.py` — current exports
- `packages/ai-parrot/src/parrot/forms/__init__.py` — current public API

---

## Acceptance Criteria

- [ ] `from parrot.forms.tools import DatabaseFormTool` works
- [ ] `from parrot.forms import DatabaseFormTool` works
- [ ] No circular imports
- [ ] Existing exports unchanged

---

## Test Specification

```python
# Verify import succeeds
from parrot.forms import DatabaseFormTool
from parrot.forms.tools import DatabaseFormTool

assert DatabaseFormTool is not None
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/formbuilder-database.spec.md` for full context
2. **Check dependencies** — TASK-544 must be complete
3. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-545-package-exports.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: Claude (sdd-worker)
**Date**: 2026-04-03
**Notes**: Added `DatabaseFormTool` to `parrot/forms/tools/__init__.py` (import + `__all__`) and to `parrot/forms/__init__.py` (import + `__all__`). Import verification passed: both `from parrot.forms.tools import DatabaseFormTool` and `from parrot.forms import DatabaseFormTool` resolve to the same class.

**Deviations from spec**: none
