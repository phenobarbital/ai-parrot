# TASK-2607: Job handles for long-running agent methods

**Feature**: FEAT-477 — Expose an AI-Parrot Agent as an MCP Server
**Spec**: `sdd/specs/mcp-as-agent.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-2600
**Assigned-to**: unassigned

---

## Context

Implements spec §3 **Module 4** — goal **G7**. Agent flows and crews exceed the 300 s
connector tool-call ceiling, so they need a durable handle rather than a blocking call.

Runs alongside TASK-2602/2604/2605 — it depends only on the reification from TASK-2600.

---

## Scope

- Create `packages/ai-parrot-server/src/parrot/mcp/agent_jobs.py`.
- Implement the `start_*` → `job_id`, `*_status`, `*_result` trio as the declared pattern
  for long-running decorated methods.
- `start_*` persists an `AgentJobRecord` and returns a `job_id` **immediately** — it must
  not block on the work.
- Persist to Redis reusing `SuspendedExecutionStore` **semantics**: caller-provided TTL and
  a tombstone on delete.
- `*_status` / `*_result` project a **manifest**, never raw payloads.
- Scope every job record to `(tenant_id, principal)` so one principal cannot read another's
  job.
- Unit tests.

**NOT in scope**: the Redis session/event store for the transport (TASK-2609) — different
concern, different store.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/mcp/agent_jobs.py` | CREATE | `AgentJobRecord` + job store + trio helpers |
| `packages/ai-parrot-server/tests/mcp/test_agent_jobs.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

> VERIFIED against `dev` on 2026-08-31.

### Verified Imports
```python
from parrot.human.suspended_store import SuspendedExecutionStore
from parrot.auth.permission import PermissionContext
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/human/suspended_store.py
class SuspendedExecutionStore:                                    # :64
    def __init__(self, redis: Any) -> None                        # :87
    async def save(self, record, ttl: int) -> None                # :103
    async def load(self, interaction_id) -> Optional[SuspendedExecution]   # :128
    async def delete(self, interaction_id) -> None                # :149
    # key format: hitl:suspended:{interaction_id}
    # delete leaves hitl:interaction:{id} intact (tombstone semantics)
```

### Does NOT Exist
- ~~`JobHandle`~~ — a prior draft's name. The model is `AgentJobRecord` (spec §2).
- ~~`SuspendedExecutionStore` being generic over job types~~ — it is HITL-specific. **Reuse
  its semantics** (TTL, tombstone, key discipline); do not force agent jobs through the
  HITL record type.
- ~~A job runner / scheduler in `parrot.mcp`~~ — none exists; use `asyncio` task management
  and persist state, do not invent a queue framework import.

---

## Implementation Notes

### Key Constraints
- `start_*` returns within the normal inline budget; the work continues out of band.
- `*_result` returns a **manifest projection** — counts, summaries, references — never the
  raw payload, which would blow the response ceiling that TASK-2606 enforces.
- Every read is scoped to the caller's `(tenant_id, principal)`; a mismatched principal gets
  the same response as a missing job (no existence oracle).
- Terminal states are `succeeded | failed | expired`; TTL expiry must be observable as
  `expired`, not as a missing job.
- Async throughout; `self.logger` at state transitions.

### References in Codebase
- `packages/ai-parrot-server/src/parrot/human/suspended_store.py:103` — TTL + save pattern

---

## Acceptance Criteria

- [ ] `start_*` returns a `job_id` without blocking on the work
- [ ] `AgentJobRecord` matches spec §2 Data Models
- [ ] Records persist to Redis with a caller-provided TTL and tombstone on delete
- [ ] `*_status` and `*_result` return manifests, never raw payloads
- [ ] A job is readable only by its own `(tenant_id, principal)`
- [ ] TTL expiry surfaces as `expired`
- [ ] All tests pass: `pytest packages/ai-parrot-server/tests/mcp/test_agent_jobs.py -v`
- [ ] No linting errors

---

## Test Specification

```python
class TestAgentJobs:
    async def test_start_returns_job_id_immediately(self, jobs):
        t0 = time.monotonic()
        job_id = await jobs.start("finance", "long_forecast", {}, pctx)
        assert job_id and (time.monotonic() - t0) < 1.0

    async def test_status_and_result_are_manifests(self, jobs, completed_job):
        res = await jobs.result(completed_job, pctx)
        assert "manifest" in res
        assert "raw" not in res and len(json.dumps(res)) < 10_000

    async def test_job_scoped_to_principal(self, jobs, completed_job, other_pctx):
        assert await jobs.result(completed_job, other_pctx) is None   # same as missing

    async def test_ttl_expiry_reports_expired(self, jobs, fake_redis):
        job_id = await jobs.start("finance", "f", {}, pctx, ttl=1)
        fake_redis.advance(2)
        assert (await jobs.status(job_id, pctx))["status"] == "expired"

    async def test_delete_leaves_tombstone(self, jobs, completed_job, fake_redis):
        await jobs.delete(completed_job)
        assert fake_redis.tombstone_exists(completed_job)
```

---

## Agent Instructions

1. **Read the spec** — §3 Module 4, G7, §2 Data Models.
2. **Check dependencies** — TASK-2600 completed.
3. **Verify the Codebase Contract**. 4. **Update status** → `"in-progress"`.
5. **Implement**. 6. **Verify** acceptance criteria.
7. **Move** to `sdd/tasks/completed/`. 8. **Update index** → `"done"`. 9. **Completion Note**.

---

## Completion Note

**Completed by**: sdd-worker (Claude Sonnet 5)
**Date**: 2026-09-01
**Notes**: `agent_jobs.py` implements `AgentJobRecord` field-for-field per spec
§2 (no extensions — TTL/save-timestamp bookkeeping lives in `AgentJobStore`'s
own persisted envelope, not the model). `AgentJobStore` reuses
`SuspendedExecutionStore`'s semantics without depending on its HITL-specific
`SuspendedExecution` type: caller-provided TTL (the underlying Redis key
survives `ttl + 300s` grace so a post-TTL read can still observe `"expired"`
instead of a bare miss), and `delete()` leaves a short-lived tombstone key
(`{key}:tombstone`) mirroring "tombstone on delete." `AgentJobs` is the
`start_*`/`*_status`/`*_result` trio: `start()` persists a `"pending"` record
and fires an `asyncio.create_task()` background run (no queue framework
exists in `parrot.mcp` — per the Codebase Contract's explicit instruction —
so `asyncio` task management + persisted state is the mechanism), returning
`job_id` immediately (verified <1s in tests). `status()`/`result()` both
scope every read to `(tenant_id, principal)` via `_scoped()`, returning `None`
— indistinguishable from a missing job — on any mismatch. `result()` returns
only `_project_manifest()`'s bounded projection (type/keys/item_count or a
200-char summary), never the raw payload. TTL expiry is promoted lazily on
`load()`: a record still `"pending"`/`"running"` once its intended `ttl` has
elapsed is read back as `"expired"` (a terminal outcome alongside
`"succeeded"`/`"failed"`, per spec) — verified with a resolver that blocks
forever (`asyncio.Event` never set) so the promotion logic, not resolver
timing, is what the test exercises. A `method_resolver` constructor hook
(`(agent_name, tool_name) -> async callable`, `None`-safe — fails the job
with an error manifest) is the integration seam for wiring in the real
exposure-set lookup later, since `agent_mount.py`/`build_exposure_set` are
not in this task's file list. 7/7 new tests pass; full
`packages/ai-parrot-server/tests/mcp/` suite (143 tests, up from 136) stays
green; `ruff check` clean (fixed 3 pre-fix findings: `datetime.UTC` alias, an
unused `noqa`, and `__all__` sort order — all in my own new file).

**Deviations from spec**: none. The `method_resolver` injection point is not
itself named in the spec, but is the natural minimal seam for `start()` to
actually run *something* without this task reaching into `agent_mount.py`
(out of file scope) — same pattern as TASK-2603's `policy_filter` and
TASK-2604's `audit_hook`.
