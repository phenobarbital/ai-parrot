# TASK-752: Migrate `clone_dashboard` to CRUD primitives

**Feature**: FEAT-107 — NavigatorToolkit Method Migration to PostgresToolkit CRUD
**Spec**: `sdd/specs/navigator-toolkit-method-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-751
**Assigned-to**: unassigned

---

## Context

Implements **Module 5** of the spec. `clone_dashboard` fans out: fetch
source dashboard → insert new dashboard → loop of widget inserts that
reference the new dashboard_id. Today it runs without a transaction —
a partial failure leaves orphan widgets. Migration wraps the fan-out in
`transaction()` so rollback is atomic.

---

## Scope

Rewrite `clone_dashboard` (toolkit.py:1244):

- Source-dashboard fetch (line 1265) → `self.select_rows("navigator.dashboards",
  where={"dashboard_id": source_id}, limit=1)`.
- Keep `_check_write_access(target_program_id)` (line 1263) and source
  access check (line 1270) byte-identical.
- Wrap the fan-out in `async with self.transaction() as tx:`:
  - New dashboard INSERT (line 1282) → `insert_row("navigator.dashboards",
    data={…}, returning=[…], conn=tx)`.
  - Widget fan-out loop (line 1298) → loop of `insert_row("navigator.widgets",
    data={…}, conn=tx)`.
- `confirm_execution=False` branch unchanged (lines 1274-1279).

**NOT in scope**: `create_dashboard`, `create_widget`, any widget
validation logic.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/navigator/toolkit.py` | MODIFY | Rewrite `clone_dashboard` body |
| `packages/ai-parrot-tools/tests/unit/test_navigator_clone_dashboard.py` | CREATE | Unit tests including rollback simulation |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.database.toolkits.postgres import PostgresToolkit
# verified: packages/ai-parrot/src/parrot/bots/database/toolkits/postgres.py:28
```

### Existing Signatures to Use
```python
async def insert_row(self, table, data, returning=None, conn=None): ...    # postgres.py:361
async def select_rows(...): ...                                            # postgres.py:609
async def transaction(self): ...                                           # postgres.py:697
async def clone_dashboard(...) -> Dict[str, Any]: ...                      # toolkit.py:1244
async def _check_write_access(self, program_id: int) -> None: ...          # toolkit.py:593
async def _check_dashboard_access(self, dashboard_id: str) -> None: ...    # toolkit.py:540
```

### Does NOT Exist
- ~~`bulk_insert` for widget fan-out~~ — not implemented. Use a loop of
  `insert_row(conn=tx)` inside `transaction()`.
- ~~`execute_many`~~ — not a public method.

---

## Implementation Notes

### Rollback Guarantee
Every `insert_row` inside the `async with self.transaction() as tx:` block
MUST pass `conn=tx`. An omitted `conn=tx` acquires a fresh pool
connection and silently breaks atomicity.

### Pattern
```python
async with self.transaction() as tx:
    new_row = await self.insert_row(
        "navigator.dashboards", data={...},
        returning=[...], conn=tx,
    )
    new_did = new_row["dashboard_id"]
    for w in source_widgets:
        await self.insert_row(
            "navigator.widgets",
            data={..., "dashboard_id": new_did, ...},
            conn=tx,
        )
```

---

## Acceptance Criteria

- [ ] `clone_dashboard(confirm_execution=False)` returns plan dict identical to baseline.
- [ ] `clone_dashboard(confirm_execution=True)` opens exactly one `transaction()`.
- [ ] Simulated failure on the Nth widget insert rolls back ALL prior writes (dashboard + preceding widgets).
- [ ] `_check_write_access` and `_check_dashboard_access` still called with original arguments.
- [ ] `get_tools()` snapshot still green.
- [ ] `pytest packages/ai-parrot-tools/tests/unit/test_navigator_clone_dashboard.py -v` passes.

---

## Test Specification

Required (spec §4):
- `test_clone_dashboard_atomic_rollback` — monkey-patch `insert_row` to
  raise on the 2nd widget; assert no dashboard row persists (mocked
  transaction records `__aexit__(exc_type!=None)`).

---

## Agent Instructions

Standard. The atomic-rollback test is the load-bearing regression
guard here — run it after every keystroke-level change.
