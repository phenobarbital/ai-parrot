# TASK-3951: Response-shape snapshot (both modes), release gates and the host guide

**Feature**: FEAT-621 — Agent Studio — Database-Backed Storage
**Spec**: `sdd/specs/agentstudio-db-storage.spec.md`
**Spec wave**: W4 — Shape snapshot + host guide
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3944, TASK-3945, TASK-3946, TASK-3947, TASK-3948, TASK-3949, TASK-3950
**Assigned-to**: unassigned

---

## Context

Spec §7 W4 ("§2.9 snapshot test both modes; host guide"), §4 `test_handlers_shapes_database_mode` and
`test_handlers_filesystem_mode_unchanged` over the routes served by `studio/agents.py`, `studio/files.py`,
`studio/toolkit_config.py`, `studio/drafts.py`, `studio/skills_catalog.py`, `studio/testing.py` and
`studio/meta_agent.py`, AC1 (no-DDL grep gate), AC16, AC17 (`ai_bots` DDL and
`_load_database_bots` untouched — diff gate), AC20 (host guide). STORAGE W4 is part of the package release gate (X16).

---

## Scope

- `test_shapes_db_mode.py`: `aiohttp_client` + real session: POST/GET/DELETE `/agents`, files PUT/GET, drafts bundle
  save + activate, toolkit-config GET/PUT; assert the §2.9 keys exactly (added keys present, no key removed vs the
  filesystem-mode snapshot taken in the same test module).
- `test_storage_gates.py`: (a) no `CREATE`/`ALTER` outside `storage/migrations/*.sql` and `migrate.py` in the server
  package; (b) `_load_database_bots` and the `navigator.ai_bots` DDL unchanged vs `origin/dev` merge-base;
  (c) `setup()`/`on_startup` never reference `apply_studio_migrations`; (d) the existing `tests/studio/*` suite runs with
  `PARROT_STUDIO_STORAGE=filesystem` (documented command in the guide).
- `docs/agentstudio/db-storage.md`: settings table (all new keys), supported PostgreSQL (≥ 14; tested 14/16),
  migration commands and file format (body + trailer, checksum, MANIFEST), FieldSync runner note, lifecycle hooks and
  mount order (X8/X10), the release-gate statement (no tenant-ready release until all three specs' gates are met).

**NOT in scope**: New behaviour of any kind.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/tests/studio/test_shapes_db_mode.py` | CREATE | §2.9 snapshot test, both modes |
| `packages/ai-parrot-server/tests/studio/storage/test_storage_gates.py` | CREATE | no-startup-DDL, ai_bots untouched, no migration at startup |
| `docs/agentstudio/db-storage.md` | CREATE | host guide |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified code references. Use these exact imports, names and signatures. Anything not listed:
> verify it exists (`grep`/`read`) before using it.

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/manager/manager.py
    async def _load_database_bots(self, app) -> None     # :610 — must be byte-identical after FEAT-621
```
`docs/agentstudio/` does not exist yet (new directory); `docs/agent_studio_api.md` is the existing FEAT-467 API doc —
link to it, do not edit it.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/tests/studio/test_shapes_db_mode.py",
      "action": "CREATE"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/storage/test_storage_gates.py",
      "action": "CREATE"
    },
    {
      "path": "docs/agentstudio/db-storage.md",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/manager/manager.py#BotManager._load_database_bots"
  ]
}
```

---

## Implementation Notes

- Parallelism: snapshots the final database-mode responses of each W3 handler: TASK-3944 (studio/agents.py), TASK-3945 (studio/files.py), TASK-3946 (studio/toolkit_config.py), TASK-3947 (studio/drafts.py), TASK-3948 (studio/skills_catalog.py), TASK-3949 (studio/testing.py), TASK-3950 (studio/meta_agent.py); creates only new test files and the host guide
- Cross-feature ordering: X16 release gate — no release is called, documented or enabled as tenant-ready until
  FEAT-605 (through W4.3, incl. W2.2 and W3.6), STORAGE W0–W4 (this task closes W4) and TOOLKITS Waves 1–4 are all
  merged; tenant hosts keep `studio_enabled=False` until then. The guide must say so.
- The diff gate compares against `git merge-base HEAD origin/dev` at test time; skip with a reason when git is
  unavailable (e.g. an sdist).

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

### `packages/ai-parrot-server/tests/studio/test_shapes_db_mode.py` (CREATE)
```python
"""FEAT-621 W4 — §2.9 response shapes in both modes (AC16). aiohttp_client + real session middleware."""
# FILL IN: one parametrised scenario list (route, method, body); run against filesystem then database apps; assert
#   set(db_keys) >= set(fs_keys) and set(db_keys) - set(fs_keys) == the §2.9 "added" set for that route.
```
### `packages/ai-parrot-server/tests/studio/storage/test_storage_gates.py` (CREATE)
```python
"""FEAT-621 gates: AC1 (no startup DDL), AC17 (ai_bots untouched)."""
# FILL IN: test_no_ddl_outside_migrations; test_load_database_bots_untouched; test_no_migration_call_at_startup.
```
### `docs/agentstudio/db-storage.md` (CREATE)
```markdown
# Agent Studio — database storage (host guide)
## Settings            <!-- FILL IN: every key from spec §6 "Does NOT Exist — config keys", default, effect -->
## Supported PostgreSQL
## Migrations          <!-- parrot-studio-migrate flags; psql -1; FieldSync runner; checksum + MANIFEST -->
## Lifecycle and mount order
## Release gate
```

---

## Acceptance Criteria

- [ ] Every database-mode response shape is additive per §2.9; filesystem-mode shapes unchanged (AC16).
- [ ] Gates: no DDL outside the migration files; `ai_bots` DDL and `_load_database_bots` untouched; no migration at startup (AC1, AC17).
- [ ] `docs/agentstudio/db-storage.md` covers settings, PostgreSQL support, migrations + file format, FieldSync runner, lifecycle hooks + mount order, release gate (AC20).
- [ ] `ruff check` clean on every touched Python file; new functions within Rule-4 budgets (`flake8` complexity).

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/studio/test_shapes_db_mode.py -q`
- `pytest packages/ai-parrot-server/tests/studio/storage/test_storage_gates.py -q`

---

## Test Specification

| Test | Covers |
|---|---|
| `test_handlers_shapes_database_mode` (`test_shapes_db_mode.py`) | AC16 |
| `test_handlers_filesystem_mode_unchanged` (same module + documented suite run) | AC16 |
| `test_no_ddl_outside_migrations` | AC1 |
| `test_load_database_bots_untouched` | AC17 |
| `test_no_migration_call_at_startup` | AC1 |

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
   `feat(agentstudio-db-storage): TASK-3951 — Response-shape snapshot (both modes), release gates and the host guide`.
8. Close with `scripts/sdd/close_task.sh TASK-3951 agentstudio-db-storage verified` and fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (package integration branch, tramo A)
**Date**: 2026-10-02
**Notes**: Commit 32c94cca9. test_shapes_db_mode.py (both modes), test_storage_gates.py (no-DDL incl. phase-2 modules, no migration at startup, ai_bots/_load_database_bots untouched vs merge-base), docs/agentstudio/db-storage.md incl. phase-2 switches/copy runbook; 6 tests, 9 mutations RED. Shape caveats: Studio GET /agents items lack six registry keys (at_startup,class_name,file_path,module,priority,tags); parrot-studio-migrate --verify only checks 1-5.

**Deviations from spec**: none
