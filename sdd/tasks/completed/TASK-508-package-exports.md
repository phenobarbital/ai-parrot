# TASK-508: Update Package Exports

**Feature**: extending-workingmemorytoolkit
**Spec**: `sdd/specs/extending-workingmemorytoolkit.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-503, TASK-505, TASK-506
**Assigned-to**: unassigned

---

## Context

With all new types and tools implemented, the package `__init__.py` must
export the new public symbols so consumers can import them directly.

Implements **Module 6** from the spec.

---

## Scope

- Update `packages/ai-parrot/src/parrot/tools/working_memory/__init__.py` to
  export the new symbols:
  - From `models.py`: `EntryType`, `StoreResultInput`, `GetResultInput`,
    `SearchStoredInput`, `SaveInteractionInput`, `RecallInteractionInput`
  - From `internals.py`: `GenericEntry`
- Add all new exports to `__all__`.

**NOT in scope**: any code changes to models, internals, or tool.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/working_memory/__init__.py` | MODIFY | Add new exports |

---

## Implementation Notes

### Current Exports

```python
from .tool import WorkingMemoryToolkit
from .models import (
    OperationType, JoinHow, AggFunc,
    FilterSpec, OperationSpecInput, ComputeAndStoreInput,
)
```

### New Exports to Add

```python
from .models import (
    EntryType,
    StoreResultInput,
    GetResultInput,
    SearchStoredInput,
    SaveInteractionInput,
    RecallInteractionInput,
)
from .internals import GenericEntry
```

---

## Acceptance Criteria

- [ ] `from parrot.tools.working_memory import EntryType` works
- [ ] `from parrot.tools.working_memory import GenericEntry` works
- [ ] `from parrot.tools.working_memory import StoreResultInput` works
- [ ] `from parrot.tools.working_memory import SaveInteractionInput` works
- [ ] `from parrot.tools.working_memory import RecallInteractionInput` works
- [ ] `from parrot.tools.working_memory import SearchStoredInput` works
- [ ] `from parrot.tools.working_memory import GetResultInput` works
- [ ] All new symbols in `__all__`
- [ ] All existing tests pass

---

## Test Specification

```python
def test_imports():
    from parrot.tools.working_memory import (
        WorkingMemoryToolkit,
        EntryType,
        GenericEntry,
        StoreResultInput,
        GetResultInput,
        SearchStoredInput,
        SaveInteractionInput,
        RecallInteractionInput,
    )
    assert EntryType.TEXT.value == "text"
    assert GenericEntry is not None
```

---

## Agent Instructions

When you pick up this task:

1. **Check dependencies** — TASK-503, TASK-505, TASK-506 must be complete
2. **Update status** in `sdd/tasks/.index.json` → `"in-progress"`
3. **Implement** following the scope above
4. **Verify** all acceptance criteria are met
5. **Move this file** to `sdd/tasks/completed/TASK-508-package-exports.md`
6. **Update index** → `"done"`
7. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker
**Date**: 2026-04-02
**Notes**: Implemented as specified. All 115 tests pass.

**Deviations from spec**: none
