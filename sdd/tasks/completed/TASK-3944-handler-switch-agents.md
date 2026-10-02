# TASK-3944: Handler switch: /agents (POST/GET/DELETE/reload) and new PATCH /agents/{name}

**Feature**: FEAT-621 — Agent Studio — Database-Backed Storage
**Spec**: `sdd/specs/agentstudio-db-storage.spec.md`
**Spec wave**: W3 — Handler switch: agents, files, tooling (part 1: agents.py + shared view helpers)
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-3932, TASK-3935, TASK-3943
**Assigned-to**: unassigned

---

## Context

Spec §2.8 rows `agents.py` / `StudioAgentReloadHandler`, §2.9 rows `/agents*`, §2.9a (`PATCH /agents/{name}`),
§2.5a step 3 (one stale-authorisation retry), X12, X14. Filesystem mode stays byte-for-byte unchanged.

---

## Scope

- `_base.py`: `_studio_write(fn, *, record_version, expected_version)` (guard + single retry on
  `StudioStaleAuthorization`, re-reading via a callback), `_studio_error(exc)` (X14 mapping),
  `_expected_version(body_or_query)` and `_refuse_expected_version()` (400 `expected_version_unsupported`).
- `agents.py`: POST/GET/DELETE in database mode through `StudioAgentService` (§2.8 row 1; duplicate check also
  against the legacy registry and `ai_bots` names on the GLOBAL partition; GLOBAL list merges legacy agents, tenant
  list returns Studio rows only; `persist: false` ⇒ `warnings`); new `patch` verb (§2.9a: `name` → 422
  `name_immutable`, legacy agent → 409 `not_studio_agent`, filesystem → 503); reload → `manager.studio.reload(key)`
  for Studio rows, `reload_agent(name)` otherwise.
- Legacy bodies moved verbatim into `_legacy_get/_legacy_post/_legacy_delete/_legacy_reload`.
- Tests: database-mode agent routes + the services wiring check.

**NOT in scope**: files/tooling/drafts/catalogue/testing handlers (TASK-3945..28); access policy (FEAT-605).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/studio/_base.py` | MODIFY | _studio_write, _studio_error, expected_version helpers |
| `packages/ai-parrot-server/src/parrot/handlers/studio/agents.py` | MODIFY | database-mode POST/GET/DELETE/PATCH/reload; _legacy_* moves |
| `packages/ai-parrot-server/tests/studio/test_agents_db_mode.py` | CREATE | aiohttp_client tests, real session, real PG |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified code references. Use these exact imports, names and signatures. Anything not listed:
> verify it exists (`grep`/`read`) before using it.

### Verified Imports
```python
from parrot.handlers.studio.storage.models import (StudioAgentDefinition, StudioAgentPatch, StudioAgentKey,
    StudioWriteGuard, StudioStaleAuthorization, StudioNameConflict, StudioVersionConflict,
    StudioStorageUnavailable, StudioToolingRefused, StudioNotFound)            # TASK-3922
from parrot.handlers.studio.models import CreateAgentRequest                   # models.py:38
from navigator_auth.decorators import is_authenticated, user_session          # agents.py:25
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/studio/agents.py
class _StudioAgentsMixin:                    # :39 (occurrences: 1) — _check_duplicate :89, _get_db_agent :51
class StudioAgentsHandler(_StudioAgentsMixin, StudioBaseView):   # :167 — get :175, _get_one :182, _get_all :193,
                                                                 #   post :209, delete :373
class StudioAgentReloadHandler(_StudioAgentsMixin, StudioBaseView):  # :443 — post :450
# `    async def post(self):` occurs 2× in agents.py (:209 create, :450 reload) — anchor with the enclosing class.
# packages/ai-parrot-server/src/parrot/handlers/studio/_base.py — StudioBaseView :121 ; _studio_partition/_studio_storage added by TASK-3932
```
The `PATCH` route needs no new route line: `StudioAgentsHandler` is already mounted at `/agents/{name}`
(`studio/__init__.py`).

### Does NOT Exist
- ~~`PATCH /astudio/agents/{name}`~~ — added here. ~~A rename~~ — out of scope (§2.9a).

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/_base.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/agents.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/test_agents_db_mode.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/agents.py#StudioAgentsHandler",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/agents.py#StudioAgentReloadHandler",
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/_base.py#StudioBaseView"
  ]
}
```

---

## Implementation Notes

- Parallelism: calls StudioAgentService from TASK-3935 (services/agents.py) and manager.studio.reload from TASK-3943 (manager.py); edits studio/_base.py after TASK-3932 (same file); adds the _studio_write/_studio_error helpers TASK-3945..28 use
- Cross-feature ordering: X16 per-file rule — every FEAT-605 or TOOLKITS task that edits `studio/agents.py` merges **after** this task and rebases on it. `studio/_base.py`: small non-overlapping FEAT-605 edits (W0.2, W1.1,
  W2.1) serialise, whichever merges first. FEAT-605 W3.1 adds the policy row for PATCH (X12) after this task.
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
- Assert at least once in this task's tests that `app["studio_storage"].services` builds all five services
  (`build_studio_services`, TASK-3933) — it is the first end-to-end use.

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
1. Add the four helpers to `_base.py`; 2. move each legacy verb body verbatim into `_legacy_*` and dispatch on the
   backend; 3. write the database path per verb; 4. add `patch`; 5. tests.

### `packages/ai-parrot-server/src/parrot/handlers/studio/_base.py` (MODIFY — inside `StudioBaseView`, after `_studio_storage`)
```python
    async def _studio_write(self, write, *, reread, expected_version: int | None):
        """Run write(guard) with the record version the access decision used; retry once on stale authorisation."""
        record = await reread()
        for attempt in (1, 2):
            guard = StudioWriteGuard(authorized_version=record.version if record else None, expected_version=expected_version)
            try:
                return await write(guard)
            except StudioStaleAuthorization:
                if attempt == 2:
                    raise StudioVersionConflict("authorization went stale twice")
                record = await reread()     # FEAT-605 re-runs its access decision on this record
    # FILL IN: _studio_error(exc) -> web.Response (X14 table), _expected_version(source) -> int | None,
    #   _refuse_expected_version(source) -> web.Response | None.
```

### `packages/ai-parrot-server/src/parrot/handlers/studio/agents.py` (MODIFY)
```python
# StudioAgentsHandler.post (:209, anchor with class): FILL IN dispatch
#   if self._studio_storage().backend == "filesystem": return await self._legacy_post()
# FILL IN: database POST/GET/DELETE per §2.8 row 1 and §2.9; new `async def patch(self)` per §2.9a.
# StudioAgentReloadHandler.post (:450): Studio row → manager.studio.reload(StudioAgentKey(part.tenant, name)).
```

### `packages/ai-parrot-server/tests/studio/test_agents_db_mode.py` (CREATE)
```python
"""FEAT-621 W3 agents in database mode (AC4, AC8, AC16, AC18). aiohttp_client + real session middleware."""
# FILL IN: test_create_without_bundle_http (201 with source studio, agent_id, version, tenant; persist false →
#   warnings); test_patch_agent_general_fields (200 + version bump; name → 422 name_immutable; stale → 409; legacy →
#   409 not_studio_agent; filesystem → 503); test_delete_guarded; test_reload_studio_agent;
#   test_tenant_partition_on_filesystem_is_503 (override _studio_partition in a test subclass);
#   test_services_container_builds; test_nothing_written_under_agents_dir.
```

---

## Acceptance Criteria

- [ ] Database-mode `/agents` routes return the §2.9 shapes (added keys only) (AC16).
- [ ] `PATCH /agents/{name}` per §2.9a incl. `name_immutable`, `not_studio_agent`, `version_conflict`, 503 on filesystem (X12).
- [ ] Writes pass a `StudioWriteGuard` and retry once on stale authorisation (AC8).
- [ ] A tenant partition on the filesystem backend → 503 `studio_storage_unavailable` (`test_tenant_partition_on_filesystem_is_503`).
- [ ] Filesystem-mode bodies unchanged (pure move); existing `tests/studio/test_agents_lifecycle.py` passes unmodified (AC16).
- [ ] `ruff check` clean on every touched Python file; new functions within Rule-4 budgets (`flake8` complexity).

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/studio/test_agents_db_mode.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_agents_lifecycle.py -q`

---

## Test Specification

| Test | Covers |
|---|---|
| `test_create_without_bundle_http` | AC8, §2.9 |
| `test_patch_agent_general_fields` | §2.9a |
| `test_delete_guarded` | AC8 |
| `test_reload_studio_agent` | §2.8 |
| `test_tenant_partition_on_filesystem_is_503` | §2.2 |
| `test_services_container_builds` | wiring |
| `test_nothing_written_under_agents_dir` | AC4 |

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
   `feat(agentstudio-db-storage): TASK-3944 — Handler switch: /agents (POST/GET/DELETE/reload) and new PATCH /agents/{name}`.
8. Close with `scripts/sdd/close_task.sh TASK-3944 agentstudio-db-storage verified` and fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (package integration branch, tramo A)
**Date**: 2026-10-02
**Notes**: Commit 4c2988f29. Database-mode agents routes, PATCH, reload, _studio_write/_studio_error helpers; 13 new tests on real PG, 12 mutation checks RED. Missing app storage falls back to legacy path (test_agents_lifecycle unmodified). Flag: agents.py ~755 lines and _base.py ~533 exceed the 500-line module budget (task lists no helper module); _legacy_post/_legacy_delete are verbatim-moved over-budget bodies.

**Deviations from spec**: none
