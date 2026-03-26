# TASK-450: Populate __init__.py with public exports

**Feature**: refactor-workingmemorytoolkit
**Spec**: `sdd/specs/refactor-workingmemorytoolkit.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-449
**Assigned-to**: unassigned

---

## Context

Per the spec (Module 4), the `__init__.py` is currently empty. It must re-export the public API so consumers can do `from parrot.tools.working_memory import WorkingMemoryToolkit`.

---

## Scope

- Populate `__init__.py` with imports and `__all__` for:
  - `WorkingMemoryToolkit` (from `.tool`)
  - Key enums: `OperationType`, `JoinHow`, `AggFunc` (from `.models`)
  - Key input models: `FilterSpec`, `OperationSpecInput`, `ComputeAndStoreInput` (from `.models`)
- Add a module docstring

**NOT in scope**: Test relocation.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/working_memory/__init__.py` | REWRITE | Add public exports |

---

## Implementation Notes

### Pattern to Follow
```python
"""WorkingMemoryToolkit — intermediate result store for analytical operations."""
from .tool import WorkingMemoryToolkit
from .models import (
    OperationType, JoinHow, AggFunc,
    FilterSpec, OperationSpecInput, ComputeAndStoreInput,
)

__all__ = [
    "WorkingMemoryToolkit",
    "OperationType",
    "JoinHow",
    "AggFunc",
    "FilterSpec",
    "OperationSpecInput",
    "ComputeAndStoreInput",
]
```

### References in Codebase
- `packages/ai-parrot/src/parrot/tools/__init__.py` — example of package exports pattern

---

## Acceptance Criteria

- [ ] `from parrot.tools.working_memory import WorkingMemoryToolkit` works
- [ ] `from parrot.tools.working_memory import OperationType, AggFunc` works
- [ ] `__all__` is defined
- [ ] All existing tests still pass

---

## Test Specification

```python
from parrot.tools.working_memory import WorkingMemoryToolkit, OperationType, AggFunc
assert OperationType.FILTER == "filter"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-450-package-init.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-03-26
**Notes**: Populated __init__.py with WorkingMemoryToolkit, OperationType, JoinHow, AggFunc, FilterSpec, OperationSpecInput, ComputeAndStoreInput and __all__ list.

**Deviations from spec**: none
