# TASK-447: Extract enums and Pydantic models to models.py

**Feature**: refactor-workingmemorytoolkit
**Spec**: `sdd/specs/refactor-workingmemorytoolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S (< 2h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

The `tool.py` monolith contains all enums and Pydantic input models inline. Per the spec (Module 1), these must be extracted to `models.py` so that `internals.py` and `tool.py` can import them independently.

This is the foundational task — all subsequent tasks depend on it.

---

## Scope

- Move the following enums from `tool.py` to `models.py`:
  - `OperationType`
  - `JoinHow`
  - `AggFunc`
- Move the following Pydantic models from `tool.py` to `models.py`:
  - `FilterSpec`, `JoinOnSpec`, `OperationSpecInput`
  - `StoreInput`, `DropStoredInput`, `GetStoredInput`, `ListStoredInput`
  - `ComputeAndStoreInput`, `MergeStoredInput`, `SummarizeStoredInput`
  - `ImportFromToolInput`, `ListToolDataFramesInput`
- Add necessary imports at the top of `models.py` (`pydantic`, `enum`, `typing`)
- Add Google-style docstrings to all classes (purpose/description only, no usage)
- Update `tool.py` to import from `.models` instead of defining inline
- Verify `tool.py` still works with the new imports (basic import check)

**NOT in scope**: Moving internal classes, changing `__init__.py`, test relocation.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/working_memory/models.py` | REWRITE | Populate with enums + Pydantic models |
| `packages/ai-parrot/src/parrot/tools/working_memory/tool.py` | MODIFY | Remove inline enums/models, import from `.models` |

---

## Implementation Notes

### Pattern to Follow
```python
# models.py
from __future__ import annotations
from typing import Any, Optional
from enum import Enum
from pydantic import BaseModel, Field


class OperationType(str, Enum):
    """Allowed deterministic operations the agent can request."""
    FILTER = "filter"
    ...
```

### Key Constraints
- Preserve all field definitions, defaults, and descriptions exactly
- No behavioral changes to any model
- `tool.py` must still define the stub `AbstractToolkit` and `tool_schema` for now (removed in TASK-449)

### References in Codebase
- `packages/ai-parrot/src/parrot/tools/working_memory/tool.py` — source of models

---

## Acceptance Criteria

- [ ] `models.py` contains all 3 enums and 10 Pydantic models
- [ ] `tool.py` imports all models from `.models`
- [ ] No duplicate definitions between `models.py` and `tool.py`
- [ ] `python -c "from parrot.tools.working_memory.models import OperationType, FilterSpec"` works
- [ ] All existing tests still pass

---

## Test Specification

```python
# Quick validation
from parrot.tools.working_memory.models import (
    OperationType, JoinHow, AggFunc,
    FilterSpec, JoinOnSpec, OperationSpecInput,
    StoreInput, DropStoredInput, GetStoredInput, ListStoredInput,
    ComputeAndStoreInput, MergeStoredInput, SummarizeStoredInput,
    ImportFromToolInput, ListToolDataFramesInput,
)

assert OperationType.FILTER == "filter"
assert FilterSpec(column="x", op="==", value=1).column == "x"
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-447-extract-models.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-03-26
**Notes**: Created models.py with all 3 enums (OperationType, JoinHow, AggFunc) and 10 Pydantic models. Updated tool.py to import from .models while keeping stubs for TASK-449.

**Deviations from spec**: none
