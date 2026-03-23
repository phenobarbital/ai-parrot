# TASK-390: Handler/Interface Lazy Imports

**Feature**: runtime-dependency-reduction
**Spec**: `sdd/specs/runtime-dependency-reduction.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-386, TASK-387
**Assigned-to**: unassigned

---

## Context

Handlers, interfaces, and store modules import `asyncdb` and `querysource` at module level. Since `querysource` moved to the `[db]` extra, these files need lazy imports so the handler framework remains importable without DB extras. Note that `asyncdb[default]` is still in core.

Implements: Spec Module 5 — Handler/Interface Lazy Imports.

---

## Scope

- Convert top-level `querysource` imports to `lazy_import()` in:
  - `parrot/handlers/bots.py`
  - `parrot/handlers/agents/abstract.py`
  - `parrot/handlers/chat.py`
  - `parrot/interfaces/hierarchy.py`
  - `parrot/interfaces/database.py`
  - `parrot/interfaces/documentdb.py`
  - `parrot/stores/kb/user.py`
  - `parrot/stores/arango.py`
- Use `lazy_import("querysource", extra="db")` pattern.
- For asyncdb submodules that require non-default extras (e.g., bigquery, arango), use lazy imports too.
- Use `TYPE_CHECKING` blocks for type annotations referencing these modules.

**NOT in scope**: Tool files (TASK-389). Bot DB modules (TASK-396).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/handlers/bots.py` | MODIFY | Lazy-import querysource/asyncdb extras |
| `parrot/handlers/agents/abstract.py` | MODIFY | Lazy-import querysource/asyncdb extras |
| `parrot/handlers/chat.py` | MODIFY | Lazy-import querysource/asyncdb extras |
| `parrot/interfaces/hierarchy.py` | MODIFY | Lazy-import querysource |
| `parrot/interfaces/database.py` | MODIFY | Lazy-import querysource |
| `parrot/interfaces/documentdb.py` | MODIFY | Lazy-import querysource |
| `parrot/stores/kb/user.py` | MODIFY | Lazy-import querysource |
| `parrot/stores/arango.py` | MODIFY | Lazy-import python-arango-async |

---

## Implementation Notes

### Pattern to Follow
```python
from __future__ import annotations
from typing import TYPE_CHECKING
from parrot._imports import lazy_import

if TYPE_CHECKING:
    from querysource import QS

class SomeHandler:
    async def setup_db(self):
        qs = lazy_import("querysource", extra="db")
        self.conn = qs.QS(...)
```

### Key Constraints
- Handlers are imported at app startup — must not crash without DB extras
- `asyncdb[default]` is in core, only querysource and advanced extras need lazy import
- `parrot/stores/arango.py` — python-arango-async moves to `[arango]` extra

### References in Codebase
- `parrot/handlers/bots.py` — heavy asyncdb usage
- `parrot/interfaces/database.py` — querysource + asyncdb

---

## Acceptance Criteria

- [ ] All listed files importable without `querysource` installed
- [ ] `parrot/stores/arango.py` importable without `python-arango-async`
- [ ] All handler/interface functionality works when deps are installed
- [ ] Missing deps raise clear error with `pip install ai-parrot[db]` or `ai-parrot[arango]`
- [ ] All existing tests pass with deps installed

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-386 and TASK-387 are completed
3. **Update status** in `tasks/.index.json` → `"in-progress"`
4. **Read each file** before modifying
5. **Implement** following the scope and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-390-handlers-lazy-imports.md`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none | describe if any
