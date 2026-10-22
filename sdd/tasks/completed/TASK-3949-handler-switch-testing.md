# TASK-3949: Handler switch: Studio test chat through manager.studio.use() with a lease

**Feature**: FEAT-621 — Agent Studio — Database-Backed Storage
**Spec**: `sdd/specs/agentstudio-db-storage.spec.md`
**Spec wave**: W3 — Handler switch: drafts, catalogue, testing (part 3: testing.py)
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-3943, TASK-3944
**Assigned-to**: unassigned

---

## Context

Spec §2.8 row `testing.py` (Studio agents: `async with manager.studio.use(key, session_id=…, request=self.request)`;
session key `f"studio_test:{key.qualified}"` → `session_id`; the session entry lives in `StudioRuntimeCache`, not
`manager._bots`; stale version ⇒ fresh build), §2.7 (`get_session`, PBAC before any build), X7.

---

## Scope

- `_StudioTestingMixin`: for a Studio row (lookup through the partition), resolve the session id from
  `session[f"studio_test:{key.qualified}"]` (create one if absent) and run the ask inside `manager.studio.use(...)`;
  never read `manager._bots` for Studio rows. Legacy agents keep the current `get_bot(new=True)` path verbatim.
- `DELETE` (end test session) evicts the Studio session entry.

**NOT in scope**: FEAT-605 W3.4 tool-scope binding at test/ask (merges after this task).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/studio/testing.py` | MODIFY | Studio rows through studio.use(); legacy path unchanged |
| `packages/ai-parrot-server/tests/studio/test_testing_db_mode.py` | CREATE | test-chat tests in database mode |

---

## Codebase Contract (Anti-Hallucination)

> **CRITICAL**: verified code references. Use these exact imports, names and signatures. Anything not listed:
> verify it exists (`grep`/`read`) before using it.

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/studio/testing.py
class _StudioTestingMixin:                                       # :164 — session lookup :203-208 reads manager._bots
        bot = await manager.get_bot(agent_name, new=True, session_id=session_id, request=self.request)   # :216 (occurrences: 1)
class StudioTestingHandler(_StudioTestingMixin, StudioBaseView):  # :226 — post :235, delete :312
```

---

## Complexity Contract

```json
{
  "schema_version": 1,
  "targets": [
    {
      "path": "packages/ai-parrot-server/src/parrot/handlers/studio/testing.py",
      "action": "MODIFY"
    },
    {
      "path": "packages/ai-parrot-server/tests/studio/test_testing_db_mode.py",
      "action": "CREATE"
    }
  ],
  "contract_symbols": [
    "sym:packages/ai-parrot-server/src/parrot/handlers/studio/testing.py#StudioTestingHandler"
  ]
}
```

---

## Implementation Notes

- Parallelism: uses BotManager.studio.use from TASK-3943 (manager.py; runtime from TASK-3942) and helpers from TASK-3944 (_base.py); sole FEAT-621 writer of studio/testing.py
- Cross-feature ordering: X16 "Before STORAGE W3" — FEAT-605 W1.3 (`testing.py` execute gate) merges **first**; this
  task rebases on it. Cross-feature ordering: X16 per-file rule — every FEAT-605 or TOOLKITS task that edits `studio/testing.py` merges **after** this task and rebases on it. (e.g. FEAT-605 W3.4, TOOLKITS M5 bindings).
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
- `use()` is a context manager holding a lease: the whole ask (incl. streaming, if any) must run inside it.

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

### `packages/ai-parrot-server/src/parrot/handlers/studio/testing.py` (MODIFY)
```python
# :216 (occurrences: 1) — FILL IN: before this line, branch on "is a Studio row in this partition"; Studio rows:
#   key = StudioAgentKey(part.tenant, agent_name); sid = session.setdefault(f"studio_test:{key.qualified}", uuid4().hex[:12])
#   async with manager.studio.use(key, session_id=sid, request=self.request) as bot: <existing ask body>
#   — the ask body must not be duplicated: extract it into a helper taking `bot`.
```
### `packages/ai-parrot-server/tests/studio/test_testing_db_mode.py` (CREATE)
```python
"""FEAT-621 W3 test chat (AC9, AC14)."""
# FILL IN: test_studio_test_chat_uses_runtime_cache (manager._bots unchanged); test_stale_version_fresh_build;
#   test_lease_held_during_ask; test_end_session_evicts; test_legacy_agent_test_chat_unchanged.
```

---

## Acceptance Criteria

- [ ] Studio test sessions live in `StudioRuntimeCache`, never in `manager._bots` (AC9).
- [ ] The instance is held under a lease for the whole ask; a stale version yields a fresh build (AC14).
- [ ] Existing `tests/studio/test_testing_surface.py` passes unmodified (AC16).
- [ ] `ruff check` clean on every touched Python file; new functions within Rule-4 budgets (`flake8` complexity).

---

## Validation Commands

- `pytest packages/ai-parrot-server/tests/studio/test_testing_db_mode.py -q`
- `pytest packages/ai-parrot-server/tests/studio/test_testing_surface.py -q`

---

## Test Specification

| Test | Covers |
|---|---|
| `test_studio_test_chat_uses_runtime_cache` | AC9 |
| `test_stale_version_fresh_build` | §2.7 |
| `test_lease_held_during_ask` | AC14 |
| `test_end_session_evicts` | §2.7a |
| `test_legacy_agent_test_chat_unchanged` | regression |

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
   `feat(agentstudio-db-storage): TASK-3949 — Handler switch: Studio test chat through manager.studio.use() with a lease`.
8. Close with `scripts/sdd/close_task.sh TASK-3949 agentstudio-db-storage verified` and fill the Completion Note.

---

## Completion Note

**Completed by**: sdd-worker (package integration branch, tramo A)
**Date**: 2026-10-02
**Notes**: Commit 89deae75e. Database-mode test-chat via manager.studio.use with lease; 6 new tests; 5 mutations RED. FLAGS: testing.py 570 lines (>500); _db_delete uses private runtime._cache.session/retire (no public evict_session); no PBAC-deny test.

**Deviations from spec**: none
