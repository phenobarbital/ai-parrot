# TASK-228: Database Tools — Package Exports (`__init__.py`)

**Feature**: Database Schema Tools — Completion & Hardening (FEAT-032)
**Spec**: `sdd/specs/tools-database.spec.md`
**Status**: done
**Priority**: high
**Estimated effort**: S (< 1h)
**Depends-on**: none
**Assigned-to**: claude-sonnet-4-6

---

## Context

> `parrot/tools/database/__init__.py` is a single blank line.  Neither `PgSchemaSearchTool` nor
> `BQSchemaSearchTool` is importable from the sub-package, making the tools invisible to agent
> crews and MCP toolkits that discover tools via `parrot.tools.database`.

---

## Scope

Replace the empty `parrot/tools/database/__init__.py` with proper exports:

```python
from .pg import PgSchemaSearchTool
from .bq import BQSchemaSearchTool

__all__ = [
    "PgSchemaSearchTool",
    "BQSchemaSearchTool",
]
```

**NOT in scope**: Any changes to `pg.py`, `bq.py`, `abstract.py`, or `cache.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/tools/database/__init__.py` | MODIFY | Add exports for both tool classes |

---

## Implementation Notes

- Read the file first before editing.
- Confirm imports resolve correctly: `PgSchemaSearchTool` is in `pg.py`, `BQSchemaSearchTool`
  is in `bq.py`.
- No `__init__.py` for `tests/tools/database/` is needed in this task (handled by TASK-232).

---

## Acceptance Criteria

- [ ] `from parrot.tools.database import PgSchemaSearchTool` succeeds without ImportError
- [ ] `from parrot.tools.database import BQSchemaSearchTool` succeeds without ImportError
- [ ] `parrot/tools/database/__all__` contains both class names
- [ ] `ruff check parrot/tools/database/__init__.py` passes

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/tools-database.spec.md` for full context
2. **Update status** in `sdd/tasks/.index.json` → `"in-progress"` with your session ID
3. **Read** `parrot/tools/database/__init__.py` (currently 1 line)
4. **Implement** the exports as described above
5. **Verify** by running:
   ```bash
   source .venv/bin/activate
   python -c "from parrot.tools.database import PgSchemaSearchTool, BQSchemaSearchTool; print('OK')"
   ruff check parrot/tools/database/__init__.py
   ```
6. **Move this file** to `sdd/tasks/completed/TASK-228-database-tools-package-exports.md`
7. **Update index** → `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-sonnet-4-6
**Date**: 2026-03-08
**Notes**:
- Replaced the single blank line in `parrot/tools/database/__init__.py` with exports for
  `PgSchemaSearchTool` and `BQSchemaSearchTool` plus an `__all__` list.
- `python -c "from parrot.tools.database import PgSchemaSearchTool, BQSchemaSearchTool"` → OK.
- `ruff check parrot/tools/database/__init__.py` → All checks passed.

**Deviations from spec**: None.
