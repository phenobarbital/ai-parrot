# TASK-396: Bot DB Modules Lazy Imports

**Feature**: runtime-dependency-reduction
**Spec**: `sdd/specs/runtime-dependency-reduction.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-386, TASK-387
**Assigned-to**: unassigned

---

## Context

Several bot modules in `parrot/bots/` import `querysource` at module level for database-backed bot functionality. Since querysource moved to the `[db]` extra, these must use lazy imports.

Implements: Spec Module 11 — Bot DB Modules Lazy Imports.

---

## Scope

- Convert top-level `querysource` imports to `lazy_import()` in:
  - `parrot/bots/db/cache.py`
  - `parrot/bots/database/sql.py`
  - `parrot/bots/product.py`
  - `parrot/bots/data.py`
- Use `lazy_import("querysource", extra="db")`.
- Use `TYPE_CHECKING` for type annotations.

**NOT in scope**: Handler/interface files (TASK-390). Tool files (TASK-389).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/bots/db/cache.py` | MODIFY | Lazy-import querysource |
| `parrot/bots/database/sql.py` | MODIFY | Lazy-import querysource |
| `parrot/bots/product.py` | MODIFY | Lazy-import querysource |
| `parrot/bots/data.py` | MODIFY | Lazy-import querysource |

---

## Implementation Notes

### Pattern to Follow
```python
from __future__ import annotations
from typing import TYPE_CHECKING
from parrot._imports import lazy_import

if TYPE_CHECKING:
    from querysource import QS

class DataBot:
    def query(self, sql: str):
        qs = lazy_import("querysource", extra="db")
        return qs.QS(sql)
```

### Key Constraints
- Core bot imports (`from parrot.bots import Chatbot, Agent`) must work without querysource
- Only the DB-specific bot subclasses need querysource at runtime
- Preserve all existing functionality

---

## Acceptance Criteria

- [ ] All listed files importable without querysource installed
- [ ] `from parrot.bots import Chatbot, Agent` works without querysource
- [ ] DB-backed bot functionality works when querysource is installed
- [ ] Missing dep raises: `pip install ai-parrot[db]`
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
7. **Move this file** to `tasks/completed/TASK-396-bot-db-lazy-imports.md`
8. **Update index** → `"done"`

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-03-22
**Notes**: Converted querysource imports in cache.py, sql.py, product.py to use lazy_import(). data.py already had querysource only in TYPE_CHECKING block with `from __future__ import annotations` — no runtime imports to convert, no changes needed.

**Deviations from spec**: none
