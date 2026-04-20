# TASK-749: Migrate `create_program` to CRUD primitives

**Feature**: FEAT-107 — NavigatorToolkit Method Migration to PostgresToolkit CRUD
**Spec**: `sdd/specs/navigator-toolkit-method-migration.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-748
**Assigned-to**: unassigned

---

## Context

Implements **Module 2** of the spec. `create_program` is the most
complex write flow: it touches `auth.programs`, `auth.program_clients`,
`auth.program_groups`, `navigator.client_modules`, and
`navigator.modules_groups` — currently through five different raw
`_nav_execute` call sites with no surrounding transaction. Migrating
it proves the pattern (insert_row + upsert_row + execute_query escape
hatches) that the rest of the feature follows.

---

## Scope

Rewrite `create_program` (toolkit.py:657) body:

- Wrap the entire DB-writing body in `async with self.transaction() as tx:`
  and thread `conn=tx` through every CRUD call inside.
- Keep the `confirm_execution=False` branch **before** the transaction
  block. Plan-dict shape unchanged.
- Main `INSERT INTO auth.programs … RETURNING …` (line 759) →
  `self.insert_row("auth.programs", data={…}, returning=["program_id","program_slug"], conn=tx)`.
- Idempotency lookup (line 704) → `self.select_rows("auth.programs",
  where={"program_slug": …}, columns=["program_id","program_slug"], limit=1)`.
- Cascaded module-list fetch (line 712) → `self.select_rows("navigator.modules",
  where={"program_id": pid}, columns=["module_id"])`.
- `INSERT INTO auth.program_clients … ON CONFLICT DO NOTHING`
  (lines 720-724, 773-777) → **stays on `self.execute_query(sql, …, conn=tx)`**
  (Q1 — `upsert_row` reserved for true UPSERTs).
- `INSERT INTO navigator.client_modules … ON CONFLICT … DO UPDATE SET
  active = EXCLUDED.active` (lines 726-730) → `self.upsert_row(...,
  conflict_cols=["client_id","program_id","module_id"],
  update_cols=["active"], conn=tx)`.
- `INSERT INTO auth.program_groups … gprogram_id subquery … ON CONFLICT
  DO NOTHING` (lines 733-738, 779-784) → **stays on `self.execute_query(sql,
  …, conn=tx)`** — scalar subquery cannot be expressed via `upsert_row.data`
  (Q1 + documented exception).
- `INSERT INTO navigator.modules_groups … ON CONFLICT … DO UPDATE SET
  active = EXCLUDED.active` (lines 741-745) → `self.upsert_row(...,
  update_cols=["active"], conn=tx)`.
- `setval(pg_get_serial_sequence('auth.programs', 'program_id'), …)` at
  line 754 → **keep** as `self.execute_query(…)` (Q3 — defensive sequence
  repair).
- `SELECT client_id, client_slug FROM auth.clients WHERE client_id =
  ANY($1::int[])` (line 689) → **stays on `self.execute_query`** (no
  equality-filter on a list via `select_rows`; document why).

**NOT in scope**: `create_module`, `create_dashboard`, any other write
tool. Authorization helpers (`_check_program_access`, etc.) untouched.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-tools/src/parrot_tools/navigator/toolkit.py` | MODIFY | Rewrite `create_program` body (method at line 657) |
| `packages/ai-parrot-tools/tests/unit/test_navigator_create_program.py` | CREATE | Unit tests for migrated method |

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
async def insert_row(self, table, data, returning=None, conn=None): ...     # 361
async def upsert_row(self, table, data,
    conflict_cols=None, update_cols=None, returning=None, conn=None): ...   # 406
async def select_rows(self, table, where=None, columns=None,
    order_by=None, limit=None, conn=None,
    distinct=False, column_casts=None): ...                                 # 609 (post-TASK-747)
@asynccontextmanager
async def transaction(self): ...                                            # 697

# packages/ai-parrot-tools/src/parrot_tools/navigator/toolkit.py
class NavigatorToolkit(PostgresToolkit):
    _NAVIGATOR_TABLES: List[str] = [...]                                    # lines 59-73
    async def _check_write_access(self, program_id: int) -> None: ...       # 593
    async def _resolve_client_ids(self, ...) -> List[int]: ...              # 263
    async def create_program(...) -> Dict[str, Any]: ...                    # 657 — body rewritten
```

### Does NOT Exist
- ~~`upsert_row(conflict_action="nothing")`~~ — not a kwarg. `DO NOTHING` stays on `execute_query`.
- ~~`transaction()` nested entry~~ — raises `RuntimeError` (postgres.py:716-720).
- ~~`select_rows(where={"client_id": [1,2,3]})`~~ — equality-only. Use `execute_query` for `= ANY(...)`.
- ~~`self._jsonb(value)` before `insert_row`~~ — parent's `_prepare_args`
  handles `$N::text::jsonb` automatically. Pass plain dicts.

---

## Implementation Notes

### Pattern (from spec §2)
```python
async def create_program(self, ..., confirm_execution: bool = False):
    await self._check_write_access(...)
    # … validation, lookups via select_rows …

    if not confirm_execution:
        return {"status": "confirm_execution", "plan": {...}}

    async with self.transaction() as tx:
        row = await self.insert_row(
            "auth.programs",
            data={...},
            returning=["program_id", "program_slug"],
            conn=tx,
        )
        pid = row["program_id"]

        for cid in client_ids:
            await self.execute_query(
                "INSERT INTO auth.program_clients (...) "
                "VALUES ($1,$2,$3,$4,true) ON CONFLICT DO NOTHING",
                [pid, cid, program_slug, client_slugs_map.get(cid, program_slug)],
                conn=tx,
            )
            for mid in module_ids:
                await self.upsert_row(
                    "navigator.client_modules",
                    data={"client_id": cid, "program_id": pid,
                          "module_id": mid, "active": True},
                    conflict_cols=["client_id", "program_id", "module_id"],
                    update_cols=["active"],
                    conn=tx,
                )
        # ... program_groups DO NOTHING via execute_query, modules_groups via upsert_row ...

    return {"status": "success", "result": {...}, "metadata": {...}}
```

### Key Constraints
- `confirm_execution=False` branch **outside** the `transaction()` block.
- Plan dict built from templated SQL via `_get_or_build_template`, not
  hand-concatenated strings.
- Thread `conn=tx` through **every** CRUD call inside the `async with`.
  Omitting it silently breaks atomicity.
- Return dict shape unchanged (`{"status", "result", "metadata"}`).

---

## Acceptance Criteria

- [ ] `create_program(confirm_execution=False)` still returns `{"status":
      "confirm_execution", …}` — identical keys/values to baseline (TASK-748 snapshot).
- [ ] `create_program(confirm_execution=True)` opens exactly one `transaction()`.
- [ ] `insert_row` called once for `auth.programs` with `returning=["program_id","program_slug"]`.
- [ ] `upsert_row` called for `navigator.client_modules` and
      `navigator.modules_groups` with `update_cols=["active"]`.
- [ ] `execute_query` retained for `auth.program_clients` (DO NOTHING),
      `auth.program_groups` (DO NOTHING + gprogram_id subquery),
      `auth.clients … = ANY($1::int[])`, and the `setval` sequence repair.
- [ ] Idempotency re-run with same `program_slug` returns
      `already_existed=True` with existing `program_id`.
- [ ] `get_tools()` snapshot from TASK-748 still matches byte-for-byte.
- [ ] No call to `_nav_execute` / `_nav_run_one` / `_nav_run_query` in
      `create_program` body.
- [ ] `pytest packages/ai-parrot-tools/tests/unit/test_navigator_create_program.py -v` passes.
- [ ] `pytest packages/ai-parrot-tools/tests/unit/test_navigator_toolkit_baseline.py -v` still passes.

---

## Test Specification

Tests required (see spec §4):
- `test_create_program_uses_transaction`
- `test_create_program_calls_upsert_row_for_program_clients` — NOTE: spec
  table says `upsert_row`, but per Q1 `program_clients` stays on
  `execute_query`. Test should assert `execute_query` with the right SQL
  snippet and `conn=tx`.
- `test_create_program_calls_upsert_row_for_modules_groups` — `update_cols=["active"]`.
- `test_create_program_idempotent_returns_existing_id`.
- `test_create_program_gprogram_id_falls_back_to_execute_query`.

---

## Agent Instructions

Standard workflow. Re-read spec §2, §6, §8 (Q1/Q3) before coding. Keep
authorization helper calls byte-identical. If a test reveals a
`program_clients` upsert expectation that conflicts with Q1, trust Q1
and adjust the test.
