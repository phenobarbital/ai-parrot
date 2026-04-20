# TASK-750: Migrate `create_module` to CRUD primitives

**Feature**: FEAT-107 — NavigatorToolkit Method Migration to PostgresToolkit CRUD
**Spec**: `sdd/specs/navigator-toolkit-method-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-749
**Assigned-to**: unassigned

---

## Context

Implements **Module 3** of the spec. `create_module` mirrors
`create_program`'s cascading-insert pattern across `navigator.modules`,
`navigator.client_modules`, `navigator.modules_groups`, and the
`auth.program_clients` / `auth.program_groups` membership tables. Runs
sequentially in the same worktree after TASK-749.

---

## Scope

Rewrite `create_module` (toolkit.py:850) body:

- Wrap body in `async with self.transaction() as tx:`.
- `INSERT INTO navigator.modules … RETURNING module_id` → `insert_row("navigator.modules", …, returning=["module_id"], conn=tx)`.
- Idempotency lookup (line 924) → `select_rows`.
- `SELECT program_slug FROM auth.programs WHERE program_id = $1` (line 880) → `select_rows`.
- `SELECT client_slug FROM auth.clients …` (line 903) → `select_rows` (scalar equality filter only — `ANY(...)` cases stay raw).
- Existing-assignments writes (lines 933-952, 984-1003):
  - `navigator.client_modules`, `navigator.modules_groups` (DO UPDATE SET active = EXCLUDED.active) → `upsert_row(update_cols=["active"], conn=tx)`.
  - `auth.program_clients`, `auth.program_groups` (DO NOTHING) → stay on `execute_query(sql, …, conn=tx)` per Q1.
- **Preserve** the Home-module slug convention, `{program_slug}_{slug}`
  prefix rule, and `description = description or module_name.title()`
  fallback — business rules that live **above** the DB write.
- `confirm_execution=False` branch unchanged.

**NOT in scope**: `update_module` (already uses `update_row` via
`_nav_build_update`), `create_dashboard`, any read tool.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/navigator/toolkit.py` | MODIFY | Rewrite `create_module` body (method at line 850) |
| `packages/ai-parrot-tools/tests/unit/test_navigator_create_module.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.database.toolkits.postgres import PostgresToolkit
# verified: packages/ai-parrot/src/parrot/bots/database/toolkits/postgres.py:28
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/bots/database/toolkits/postgres.py
async def insert_row(self, table, data, returning=None, conn=None): ...   # 361
async def upsert_row(self, table, data,
    conflict_cols=None, update_cols=None, returning=None, conn=None): ... # 406
async def select_rows(self, table, where=None, columns=None,
    order_by=None, limit=None, conn=None, distinct=False,
    column_casts=None): ...                                               # 609
@asynccontextmanager
async def transaction(self): ...                                          # 697

# packages/ai-parrot-tools/src/parrot_tools/navigator/toolkit.py
async def _check_write_access(self, program_id: int) -> None: ...         # 593
async def _resolve_program_id(self, ...) -> int: ...                      # 211
async def create_module(...) -> Dict[str, Any]: ...                       # 850
```

### Does NOT Exist
- ~~`select_rows(where={"client_id": [...]})`~~ — equality-only.
- ~~`upsert_row` for `DO NOTHING` semantic~~ — stays on `execute_query` (Q1).

---

## Implementation Notes

### Business-Rule Preservation
Do NOT touch this preamble (exact lines vary; preserve logic):
```python
if module_name.lower() == "home":
    module_slug = program_slug
    classname = program_slug
else:
    if not slug.startswith(program_slug + "_"):
        module_slug = f"{program_slug}_{slug}"
    ...
description = description or module_name.title()
```

### Pattern
Same as TASK-749. Confirm-plan branch outside `transaction()`. Thread
`conn=tx` through every CRUD call inside.

---

## Acceptance Criteria

- [ ] `create_module(confirm_execution=False)` returns plan dict identical to baseline.
- [ ] `create_module(confirm_execution=True)` opens exactly one `transaction()`.
- [ ] `insert_row("navigator.modules", …)` called once with `returning=["module_id"]`.
- [ ] `upsert_row` used for `navigator.client_modules` and `navigator.modules_groups` (`update_cols=["active"]`).
- [ ] `execute_query` retained for `auth.program_clients` / `auth.program_groups` (DO NOTHING) with `conn=tx`.
- [ ] Home-module slug convention preserved (tested against `insert_row` data dict).
- [ ] `{program_slug}_{slug}` prefix rule preserved.
- [ ] `get_tools()` snapshot still green.
- [ ] `pytest packages/ai-parrot-tools/tests/unit/test_navigator_create_module.py -v` passes.

---

## Test Specification

Required (spec §4):
- `test_create_module_uses_transaction`
- `test_create_module_home_slug_convention_preserved`
- `test_create_module_prefix_rule_preserved`

---

## Agent Instructions

Standard. Re-read spec §2 and §3 Module 3 before coding. Run
TASK-748's baseline tests after rewrite to confirm no tool-surface drift.
