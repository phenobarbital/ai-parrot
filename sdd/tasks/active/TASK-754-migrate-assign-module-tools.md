# TASK-754: Migrate `assign_module_to_client` + `assign_module_to_group`

**Feature**: FEAT-107 — NavigatorToolkit Method Migration to PostgresToolkit CRUD
**Spec**: `sdd/specs/navigator-toolkit-method-migration.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-748
**Assigned-to**: unassigned

---

## Context

Implements **Module 7** of the spec. Both methods already have true
UPSERT semantics (`ON CONFLICT … DO UPDATE SET active = EXCLUDED.active`
— the exact case Q1 reserves for `upsert_row`). Single-table writes, no
transaction needed.

---

## Scope

- Rewrite `assign_module_to_client` (toolkit.py:1536) body to use
  `self.upsert_row("navigator.client_modules", data={…},
  conflict_cols=["client_id","program_id","module_id"],
  update_cols=["active"])`.
- Rewrite `assign_module_to_group` (toolkit.py:1551) body to use
  `self.upsert_row("navigator.modules_groups", data={…},
  conflict_cols=["group_id","module_id","client_id","program_id"],
  update_cols=["active"])`.
- `confirm_execution=False` branch unchanged in both.
- No transaction wrapper (single-table write each).

**NOT in scope**: any other assignment/write tool, authorization
helpers, schema changes.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/navigator/toolkit.py` | MODIFY | Rewrite both method bodies |
| `packages/ai-parrot-tools/tests/unit/test_navigator_assign_module.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.database.toolkits.postgres import PostgresToolkit
# verified: packages/ai-parrot/src/parrot/bots/database/toolkits/postgres.py:28
```

### Existing Signatures to Use
```python
async def upsert_row(self, table, data,
    conflict_cols=None, update_cols=None, returning=None, conn=None): ...  # postgres.py:406
async def assign_module_to_client(...) -> Dict[str, Any]: ...              # toolkit.py:1536
async def assign_module_to_group(...) -> Dict[str, Any]: ...               # toolkit.py:1551
```

### Does NOT Exist
- ~~Combined `assign_module` that takes client OR group~~ — two separate tools.
- ~~`upsert_row(conflict_cols="group_id")`~~ — must be a list, even for single-column PK.

---

## Implementation Notes

### Pattern
```python
if not confirm_execution:
    return {"status": "confirm_execution", "plan": {...}}

row = await self.upsert_row(
    "navigator.client_modules",
    data={"client_id": cid, "program_id": pid,
          "module_id": mid, "active": True},
    conflict_cols=["client_id", "program_id", "module_id"],
    update_cols=["active"],
)
return {"status": "success", "result": row, "metadata": {...}}
```

---

## Acceptance Criteria

- [ ] `assign_module_to_client`: `upsert_row` called with
      `conflict_cols=["client_id","program_id","module_id"]`, `update_cols=["active"]`.
- [ ] `assign_module_to_group`: `upsert_row` called with
      `conflict_cols=["group_id","module_id","client_id","program_id"]`, `update_cols=["active"]`.
- [ ] Neither method opens a transaction (single-table writes).
- [ ] `confirm_execution=False` branch unchanged in both.
- [ ] `get_tools()` snapshot still green.
- [ ] `pytest packages/ai-parrot-tools/tests/unit/test_navigator_assign_module.py -v` passes.

---

## Test Specification

Required (spec §4):
- `test_assign_module_to_client_upsert_semantics`
- `test_assign_module_to_group_upsert_semantics`

---

## Agent Instructions

Standard. Smallest migration in the feature — good warm-up if running
in parallel with Module 4/5/6, except policy says sequential-in-worktree.
