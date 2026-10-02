# TASK-3945: Handler switch: /agents/{name}/files on StudioAssetService

**Feature**: FEAT-621 — Agent Studio — Database-Backed Storage
**Spec**: `sdd/specs/agentstudio-db-storage.spec.md`
**Spec wave**: W3 — Handler switch: agents, files, tooling (part 2: files.py)
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3936, TASK-3944
**Assigned-to**: unassigned

---

## Context

Spec §2.8 row `files.py`, §2.9 files rows (`reload_required: false`, added `version` and `sha256`; new 413/415/422
errors; list stays `{kind, files: [str]}`), §2.9 `expected_version` supported on PUT/DELETE.

---

## Scope

- `StudioFilesHandler.get/put/delete`: database mode through `StudioAssetService`; legacy bodies moved verbatim to
  `_legacy_*`. `write_text`/`resolve_safe_path` disappear from the DB path. Same validation rules (reused by the
  service from `_StudioFilesMixin`).

**NOT in scope**: Skills catalogue import (TASK-3948).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/studio/files.py` | MODIFY | database-mode GET/PUT/DELETE; _legacy_* moves |
| `packages/ai-parrot-server/tests/studio/test_files_db_mode.py` | CREATE | database-mode file route tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified code references. Use these exact imports, names and signatures. Anything not listed:
> verify it exists (`grep`/`read`) before using it.

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/studio/files.py
class _StudioFilesMixin:                       # :76 (occurrences: 1)
class StudioFilesHandler(_StudioFilesMixin, StudioBaseView):   # :162 — get :170, put :216, delete :280
```

### Does NOT Exist
- ~~`version`/`sha256` keys in today's file responses~~ — added in database mode only.

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/files.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/test_files_db_mode.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/files.py#StudioFilesHandler"
  ]
}
```

---

## Implementation Notes

- Parallelism: calls StudioAssetService from TASK-3936 (services/assets.py) and the _studio_write/_studio_error helpers from TASK-3944 (_base.py); sole FEAT-621 writer of studio/files.py
- Cross-feature ordering: X16 per-file rule — every FEAT-605 or TOOLKITS task that edits `studio/files.py` merges **after** this task and rebases on it.
- Database mode only on the new path: `storage = self._studio_storage()`; `backend == "filesystem"` ⇒ the
  existing verb body runs unchanged, moved **verbatim** into `_legacy_<verb>` (a pure move — no drive-by edits).
- Every service-path write passes `StudioWriteGuard(authorized_version=<version of the record the access decision
  used>, expected_version=<body/query value on the §2.9 supported routes>)` and retries **once** on
  `StudioStaleAuthorization` (helper `_studio_write` from TASK-3944); a second stale ⇒ 409 `version_conflict`.
- Error mapping via `_studio_error` (TASK-3944): X14 codes and statuses only (503 `studio_storage_unavailable`,
  409 `version_conflict`, 413 `asset_too_large`/`agent_assets_quota`, 415 `binary_assets_unsupported`, 422
  `unsupported_config_key`/`tooling_not_permitted`/`name_immutable`/`declarative_only`, 409 `not_studio_agent`).
  `StudioNameConflict` answers today's `duplicate` (pre-merge state); FEAT-605 v0.2 switches it to `name_taken`.
- Partition: `part = await self._studio_partition()`; `storage.require_for(part)` before any storage call.
- Response shapes: exactly the additive changes of spec §2.9 — no key removed or renamed.

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

### `packages/ai-parrot-server/src/parrot/handlers/studio/files.py` (MODIFY)
```python
# StudioFilesHandler.get/put/delete: FILL IN — filesystem ⇒ return await self._legacy_<verb>(); else
#   part = await self._studio_partition(); storage.require_for(part); svc = storage.services.assets;
#   PUT: content_type from header/body, expected_version via self._expected_version(body);
#   response {..., "reload_required": False, "version": v, "sha256": rec.sha256} — bounded by §2.9 files rows.
```

### `packages/ai-parrot-server/tests/studio/test_files_db_mode.py` (CREATE)
```python
"""FEAT-621 W3 files (AC4, AC8, AC16)."""
# FILL IN: test_files_put_get_delete_shapes; test_files_413_415_codes; test_files_stale_expected_version (409, row
#   unchanged); test_files_list_shape_unchanged; test_files_policy_refusal_422.
```

---

## Acceptance Criteria

- [ ] Database-mode file routes return `reload_required: false`, `version`, `sha256`; list shape unchanged (AC16).
- [ ] 413 `asset_too_large` / `agent_assets_quota`, 415 `binary_assets_unsupported`, 422 `tooling_not_permitted` mapped (X14).
- [ ] Stale `expected_version` on PUT/DELETE → 409, nothing written (AC8).
- [ ] Existing `tests/studio/test_files.py` passes unmodified in filesystem mode (AC16).
- [ ] `ruff check` clean on every touched Python file; new functions within Rule-4 budgets (`flake8` complexity).

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/studio/test_files_db_mode.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_files.py -q`

---

## Test Specification

| Test | Covers |
|---|---|
| `test_files_put_get_delete_shapes` | AC16 |
| `test_files_413_415_codes` | X14 |
| `test_files_stale_expected_version` | AC8 (`test_stale_child_writes`, files half) |
| `test_files_list_shape_unchanged` | §2.9 |
| `test_files_policy_refusal_422` | AC13 |

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
   `feat(agentstudio-db-storage): TASK-3945 — Handler switch: /agents/{name}/files on StudioAssetService`.
8. Close with `scripts/sdd/close_task.sh TASK-3945 agentstudio-db-storage verified` and fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (package integration branch, tramo A)
**Date**: 2026-10-02
**Notes**: Commit a79b24b5e. Database-mode files routes via StudioAssetService; 6 new tests on real PG; 5 mutations RED. content_type read from body field (JSON header would always 415). GET unsafe name 404 (legacy 400). _legacy_put over-budget is the verbatim legacy body.

**Deviations from spec**: none
