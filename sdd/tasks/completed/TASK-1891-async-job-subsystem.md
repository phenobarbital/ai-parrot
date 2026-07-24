# TASK-1891: Async job subsystem — Redis store, polling route, TTL + watchdog

**Feature**: FEAT-327 — Infographic Render Endpoint — Deterministic Render-as-a-Service
**Spec**: `sdd/specs/infographic-render-endpoint.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1890
**Assigned-to**: unassigned

---

## Context

Module 4 of FEAT-327. `async=true` turns the render into a background job: `202 {job_id}` +
`GET /api/v1/agents/infographic/render/jobs/{job_id}` polling. Resolved decisions: job store
is **Redis** (multi-worker — polling works regardless of which worker rendered), terminal jobs
expire after **1 day** (Redis TTL), and the max-runtime watchdog default is **10 minutes**
(a constant now, replaceable by a resource-computed value later without API changes).

---

## Scope

- Implement a small Redis-backed job store (e.g.
  `packages/ai-parrot-server/src/parrot/handlers/render_jobs.py`): create/update/get
  `RenderJob` records (TASK-1889 model), key prefix `infographic:job:`, client constructed
  like `parrot/memory/redis.py:22-29` (`Redis.from_url(REDIS_HISTORY_URL,
  decode_responses=True, ...)`).
- `async=true` branch in the render dispatch: enqueue → `202 {"job_id": ...}`; render runs as
  an `asyncio` task reusing the TASK-1890 sync flow; task completion writes `done`+result or
  `failed`+structured error and sets the **86400 s TTL**.
- Polling route `GET /api/v1/agents/infographic/render/jobs/{job_id}` (registered with the
  TASK-1890 block): `200` with `RenderJob` state; unknown/expired → `404`.
- **Watchdog**: each job stores a `deadline` (now + max-runtime, default **600 s**, config
  key); poll-time check flips a past-deadline `running` job to `failed` (worker-death
  recovery). Keep the max-runtime resolution behind one function so a future resource-aware
  computation replaces the constant cleanly.
- Unit tests with a Redis test double (fakeredis or an injected fake).

**NOT in scope**: the sync flow itself (TASK-1890), decoding (TASK-1889), docs (TASK-1892).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/render_jobs.py` | CREATE | Redis job store + watchdog |
| `packages/ai-parrot-server/src/parrot/handlers/infographic.py` | MODIFY | async branch + polling dispatch |
| `packages/ai-parrot-server/src/parrot/manager/manager.py` | MODIFY | jobs GET route (with TASK-1890 block) |
| `packages/ai-parrot-server/tests/.../test_render_jobs.py` | CREATE | Unit tests (verify test layout first) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from redis.asyncio import Redis            # pattern: parrot/memory/redis.py:4
from parrot.conf import REDIS_HISTORY_URL  # used by parrot/memory/redis.py:7 (as ..conf)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/memory/redis.py — CLIENT CONSTRUCTION PATTERN ONLY
class RedisConversation(ConversationMemory):                     # line 10
    # Redis.from_url(self.redis_url, decode_responses=True, encoding="utf-8",
    #                socket_connect_timeout=5, socket_timeout=5,
    #                retry_on_timeout=True)                        lines 22-29

# RenderJob model — created by TASK-1889 (handlers/infographic_render.py):
#   job_id, status: pending|running|done|failed, result, error, created_at, deadline
```

### Does NOT Exist
- ~~a generic KV/job store anywhere in `parrot/memory/`~~ — only `ConversationMemory`
  subclasses exist; the job store is NEW code following the client pattern, NOT a subclass of
  `RedisConversation`.
- ~~any job/polling infra for infographics~~ — created HERE.
- ~~a background scheduler/beat process for expiry~~ — expiry is Redis TTL + poll-time
  watchdog check; do NOT add a daemon.
- ~~a resource-aware max-runtime computation~~ — NOT in v1; default constant 600 s behind one
  resolver function (resolved decision: "start with 10").

---

## Implementation Notes

### Key Constraints
- Multi-worker correctness: all state transitions go through Redis (atomic where it matters —
  use `SET ... XX`/watch or a Lua/pipeline if needed for the watchdog flip); never keep
  job state in process memory.
- TTL rule: TTL (86400 s) is set when a job REACHES a terminal state (`done`/`failed`) —
  pending/running jobs carry no expiry (the watchdog handles orphans).
- The `asyncio` render task must capture exceptions into the job record (`failed` +
  structured error) — never let it die silently.
- JSON-serialize `RenderJob` with pydantic `model_dump_json`; `decode_responses=True` client.
- Config keys (TTL, max-runtime) follow the same convention TASK-1889 established for the
  body cap.

### References in Codebase
- `parrot/memory/redis.py:10-29` — client construction to mirror
- `sdd/specs/infographic-render-endpoint.spec.md` §3 Module 4 + §7 Known Risks (worker-death
  scenario)

---

## Acceptance Criteria

- [ ] Implementation complete per scope
- [ ] All tests pass (`pytest` on the created test module)
- [ ] No linting errors (`ruff check` on new/modified files)
- [ ] `async=true` → 202 + job id; poll returns pending/running → done with the same
  negotiated result payload the sync path produces
- [ ] Job state readable from a DIFFERENT store instance (multi-worker simulation)
- [ ] Terminal jobs get 86400 s TTL; expired/unknown job id → 404
- [ ] Past-deadline `running` job flips to `failed` on poll (watchdog); default max-runtime
  600 s behind a single resolver function
- [ ] Render task exceptions land in the job record as structured `failed` errors

---

## Test Specification

```python
# test_render_jobs.py
class TestJobStore:
    async def test_create_and_get_roundtrip(self): ...
    async def test_terminal_state_sets_ttl(self): ...
    async def test_unknown_job_404_semantics(self): ...
    async def test_multiworker_visibility(self): ...      # second store instance sees the job

class TestAsyncBranch:
    async def test_202_and_poll_roundtrip(self, render_app): ...
    async def test_task_exception_becomes_failed(self, render_app): ...
    async def test_watchdog_flips_orphaned_running(self, render_app): ...
```

---

## Agent Instructions

1. **Read the spec**; 2. **Check dependencies** (TASK-1890 in `completed/`); 3. **Verify the
Codebase Contract**; 4. **Update status** in
`sdd/tasks/index/infographic-render-endpoint.json` → `"in-progress"`; 5. **Implement**;
6. **Verify criteria**; 7. **Move file to completed/**; 8. **Update index** → `"done"`;
9. **Completion Note**.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:

**Deviations from spec**: none
