# TASK-751: Migrate `create_dashboard` to CRUD primitives

**Feature**: FEAT-107 — NavigatorToolkit Method Migration to PostgresToolkit CRUD
**Spec**: `sdd/specs/navigator-toolkit-method-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-748
**Assigned-to**: unassigned

---

## Context

Implements **Module 4** of the spec. `create_dashboard` is a 20-column
INSERT with five `::text::jsonb` casts and one `$N::text::jsonb` for
`attributes`/`filtering_show`/`conditions`/`cond_definition`/`params`.
Migrating it removes the hand-written cast template — the dynamic
Pydantic model + `_prepare_args` + `_json_cols_for` handle it.

---

## Scope

Rewrite `create_dashboard` (toolkit.py:1088):

- Wrap body in `async with self.transaction() as tx:` (single INSERT
  today, but structure matches for future cascading assignments).
- Idempotency lookup at line 1135 → `self.select_rows(...)`.
- Main INSERT at line 1157 (20-column, multiple `::text::jsonb`) →
  `self.insert_row("navigator.dashboards", data={…},
  returning=[<same columns as today>], conn=tx)`.
- **Remove** the hand-written `$15::text::jsonb, $16::text::jsonb,
  $17::text::jsonb, $18, $19::text::jsonb, $20::text::jsonb` template
  fragments — pass plain Python dicts for JSON columns.
- `confirm_execution=False` branch unchanged (lines 1126-1131).

**NOT in scope**: `update_dashboard` (already uses `update_row` via
`_nav_build_update`), `clone_dashboard`, `get_dashboard`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/navigator/toolkit.py` | MODIFY | Rewrite `create_dashboard` body |
| `packages/ai-parrot-tools/tests/unit/test_navigator_create_dashboard.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.database.toolkits.postgres import PostgresToolkit
# verified: packages/ai-parrot/src/parrot/bots/database/toolkits/postgres.py:28
```

### Existing Signatures to Use
```python
async def insert_row(self, table, data, returning=None, conn=None): ...   # postgres.py:361
async def select_rows(...): ...                                           # postgres.py:609
async def transaction(self): ...                                          # postgres.py:697
async def create_dashboard(...) -> Dict[str, Any]: ...                    # toolkit.py:1088
async def _check_write_access(self, program_id: int) -> None: ...         # toolkit.py:593
```

### Does NOT Exist
- ~~`self._jsonb(value)` before `insert_row`~~ — parent's `_prepare_args`
  + `_json_cols_for` handles `::text::jsonb` automatically.
- ~~Hand-rolled cast template~~ — removed at the end of this task.

---

## Implementation Notes

### Pattern
```python
if not confirm_execution:
    return {"status": "confirm_execution", "plan": {...}}

async with self.transaction() as tx:
    row = await self.insert_row(
        "navigator.dashboards",
        data={
            "dashboard_id": dashboard_id,
            "dashboard_name": dashboard_name,
            "program_id": program_id,
            "module_id": module_id,
            "attributes": attributes,        # plain dict — parent handles JSON
            "filtering_show": filtering_show,
            "conditions": conditions,
            "cond_definition": cond_definition,
            "params": params,
            # ... remaining columns ...
        },
        returning=[...],   # same RETURNING list as the old SQL
        conn=tx,
    )

return {"status": "success", "result": row, "metadata": {...}}
```

### Key Constraints
- JSON columns (`attributes`, `filtering_show`, `conditions`,
  `cond_definition`, `params`) pass as plain `dict[str, Any]`. No manual
  JSON encoding. No `$N::text::jsonb` in any string.
- `confirm_execution=False` branch stays before the transaction.

---

## Acceptance Criteria

- [ ] `create_dashboard(confirm_execution=False)` returns plan dict identical to baseline.
- [ ] `insert_row("navigator.dashboards", …)` called once with all 20 columns in `data={…}`.
- [ ] JSON columns in `data` are plain dicts; no `self._jsonb(...)` call remains.
- [ ] RETURNING clause contract preserved (same columns returned as before).
- [ ] `transaction()` entered exactly once.
- [ ] `get_tools()` snapshot still green.
- [ ] `pytest packages/ai-parrot-tools/tests/unit/test_navigator_create_dashboard.py -v` passes.

---

## Test Specification

Required (spec §4):
- `test_create_dashboard_insert_row_payload_shape` — 20-column data dict,
  JSON keys are plain dicts.
- `test_create_dashboard_confirm_execution_false_returns_plan_dict` (inherited from TASK-748 coverage).

---

## Agent Instructions

Standard. Diff the new body against the old RETURNING clause carefully —
downstream clients parse returned keys by name.
