# TASK-3928: StudioAgentRepository: partitioned CRUD, row lock + guard, one-statement snapshot

**Feature**: FEAT-621 — Agent Studio — Database-Backed Storage
**Spec**: `sdd/specs/agentstudio-db-storage.spec.md`
**Spec wave**: W1 — Repositories (M3, part 2: StudioAgentRepository)
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3925, TASK-3926
**Assigned-to**: unassigned

---

## Context

Spec §2.5 (`StudioAgentRepository`), §2.5a (row locking, write guard, runtime build snapshot, lock order),
§2.6 (`get_version` revalidation query), §3 Module 3 invariant: every statement carries
`tenant IS NOT DISTINCT FROM $n` or uses an `agent_id` obtained from `lock`/`insert`/`load_snapshot`.

---

## Scope

- `StudioAgentRepository(pool)` with `get`, `get_version`, `load_snapshot` (ONE statement: row + `json_agg` of
  assets + `json_agg` of tooling ordered by `(kind, position)`), `list(part, *, owner=None)`,
  `lock(conn, part, name, guard)`, `insert`, `update_definition`, `update_visibility`, `set_status`, `delete`
  (returns the deleted snapshot).
- `lock`: `SELECT agent_id, version, status … FOR UPDATE`; no row ⇒ `StudioNotFound`; expected_version mismatch ⇒
  `StudioVersionConflict`; authorized_version mismatch ⇒ `StudioStaleAuthorization` — in that order.
- `insert`: `StudioNameConflict` on either unique index (asyncdb re-raises `UniqueViolationError`).
- Row → record mapping helpers (`_agent_record`, `_snapshot`).

**NOT in scope**: Asset/tooling repositories (TASK-3929); drafts/catalogue (TASK-3930); services and the tooling policy (W2).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/studio/storage/repositories.py` | MODIFY | StudioAgentRepository + row mappers |
| `packages/ai-parrot-server/tests/studio/storage/test_agent_repository.py` | CREATE | real-PG repository tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified code references. Use these exact imports, names and signatures. Anything not listed:
> verify it exists (`grep`/`read`) before using it.

### Verified Imports
```python
from parrot.handlers.studio.storage.models import (StudioPartition, StudioAgentDefinition, StudioAgentRecord,
    StudioAgentHead, StudioAgentSnapshot, StudioAssetRecord, StudioToolingRecord, StudioWriteGuard,
    StudioNameConflict, StudioVersionConflict, StudioStaleAuthorization, StudioNotFound)   # TASK-3922
from parrot.handlers.studio.storage.repositories import studio_transaction, _exec, _fetch_all  # TASK-3925
from asyncpg.exceptions import UniqueViolationError   # re-raised by asyncdb pg.execute (spec §2.5a); in-repo precedent
                                                      # handlers/agents/users.py:703-705 (local import)
```

### Existing Signatures to Use
- Table DDL: `packages/ai-parrot-server/src/parrot/handlers/studio/storage/migrations/0002_ai_agents.sql` (TASK-3924) — columns, CHECKs, unique constraint
  `ai_agents_tenant_name_key`, partial index `ai_agents_global_name_uq`.
- asyncdb `pg.fetch_one` raises on error; `fetch_all` returns `None` for zero rows (use `_fetch_all`).

### Does NOT Exist
- ~~asyncdb `Model` classes for these tables~~ — raw SQL by decision (§2.4: `text[]`/Optional fields broke the model
  processor, TASK-2522).
- ~~`LISTEN/NOTIFY`~~ anywhere — not used.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/storage/repositories.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/storage/test_agent_repository.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": []
}
```

---

## Implementation Notes

- Parallelism: extends storage/repositories.py after TASK-3925 (studio_transaction/_exec); its tests use the studio_pool fixture from TASK-3926 (conftest.py, applied migrations); models from TASK-3922 arrive transitively
- Cross-feature ordering: none (X16 early subset). FEAT-605 W2.1 consumes this API once STORAGE W0+W1 merge.
- Lock order (§2.5a): draft row → agent row → child rows by `(kind, name)` → catalogue rows. This repository only
  ever locks the agent row; never lock a child before its parent.
- `load_snapshot` MUST be a single SQL statement (mutation in `test_snapshot_during_edit`, TASK-3942: three
  queries ⇒ RED). Use `COALESCE((SELECT json_agg(...) ...), '[]'::json)` sub-selects.
- `definition` jsonb ↔ `StudioAgentDefinition.model_validate`; `allowed_groups` text[] ↔ tuple.

### Common constraints (all FEAT-621 tasks)
- Contract verified against `dev` @ `32b1a45d4` (2026-09-30). Earlier FEAT-621 tasks shift line numbers:
  re-run every `grep -c` before editing and fix this file first if an anchor moved.
- Async throughout; the pool is the host's `app["database"]` (asyncdb `pg` pool); no sync driver, no second pool.
- Raw parametrised SQL (`$1…$n`), never value interpolation; schema literal `navigator`.
- Transactions only through `studio_transaction`; statements only through `_exec` (spec §2.5a).
- Pydantic for payloads, frozen dataclasses for records; `self.logger` in views,
  `logging.getLogger("Parrot.AgentStudio.Storage")` in storage/services/runtime.
- ARCHITECTURE Rule 4: functions ≤ 60 lines, cyclomatic complexity ≤ 10, modules ≤ 500 lines.
- **Database rule** (spec §4): integration tests read `TEST_STUDIO_PG_DSN` and `pytest.skip` with a reason when it is
  unset. Point it at a PostgreSQL ≥ 14 database dedicated to this worktree — the fixtures truncate `navigator.ai_*`.
- **Request/session rule** (spec §4, ARCHITECTURE R6): handler tests use `aiohttp_client` with the real session
  middleware or `make_mocked_request(..., app=app)` + `request["NAV_SESSION"] = SessionData(...)`; never a `Mock`
  with a hand-set `.session`. Each new assertion is mutation-checked (revert the guarded line ⇒ RED).
- Worktree tests: prefix with `PYTHONPATH=packages/ai-parrot/src:packages/ai-parrot-server/src` as needed;
  never `uv sync` inside a worktree.

---

## Implementation Blueprint

> Write each block to its declared path nearly verbatim, then complete every `# FILL IN:` marker. Never change a
> signature, class name or file path the blueprint fixes (they come from spec §2.4/§2.5/§3 skeletons).

### Steps (in order)
1. Add row mappers, then the read methods, then `lock`, then the writes — *why*: writes call `lock` first.
2. Write the integration tests (fixture `studio_pool`).

### `packages/ai-parrot-server/src/parrot/handlers/studio/storage/repositories.py` (MODIFY — append)
```python
_AGENT_COLS = ("agent_id, tenant, name, owner, visibility, allowed_groups, definition, status, version, "
               "created_at, updated_at")


class StudioAgentRepository:
    """Partitioned access to navigator.ai_agents (spec §2.5). Never encodes access policy."""

    def __init__(self, pool: Any) -> None:
        self.pool = pool

    async def get(self, part: StudioPartition, name: str) -> StudioAgentRecord | None:
        sql = (f"SELECT {_AGENT_COLS} FROM {NAVIGATOR_SCHEMA}.ai_agents "
               "WHERE tenant IS NOT DISTINCT FROM $1 AND name = $2")
        # FILL IN: acquire, fetch_one (None-safe), map with _agent_record.
        raise NotImplementedError

    async def lock(self, conn: Any, part: StudioPartition, name: str, guard: StudioWriteGuard) -> StudioAgentHead:
        """SELECT … FOR UPDATE, then NotFound → VersionConflict → StaleAuthorization (§2.5a order)."""
        # FILL IN — bounded by test_lock_guard_order.
        raise NotImplementedError

    async def load_snapshot(self, part: StudioPartition, name: str) -> StudioAgentSnapshot | None:
        """ONE statement: row + json_agg(assets incl. content) + json_agg(tooling ORDER BY kind, position)."""
        raise NotImplementedError
    # FILL IN: get_version, list, insert, update_definition, update_visibility, set_status, delete — signatures
    #   exactly as spec §2.5; every UPDATE/DELETE keyed by the agent_id returned from lock().
```
**Why this shape**: the predicate `tenant IS NOT DISTINCT FROM $1` makes `None` match only NULL rows (GLOBAL).

### `packages/ai-parrot-server/tests/studio/storage/test_agent_repository.py` (CREATE)
```python
"""FEAT-621 M3 — StudioAgentRepository on real Postgres (AC6, AC7, AC8)."""
# FILL IN: test_unique_per_tenant (acme/sales + beta/sales coexist; second acme/sales and two NULL sales →
#   StudioNameConflict); test_partition_isolation_agents (every method with partition beta on an acme agent →
#   None/False/[]); test_lock_guard_order; test_version_bumps_on_definition_update; test_delete_returns_snapshot;
#   test_load_snapshot_single_statement (spy on conn.fetch_one call count == 1).
```

### FILL IN checklist
- [ ] mappers; nine methods; error translation of `UniqueViolationError`.
- [ ] six tests.

---

## Acceptance Criteria

- [ ] `UNIQUE(tenant, name)` incl. tenant NULL enforced and surfaced as `StudioNameConflict` (`test_unique_per_tenant`, AC6).
- [ ] No method reads or writes an agent outside its partition (`test_partition_isolation_agents`, AC7).
- [ ] `lock` applies NotFound → VersionConflict → StaleAuthorization under `FOR UPDATE` (AC8 groundwork).
- [ ] `load_snapshot` is one SQL statement (AC5 groundwork).
- [ ] `ruff check` clean on every touched Python file; new functions within Rule-4 budgets (`flake8` complexity).

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/studio/storage/test_agent_repository.py -q`

---

## Test Specification

| Test | Covers |
|---|---|
| `test_unique_per_tenant` | AC6 |
| `test_partition_isolation_agents` | AC7 (agents half of `test_partition_isolation`) |
| `test_lock_guard_order` | §2.5a |
| `test_version_bumps_on_definition_update` | §2.6 |
| `test_delete_returns_snapshot` | §2.5c clean-up input |
| `test_load_snapshot_single_statement` | §2.5a snapshot |

---

## Agent Instructions

1. **Work in the feature worktree** — never on `dev`
   (`python -m scripts.sdd.ensure_worktree --slug agentstudio-db-storage --feature-id FEAT-621`).
2. Read the spec sections cited in Context; check every `Depends-on` task is `"done"` in
   `sdd/tasks/index/agentstudio-db-storage.json`.
3. Verify the Codebase Contract anchors (`grep -c`) before editing; fix stale entries in this file first.
4. Set this task `"in-progress"` in the index (with `started_at`) and commit only the index.
5. Implement exactly the files listed, starting from the Blueprint; no refactors outside scope.
6. `ruff check --fix` the touched Python files; run the Validation Commands.
7. Commit code only (never `git add .`/`-A`):
   `feat(agentstudio-db-storage): TASK-3928 — StudioAgentRepository: partitioned CRUD, row lock + guard, one-statement snapshot`.
8. Close with `scripts/sdd/close_task.sh TASK-3928 agentstudio-db-storage verified` and fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, deviations, issues.

**Deviations from spec**: none | describe if any
