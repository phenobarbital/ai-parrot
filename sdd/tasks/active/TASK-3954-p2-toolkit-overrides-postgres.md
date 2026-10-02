# TASK-3954: Phase 2: per-user toolkit overrides in navigator.ai_user_toolkit_overrides behind TOOLKIT_OVERRIDES_STORE

**Feature**: FEAT-621 — Agent Studio — Database-Backed Storage
**Spec**: `sdd/specs/agentstudio-db-storage.spec.md`
**Spec wave**: P2 (phase 2) — Vault credentials + overrides in Postgres (M12, part 2: per-user toolkit overrides)
**Status**: pending
**Priority**: low
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3927, TASK-3953
**Assigned-to**: unassigned

---

## Context

Spec §2.10 (overrides row, 0008 DDL, `TOOLKIT_OVERRIDES_STORE`), §3 Module 12 (`ToolkitConfigService` dispatches to
`PgToolkitOverrideStore` with the same methods, incl. `purge_agent`), X3/X17 (key `agent_ref` = tooling ref).
Phase 2 (spec §2.10): separately releasable; defaults stay `documentdb` until a host opts in (FieldSync sets all three switches to `postgres`). The identity scheme (§2.5c) is already in force in v1: phase 2 changes WHERE credentials live, never WHAT they are called. Ciphertexts are byte-compatible (same AAD contexts), so every move is a copy, not a re-encryption.

---

## Scope

- `migrations/0008_ai_user_toolkit_overrides.sql` + trailer; MANIFEST entry.
- `storage/overrides_store.py` `PgToolkitOverrideStore(pool)`: `save`, `load`, `remove`, `revision`, `purge_agent` —
  same signatures as `ToolkitConfigService`; `agent_ref` column.
- `toolkit_persistence.py`: `ToolkitConfigService` dispatches on `TOOLKIT_OVERRIDES_STORE` (registration at startup
  in the same place as the vault store).
- Test `test_vault_and_overrides_pg_roundtrip`: with both switches `postgres`, the cross-tenant identity scenario
  passes and DocumentDB is never contacted.

**NOT in scope**: Copy script (TASK-3955).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/studio/storage/migrations/0008_ai_user_toolkit_overrides.sql` | CREATE | overrides table (§2.10) + trailer |
| `packages/ai-parrot-server/src/parrot/handlers/studio/storage/migrations/MANIFEST.json` | MODIFY | version 8 entry |
| `packages/ai-parrot-server/src/parrot/handlers/studio/storage/overrides_store.py` | CREATE | PgToolkitOverrideStore |
| `packages/ai-parrot-server/src/parrot/handlers/toolkit_persistence.py` | MODIFY | TOOLKIT_OVERRIDES_STORE dispatch |
| `packages/ai-parrot-server/tests/studio/storage/test_overrides_store.py` | CREATE | real-PG overrides + combined phase-2 identity test |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified code references. Use these exact imports, names and signatures. Anything not listed:
> verify it exists (`grep`/`read`) before using it.

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/toolkit_persistence.py
class ToolkitConfigService:   # :28 — save :31, load :37, remove :53, revision :63, purge_agent (TASK-3927); COLLECTION :14
```

### Does NOT Exist
- ~~`TOOLKIT_OVERRIDES_STORE`~~, ~~`navigator.ai_user_toolkit_overrides`~~ — new.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/storage/migrations/0008_ai_user_toolkit_overrides.sql",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/storage/migrations/MANIFEST.json",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/storage/overrides_store.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/toolkit_persistence.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/storage/test_overrides_store.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/toolkit_persistence.py#ToolkitConfigService"
  ]
}
```

---

## Implementation Notes

- Parallelism: exclusive: rewrites the shared MANIFEST.json after TASK-3953 (0007 entry, same file); edits handlers/toolkit_persistence.py after TASK-3927 (purge_agent, same file)
- Cross-feature ordering: X16 "Identity files" — TOOLKITS M9 (R3 consumer) only tests `toolkit_persistence.py`;
  this phase-2 edit lands **after** TOOLKITS M9 ("P2 M12 later edits `toolkit_persistence.py` after M9").
- New migration file follows TASK-3924's format exactly (advisory lock first; body + one `-- @studio-ledger` trailer); write the body, then run `parrot-studio-migrate --stamp` to produce the trailer hex and the MANIFEST entry. `required` stays 5; `required_phase2` is 8.

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

### `packages/ai-parrot-server/src/parrot/handlers/toolkit_persistence.py` (MODIFY)
```python
# FILL IN: module-level _PG_OVERRIDES = None + set_toolkit_override_store(store); each ToolkitConfigService method:
#   `if _PG_OVERRIDES is not None: return await _PG_OVERRIDES.<same method>(...)` — signatures unchanged.
```
### `packages/ai-parrot-server/src/parrot/handlers/studio/storage/overrides_store.py` (CREATE) — FILL IN per Scope.
### `packages/ai-parrot-server/tests/studio/storage/test_overrides_store.py` (CREATE)
```python
# FILL IN: test_overrides_pg_roundtrip; test_purge_agent_pg; test_vault_and_overrides_pg_roundtrip (re-run the
#   cross-tenant identity scenario of TASK-3946 with both switches on; DocumentDb patched to raise if instantiated).
```

---

## Acceptance Criteria

- [ ] With `VAULT_STORE=postgres` and `TOOLKIT_OVERRIDES_STORE=postgres`, the cross-tenant identity scenario passes and DocumentDB is never contacted (`test_vault_and_overrides_pg_roundtrip`, AC21).
- [ ] `ToolkitConfigService` signatures unchanged; `purge_agent` works on Postgres.
- [ ] Regression: `pytest packages/ai-parrot-server/tests/studio/storage/test_migration_files.py -q` (from TASK-3924) green with 0008 stamped.
- [ ] `ruff check` clean on every touched Python file; new functions within Rule-4 budgets (`flake8` complexity).

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/studio/storage/test_overrides_store.py -q`

---

## Test Specification

| Test | Covers |
|---|---|
| `test_overrides_pg_roundtrip` | AC21 |
| `test_purge_agent_pg` | §2.5c on Postgres |
| `test_vault_and_overrides_pg_roundtrip` | AC21 |

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
   `feat(agentstudio-db-storage): TASK-3954 — Phase 2: per-user toolkit overrides in navigator.ai_user_toolkit_overrides behind TOOLKIT_OVERRIDES_STORE`.
8. Close with `scripts/sdd/close_task.sh TASK-3954 agentstudio-db-storage verified` and fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, deviations, issues.

**Deviations from spec**: none | describe if any
