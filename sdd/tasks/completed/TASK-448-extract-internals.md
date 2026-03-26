# TASK-448: Extract internal classes to internals.py

**Feature**: refactor-workingmemorytoolkit
**Spec**: `sdd/specs/refactor-workingmemorytoolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-447
**Assigned-to**: unassigned

---

## Context

Per the spec (Module 2), the internal engine classes must be extracted from `tool.py` into `internals.py`, with underscore prefixes removed from class names. These classes handle catalog storage, operation execution, and shape limiting.

---

## Scope

- Move the following classes from `tool.py` to `internals.py`, renaming as indicated:
  - `_CatalogEntry` → `CatalogEntry`
  - `_OperationExecutor` → `OperationExecutor`
  - `_ShapeLimit` → `ShapeLimit`
  - `_WorkingMemoryCatalog` → `WorkingMemoryCatalog`
- Add `self.logger = logging.getLogger(__name__)` to `WorkingMemoryCatalog.__init__` (per open question resolution: use `self.logger`)
- Replace `logger.info(...)` / `logger.warning(...)` calls in `WorkingMemoryCatalog` with `self.logger.info(...)` / `self.logger.warning(...)`
- Import models from `.models` (not from `tool.py`)
- Add Google-style docstrings to all classes
- Update `tool.py` to import from `.internals`
- Update all internal references: `_OperationExecutor._AGG_MAP` → `OperationExecutor.AGG_MAP` (in `summarize_stored`)

**NOT in scope**: Changing `__init__.py`, test relocation, replacing framework stubs.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/working_memory/internals.py` | REWRITE | Populate with catalog, executor, shape limit classes |
| `packages/ai-parrot/src/parrot/tools/working_memory/tool.py` | MODIFY | Remove internal classes, import from `.internals`, update references |

---

## Implementation Notes

### Rename Map

| Old Name | New Name | Notes |
|---|---|---|
| `_CatalogEntry` | `CatalogEntry` | Dataclass, no behavioral change |
| `_OperationExecutor` | `OperationExecutor` | Also rename `_AGG_MAP` → `AGG_MAP` |
| `_ShapeLimit` | `ShapeLimit` | Dataclass |
| `_WorkingMemoryCatalog` | `WorkingMemoryCatalog` | Add `self.logger` |

### Key Constraints
- `WorkingMemoryToolkit` still uses `self._catalog` (private attribute on toolkit) — that underscore stays
- Tests reference `toolkit._catalog` — the attribute name on the toolkit doesn't change, only the class name changes
- `OperationExecutor.AGG_MAP` is referenced by `summarize_stored` in `tool.py` — update that reference

### References in Codebase
- `packages/ai-parrot/src/parrot/tools/working_memory/tool.py` — source of classes
- `packages/ai-parrot/src/parrot/tools/working_memory/models.py` — models to import

---

## Acceptance Criteria

- [ ] `internals.py` contains `CatalogEntry`, `OperationExecutor`, `ShapeLimit`, `WorkingMemoryCatalog`
- [ ] No underscore-prefixed class names in `internals.py`
- [ ] `WorkingMemoryCatalog` uses `self.logger` (not module-level `logger`)
- [ ] `tool.py` imports all internal classes from `.internals`
- [ ] No duplicate class definitions between `internals.py` and `tool.py`
- [ ] `python -c "from parrot.tools.working_memory.internals import CatalogEntry, OperationExecutor"` works
- [ ] All existing tests still pass

---

## Test Specification

```python
from parrot.tools.working_memory.internals import (
    CatalogEntry, OperationExecutor, ShapeLimit, WorkingMemoryCatalog,
)
import pandas as pd

catalog = WorkingMemoryCatalog(session_id="test")
assert hasattr(catalog, 'logger')
catalog.put("test", pd.DataFrame({"a": [1, 2, 3]}))
assert "test" in catalog
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `tasks/completed/TASK-448-extract-internals.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet)
**Date**: 2026-03-26
**Notes**: Created internals.py with CatalogEntry, OperationExecutor (AGG_MAP renamed from _AGG_MAP), ShapeLimit, WorkingMemoryCatalog (with self.logger). Updated tool.py to import from .internals and updated OperationExecutor.AGG_MAP reference in summarize_stored.

**Deviations from spec**: none
