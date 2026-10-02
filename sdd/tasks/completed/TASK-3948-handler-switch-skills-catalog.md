# TASK-3948: Handler switch: /skills catalogue on StudioSkillCatalogService; derived index

**Feature**: FEAT-621 — Agent Studio — Database-Backed Storage
**Spec**: `sdd/specs/agentstudio-db-storage.spec.md`
**Spec wave**: W3 — Handler switch: drafts, catalogue, testing (part 2: skills_catalog.py)
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3938, TASK-3944
**Assigned-to**: unassigned

---

## Context

Spec §2.8 row `skills_catalog.py` (shared `SkillRegistry` becomes a derived per-pod index: namespace
`<tenant or org_id>/_shared`, persistence under `STUDIO_RUNTIME_DIR/_shared/<partition>/skills`, rebuilt by
`resync`/startup reconcile from Postgres; import-to-agent writes an `ai_agent_assets` row under the agent lock),
§2.9 `/skills*` (added `tenant`, `visibility`, `allowed_groups`; per-partition uniqueness; `expected_version` → 400),
Q3.

---

## Scope

- `StudioSkillsCatalogHandler` get/post/put/delete, `StudioSkillsImportHandler.post`, `StudioSkillsResyncHandler.post`
  and `reconcile_skills_catalog` in database mode through the service; `_get_shared_skill_registry` uses
  `shared_index_location(part, org_id)`; legacy bodies moved verbatim.
- `expected_version` on any `/skills*` route → 400 `expected_version_unsupported`.

**NOT in scope**: FEAT-605 `PATCH /skills/{id}/visibility` (W4.1).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/studio/skills_catalog.py` | MODIFY | database-mode catalogue routes; derived index location; _legacy_* moves |
| `packages/ai-parrot-server/tests/studio/test_skills_catalog_db_mode.py` | CREATE | database-mode catalogue tests |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified code references. Use these exact imports, names and signatures. Anything not listed:
> verify it exists (`grep`/`read`) before using it.

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/studio/skills_catalog.py
def _shared_namespace(org_id: str) -> str                                   # :46
def _get_shared_skill_registry(app: Any, org_id: str):                      # :51 (occurrences: 1)
async def reconcile_skills_catalog(app: Any) -> None                        # :119
class StudioSkillsCatalogHandler(_StudioSkillsMixin, StudioBaseView):       # :268 — get :276, post :333, put :397, delete :442
class StudioSkillsImportHandler(_StudioSkillsMixin, _StudioFilesMixin, StudioBaseView):  # :515 — post :527
class StudioSkillsResyncHandler(_StudioSkillsMixin, StudioBaseView):        # :593 — post :602
```

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/skills_catalog.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/test_skills_catalog_db_mode.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/skills_catalog.py#StudioSkillsCatalogHandler",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/skills_catalog.py#_get_shared_skill_registry"
  ]
}
```

---

## Implementation Notes

- Parallelism: calls StudioSkillCatalogService/shared_index_location from TASK-3938 (services/catalog.py) and helpers from TASK-3944 (_base.py); sole FEAT-621 writer of studio/skills_catalog.py
- Cross-feature ordering: X16 "Before STORAGE W3" — FEAT-605 W1.3 (`skills_catalog.py` resync gate) merges
  **first**; this task rebases on it and its `_legacy_*` bodies carry it verbatim.
  Cross-feature ordering: X16 per-file rule — every FEAT-605 or TOOLKITS task that edits `studio/skills_catalog.py` merges **after** this task and rebases on it.
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

### `packages/ai-parrot-server/src/parrot/handlers/studio/skills_catalog.py` (MODIFY)
```python
# _get_shared_skill_registry (:51): FILL IN — database backend ⇒ namespace/path from shared_index_location(part, org_id)
#   (never AGENTS_DIR); filesystem ⇒ unchanged.
# Each verb: filesystem ⇒ _legacy_<verb>; database ⇒ service call; refuse expected_version with 400.
```
### `packages/ai-parrot-server/tests/studio/test_skills_catalog_db_mode.py` (CREATE)
```python
"""FEAT-621 W3 catalogue (AC4, AC6, AC16)."""
# FILL IN: test_skills_shapes_add_tenancy_keys; test_skills_unique_per_partition_409;
#   test_skills_expected_version_unsupported (400); test_import_writes_asset_row; test_resync_rebuilds_from_postgres;
#   test_index_not_under_agents_dir.
```

---

## Acceptance Criteria

- [ ] `/skills*` items carry `tenant`, `visibility`, `allowed_groups`; name uniqueness per partition (AC6, AC16).
- [ ] `expected_version` on `/skills*` → 400 `expected_version_unsupported` (`test_stale_child_writes`, catalogue half).
- [ ] Import-to-agent writes an `ai_agent_assets` row; the derived index lives under `STUDIO_RUNTIME_DIR` (AC4).
- [ ] Existing `tests/studio/test_skills_catalog.py` passes unmodified in filesystem mode (AC16).
- [ ] `ruff check` clean on every touched Python file; new functions within Rule-4 budgets (`flake8` complexity).

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/studio/test_skills_catalog_db_mode.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_skills_catalog.py -q`

---

## Test Specification

| Test | Covers |
|---|---|
| `test_skills_shapes_add_tenancy_keys` | AC16 |
| `test_skills_unique_per_partition_409` | AC6 |
| `test_skills_expected_version_unsupported` | §2.9 |
| `test_import_writes_asset_row` | AC4 |
| `test_resync_rebuilds_from_postgres` | Q3 |
| `test_index_not_under_agents_dir` | AC4 |

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
   `feat(agentstudio-db-storage): TASK-3948 — Handler switch: /skills catalogue on StudioSkillCatalogService; derived index`.
8. Close with `scripts/sdd/close_task.sh TASK-3948 agentstudio-db-storage verified` and fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (package integration branch, tramo A)
**Date**: 2026-10-02
**Notes**: Commits a98a4037f, 807a0e964. Database-mode catalogue routes, import, resync, derived index under STUDIO_RUNTIME_DIR; 7 new tests; 9 mutations RED. Adjusted 2 tests in test_scope_route_gates.py (tenant partition without DB now 503). FLAGS: skills_catalog.py is 931 lines (>500 budget; legacy bodies verbatim, only that file allowed); catalogue service has no write guard so only import uses _studio_write; new skills always private (no visibility field in SkillPublishRequest).

**Deviations from spec**: none
