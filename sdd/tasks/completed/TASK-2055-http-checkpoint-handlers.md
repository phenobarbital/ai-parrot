# TASK-2055: HTTP ops handlers — list / history / resume / delete

**Feature**: FEAT-399 — AgentsFlow State Checkpointing (Two-Tier Persistence)
**Spec**: `sdd/specs/agentsflow-state-checkpointing.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2053
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 9 (resolved OQ5): the ops surface over the checkpoint plane,
following the existing `parrot/handlers/` layout and auth conventions —
no new auth mechanism.

---

## Scope

- Implement `parrot/handlers/flows/checkpoints.py` following the existing
  handlers pattern (aiohttp `BaseView`-style classes, same auth decorators/
  middleware the sibling handlers use — READ 2–3 existing handlers first and
  copy their conventions exactly):
  - `GET  /api/v1/flows/checkpoints` — list recoverable flows
    (`?status=suspended` filter; queries durable store and ephemeral store).
  - `GET  /api/v1/flows/checkpoints/{flow_id}` — checkpoint history for a flow.
  - `POST /api/v1/flows/checkpoints/{flow_id}/resume` — body:
    `{"checkpoint_id": optional}`; resumes via `AgentsFlow.resume()` and
    schedules `run_flow()` as a background task; returns flow_id + accepted
    status (202). `FlowLockedError` → 409; `CheckpointNotFoundError` → 404.
  - `DELETE /api/v1/flows/checkpoints/{flow_id}` — delete a flow's
    checkpoints from both tiers.
- Route registration wherever sibling flow/crew handlers register theirs
  (BotManager route registration — verify how `parrot.manager.manager`
  imports and registers handler classes, and follow it).
- Resume needs an `AgentRegistry` — obtain it the same way sibling handlers
  obtain bot/agent context (verify in existing handlers; do not invent a
  new lookup path).
- Handler tests per existing `packages/ai-parrot/tests/handlers/` conventions
  (there is a `conftest.py` there — reuse its fixtures).

**NOT in scope**: new auth scheme (explicit spec resolution), UI, WebSocket
progress streaming.

---

## Files to Create / Modify

**CORRECTED during this task (2026-08-01) — the original paths below are
STALE.** FEAT-203 (TASK-1371/1372) relocated `parrot/handlers/` and
`parrot/manager/manager.py` (BotManager) to the `ai-parrot-server`
satellite package. Verified directly: `packages/ai-parrot/src/parrot/
handlers/` only contains `dataset_filter_handler.py`/
`spatial_filter_handler.py`/`credentials_utils.py`/`vault_utils.py` — no
`crew/`, `agents/`, etc. The real sibling handlers (crew/, agent.py, …)
and `manager/manager.py` live under `packages/ai-parrot-server/src/
parrot/`.

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/flows/__init__.py` | CREATE | Sub-package (mirrors `handlers/crew/__init__.py`'s plain re-export pattern; `handlers/` itself has no `__init__.py` — implicit namespace package) |
| `packages/ai-parrot-server/src/parrot/handlers/flows/checkpoints.py` | CREATE | Handler class(es) |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | Import + `router.add_view(...)` in `setup()`, same as `ChatHandler`/`AgentTalk`/etc. |
| `packages/ai-parrot/tests/handlers/test_checkpoint_handlers.py` | CREATE | Handler tests — reuses `conftest.py`'s `_register_module`/`_register_package` cross-satellite-package loading technique (see its module docstring: "Handlers were relocated to the ai-parrot-server satellite package (TASK-1371)") |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.bots.flows.core.checkpoint.store.factory import get_checkpoint_store  # TASK-2048
from parrot.bots.flows.core.checkpoint.errors import FlowLockedError, CheckpointNotFoundError  # TASK-2046
# AgentsFlow.resume() — TASK-2053 signature:
#   @classmethod async def resume(cls, flow_id, checkpoint_id=None, *, agent_registry, store=None, durable_store=None)
```

### Existing Signatures to Use (verified structure — details to confirm in-repo)
```python
# parrot/handlers/ — ~59 files; sub-packages: agents/, crew/, database/, jobs/,
#   models/, scraping/, stores/. Key classes incl. ChatHandler, BotHandler,
#   CrewHandler (aiohttp BaseView style; navigator/navigator-auth for auth).
#   [verified via repo knowledge graph: FEAT-203 finding F001-handlers-structure]
# Route registration: parrot.manager.manager (BotManager) imports ~25 handler
#   classes and registers their routes — add checkpoint handlers THERE, the same way.
# packages/ai-parrot/tests/handlers/conftest.py — existing handler-test fixtures; reuse.
```

### Does NOT Exist
- ~~`parrot/handlers/flows/`~~ — likely absent (existing sub-packages listed above do NOT include `flows/`); verify, create if absent.
- ~~A dedicated checkpoint API key / auth scheme~~ — resolved OQ5: reuse existing handler auth; do NOT add `FLOW_CHECKPOINT_API_KEY`.
- ~~Auto-resume of all suspended flows via one endpoint~~ — resume is per-flow; bulk resume is out of scope.

---

## Implementation Notes

### Key Constraints
- READ FIRST, THEN CODE: this task's contract intentionally defers exact
  class/decorator names to in-repo verification — open `parrot/handlers/crew/`
  (closest sibling) and mirror its base class, auth wiring, and JSON response
  envelope precisely. Record what you found in the completion note.
- Resume endpoint returns 202 immediately; the resumed `run_flow()` runs as a
  tracked background task (register it with the FlowRecoveryService from
  TASK-2054 if available, so shutdown still covers it).
- Error mapping: `FlowLockedError` → 409 Conflict; `CheckpointNotFoundError`
  → 404; unexpected → 500 with logged traceback, generic body.
- DELETE must hit both tiers (ephemeral + durable) and be idempotent.

---

## Acceptance Criteria

- [ ] `test_http_list_history_resume_delete` — all four endpoints behave per scope, incl. 409/404 mappings.
- [ ] Auth wiring matches sibling handlers (same decorator/middleware — assert unauthenticated requests are rejected the same way).
- [ ] Routes registered through the same mechanism as sibling handlers.
- [ ] `pytest packages/ai-parrot/tests/handlers/test_checkpoint_handlers.py -v` passes; `ruff check` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/handlers/test_checkpoint_handlers.py
async def test_list_suspended(handler_client, seeded_stores):
    resp = await handler_client.get("/api/v1/flows/checkpoints?status=suspended")
    assert resp.status == 200 and "f1" in [f["flow_id"] for f in await resp.json()]

async def test_resume_conflict_when_locked(handler_client, locked_flow):
    resp = await handler_client.post("/api/v1/flows/checkpoints/f1/resume", json={})
    assert resp.status == 409

async def test_resume_missing_returns_404(handler_client):
    resp = await handler_client.post("/api/v1/flows/checkpoints/nope/resume", json={})
    assert resp.status == 404
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** for full context
2. **Check dependencies** — TASK-2053 in `tasks/completed/`
3. **Verify the Codebase Contract** — read 2–3 sibling handlers + `parrot/manager/manager.py` registration + `tests/handlers/conftest.py` BEFORE writing any handler code
4. **Update status** in `sdd/tasks/index/agentsflow-state-checkpointing.json` → `"in-progress"`
5. **Implement**, then **verify** all acceptance criteria
6. **Move this file** to `sdd/tasks/completed/` and update index → `"done"`
7. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (autonomous)
**Date**: 2026-08-01
**Notes**: **Codebase Contract correction (recorded above, verified
before implementing)**: FEAT-203 (TASK-1371/1372) relocated
`parrot/handlers/` and `parrot/manager/manager.py` (BotManager) to the
`ai-parrot-server` satellite package — the task's original file paths
(`packages/ai-parrot/src/parrot/handlers/flows/...`) were stale.
Verified directly: `packages/ai-parrot/src/parrot/handlers/` only holds
`dataset_filter_handler.py`/`spatial_filter_handler.py`/etc — no
`crew/`, no BotManager. Implemented in the correct location instead.

Read `handlers/crew/execution_history_handler.py`
(`CrewExecutionHistoryHandler`) as the closest sibling — same shape
(list / detail-by-id / action-on-id / delete over a store-backed
record) — and `handlers/crew/tool_catalog.py` for the
`@is_authenticated()`/`@user_session()` auth-decorator convention (spec
resolved OQ5: reuse existing auth, no new mechanism). Implemented
`FlowCheckpointHandler` (`handlers/flows/checkpoints.py`) with the exact
`BaseView` + `.configure(app, path)` classmethod +
`app.router.add_view()` pattern (action route `/resume` registered
*before* the bare `{flow_id}` route, same ordering discipline as the
sibling). Wired `FlowCheckpointHandler.configure(self.app,
'/api/v1/flows/checkpoints')` into `BotManager.setup()` right after the
crew route block (unconditional — no feature flag, unlike
`ENABLE_CREWS`, since spec doesn't call for one and the route prefix
doesn't collide with anything).

Endpoints: `GET /` (list, `?status=` filter, merges ephemeral + durable
`list_flows()`), `GET /{flow_id}` (history, ephemeral-then-durable
fallback, 404 on empty), `POST /{flow_id}/resume` (`AgentsFlow.resume()`
→ 202 + `asyncio.ensure_future(flow.run_flow())` as a tracked background
task — no extra registration needed for `FlowRecoveryService`, since
`run_flow()` already self-registers when `checkpoint=True`, TASK-2054),
`DELETE /{flow_id}` (both tiers, idempotent).

**Real bug found and fixed during testing (not a spec deviation)**:
`inspect.getsource()`'d `navigator.views.base.BaseView.error()` — it
only maps a fixed status whitelist (400/401/403/404/406/412/428) and
`raise`s the built `HTTPException` (not returns it); anything outside
that whitelist — including 409 and 500, both required by this task's
acceptance criteria — silently degrades to `HTTPBadRequest` (400).
Caught this via a genuinely failing test (`assert 409 == 400`), not by
inspection alone. Fixed by using `self.json_response({...}, status=...)`
(which returns normally and accepts arbitrary status) instead of
`self.error(...)` for the 409 (`FlowLockedError`) and every 500 path;
kept `self.error(...)` only for 400/404 (both in the real whitelist).
This is a correctness fix that would have affected production behavior
too, not just tests.

Added `test_checkpoint_handlers.py` (9 tests): reuses
`conftest.py`'s `_register_package`/`_SERVER_SRC` cross-satellite
loading technique (its own Step 3 pattern, extended with the same
"no-op auth decorators during load" dance since `@is_authenticated()`/
`@user_session()` wrap the handler's methods at class-definition/import
time — a local `_TestFlowCheckpointHandler` subclass adds
`match_parameters()`/`get_arguments()` — verified-identical to the real
navigator implementations via `inspect.getsource` — since the shared
`_TestBaseView` stub doesn't define them and no existing test in this
suite needed them before). `Handler.__new__(Handler)` + `MockRequest`
construction (same idiom as `test_dataset_handler.py`), plus a
`_call_expecting_status()` helper that catches the raised
`web.HTTPException` for the 400/404 paths. Covers list/history/resume/
delete, the 409/404/400/500 mappings, and auth-decorator presence. All
9 pass; combined with the full `tests/flows/checkpoint/` suite: 70
passed, 9 skipped (Redis/pg/mongo, no local services). `ruff check`
clean on all new files; `manager.py`'s diff is 4 purely-additive lines
(import + one `.configure()` call).

**Deviations from spec**: none (the stale-path correction and the
navigator `error()` status-whitelist workaround are documented findings/
fixes, not changes to the spec's endpoint design).
