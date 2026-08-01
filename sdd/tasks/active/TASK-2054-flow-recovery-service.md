# TASK-2054: FlowRecoveryService — graceful-shutdown suspend + dump

**Feature**: FEAT-399 — AgentsFlow State Checkpointing (Two-Tier Persistence)
**Spec**: `sdd/specs/agentsflow-state-checkpointing.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-2053
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 8 (resolved OQ6): on graceful server shutdown, every active
checkpointed flow is suspended and dumped to the durable store within a 15s
configurable deadline; misses are ERROR-logged with their flow_ids (their
last Redis checkpoint stays recoverable until TTL).

---

## Scope

- Implement `recovery.py`: `FlowRecoveryService`:
  - Registry of active checkpointed flows: `register(flow)` / `unregister(flow)`
    (AgentsFlow calls these at `run_flow()` start/finally when
    `checkpoint=True` — add that hookup here, guarded so absence of a service
    is a no-op).
  - `async def shutdown(deadline: float = FLOW_CHECKPOINT_SHUTDOWN_DEADLINE)`:
    `flow.suspend()` for all registered flows in parallel under
    `asyncio.wait(..., timeout=deadline)`; flows not finished by the deadline
    → single `logger.error` listing their flow_ids.
  - `attach_to_app(app: aiohttp.web.Application)` — appends `shutdown` to
    `app.on_shutdown`.
  - `install_signal_handlers(loop)` — SIGTERM/SIGINT for standalone runners
    (best-effort; skip on platforms without signal support).
  - Module-level default instance + accessor, so AgentsFlow and handlers can
    share one registry without a DI framework.
- Unit tests: deadline behavior with slow fake flows, ERROR log content,
  register/unregister lifecycle.

**NOT in scope**: HTTP endpoints (TASK-2055), auto-resume-on-startup
(explicit spec Non-Goal).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/recovery.py` | CREATE | FlowRecoveryService |
| `packages/ai-parrot/src/parrot/bots/flows/core/checkpoint/__init__.py` | MODIFY | Re-export |
| `packages/ai-parrot/src/parrot/bots/flows/flow/flow.py` | MODIFY | register/unregister in run_flow when checkpointing |
| `packages/ai-parrot/tests/flows/checkpoint/test_recovery_service.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.conf import FLOW_CHECKPOINT_SHUTDOWN_DEADLINE       # TASK-2048
from parrot.bots.flows.core.checkpoint.model import FlowCheckpoint  # TASK-2046
# AgentsFlow.suspend() exists after TASK-2053 — signature: async def suspend(self) -> FlowCheckpoint
```

### Existing Signatures to Use
```python
# aiohttp application shutdown hook (aiohttp is a core dependency):
#   app.on_shutdown.append(async_callable(app))
# — the standard aiohttp signal list; the callable receives the Application.

# packages/ai-parrot/src/parrot/bots/flows/flow/flow.py
async def run_flow(self, ctx) -> FlowResult: ...  # line 693 (pre-TASK-2053 numbering) —
    # register/unregister must live in the same try/finally added by TASK-2053;
    # re-verify line numbers AFTER TASK-2053 lands.
```

### Does NOT Exist
- ~~`FlowRecoveryService`~~ — introduced HERE.
- ~~A global flow registry anywhere in `parrot/bots/flows/`~~ — introduced HERE; do not confuse with `parrot.registry` (AgentRegistry — bots, not runs).
- ~~Auto-resume-on-startup~~ — spec Non-Goal; do NOT scan-and-relaunch suspended flows.
- ~~`BotManager` involvement~~ — route/app wiring for handlers is TASK-2055's concern; this task only exposes `attach_to_app`.

---

## Implementation Notes

### Key Constraints
- `shutdown()` must be idempotent and safe with zero registered flows.
- Never raise out of `shutdown()` — aiohttp on_shutdown failures would mask
  other cleanup; log and continue.
- Deadline miss log MUST include every missed flow_id in one ERROR line
  (spec acceptance criterion).
- WeakSet or explicit unregister-in-finally to avoid leaking finished flows.
- `install_signal_handlers` must not double-register and must chain politely
  (add_signal_handler replaces — preserve any existing handler by wrapping,
  or document the limitation in the completion note).

---

## Acceptance Criteria

- [ ] `test_recovery_service_suspends_within_deadline` — fast flows dumped; slow flow → ERROR log listing its flow_id; no exception raised.
- [ ] Registered flows auto-unregister after normal completion.
- [ ] `attach_to_app` triggers suspend on aiohttp AppRunner cleanup (test with a bare `web.Application()`).
- [ ] `pytest packages/ai-parrot/tests/flows/checkpoint/test_recovery_service.py -v` passes; `ruff check` clean.

---

## Test Specification

```python
# packages/ai-parrot/tests/flows/checkpoint/test_recovery_service.py
async def test_shutdown_within_deadline(caplog):
    svc = FlowRecoveryService()
    svc.register(fast_fake_flow)      # suspend() returns quickly
    svc.register(slow_fake_flow)      # suspend() sleeps > deadline
    await svc.shutdown(deadline=0.1)
    assert fast_fake_flow.suspended
    assert "slow-flow-id" in caplog.text and "ERROR" in caplog.text

async def test_idempotent_and_empty():
    svc = FlowRecoveryService()
    await svc.shutdown(deadline=0.1)  # no flows — no error
    await svc.shutdown(deadline=0.1)
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** for full context
2. **Check dependencies** — TASK-2053 in `tasks/completed/`
3. **Verify the Codebase Contract** — re-verify flow.py line numbers post-TASK-2053
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
