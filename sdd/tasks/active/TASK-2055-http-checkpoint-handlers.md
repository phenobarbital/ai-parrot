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

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/handlers/flows/__init__.py` | CREATE | Sub-package (if absent — verify first) |
| `packages/ai-parrot/src/parrot/handlers/flows/checkpoints.py` | CREATE | Handler classes |
| (route registration site — locate in `parrot/manager/manager.py`) | MODIFY | Register routes like sibling handlers |
| `packages/ai-parrot/tests/handlers/test_checkpoint_handlers.py` | CREATE | Handler tests |

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

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
