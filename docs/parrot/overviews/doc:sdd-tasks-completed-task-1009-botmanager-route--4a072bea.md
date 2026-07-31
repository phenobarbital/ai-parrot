---
type: Wiki Overview
title: 'TASK-1009: Register HITL route + call setup_web_hitl in BotManager.setup'
id: doc:sdd-tasks-completed-task-1009-botmanager-route-and-bootstrap-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: This task wires the HITL response handler into the routing layer and ensures
  the bootstrap is called at the right time (§3 Modules 4 and 6 in the spec). The
  modifications are made to `BotManager.setup`, which is the central registration
  point for agent routes.
relates_to:
- concept: mod:parrot.handlers.web_hitl
  rel: mentions
---

# TASK-1009: Register HITL route + call setup_web_hitl in BotManager.setup

**Feature**: FEAT-146 — web-hitl-and-demo-agent
**Spec**: `sdd/specs/web-hitl-and-demo-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S
**Depends-on**: TASK-1006, TASK-1007
**Assigned-to**: unassigned

---

## Context

This task wires the HITL response handler into the routing layer and ensures the bootstrap is called at the right time (§3 Modules 4 and 6 in the spec). The modifications are made to `BotManager.setup`, which is the central registration point for agent routes.

By integrating here, we ensure:
1. The HITL route is registered next to the agent chat route.
2. The bootstrap runs when `user_socket_manager` is available.
3. Web-only deployments (without Telegram) still get HITL support.

---

## Scope

- Locate `BotManager.setup` in `packages/ai-parrot/src/parrot/manager/manager.py` (around line 964).
- Add import: `from parrot.handlers.web_hitl import HITLResponseHandler, setup_web_hitl`.
- Before the method returns, register the route:
  ```python
  app.router.add_view('/api/v1/agents/hitl/respond', HITLResponseHandler)
  ```
  (Place this next to the existing `/api/v1/agents/chat/{agent_id}` routes around line 998.)
- Also call `setup_web_hitl(app)` (same method).
- If `app['user_socket_manager']` is absent, the bootstrap logs a warning but does not fail.
- No other behavioral changes to `BotManager.setup`.

**NOT in scope**:
- Modifying `app.py:setup_app` (the bootstrap is called from BotManager, not separately).
- Changing existing routes or agent behavior.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/manager/manager.py` | MODIFY | Register HITL route and call `setup_web_hitl(app)` in `BotManager.setup`. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.handlers.web_hitl import (                                          # (created in previous tasks)
    HITLResponseHandler,
    setup_web_hitl,
)
```

### Existing Signatures to Use

```python
# parrot/manager/manager.py:964
class BotManager:
    def setup(self, app: web.Application) -> web.Application: ...
    # Existing routes around line 998:
    #   app.router.add_view('/api/v1/agents/chat/{agent_id}', AgentTalk)
    #   app.router.add_view('/api/v1/agents/chat/{agent_id}/{method_name}', AgentTalk)

# parrot/handlers/web_hitl.py
class HITLResponseHandler(BaseView): ...
def setup_web_hitl(app: web.Application) -> None: ...
```

### Does NOT Exist

- No new signature changes for `BotManager.setup`.

---

## Implementation Notes

### Pattern to Follow

Follow the existing route registration pattern in `BotManager.setup`:
```python
app.router.add_view('/api/v1/agents/chat/{agent_id}', AgentTalk)
```

Similarly, for the HITL route:
```python
app.router.add_view('/api/v1/agents/hitl/respond', HITLResponseHandler)
```

### Key Constraints

- Route must be `/api/v1/agents/hitl/respond` (per spec §3 Module 3).
- Call `setup_web_hitl(app)` unconditionally (it handles the case where socket manager is missing).
- Place the route registration next to the existing agent chat routes for clarity.

---

## Acceptance Criteria

- [ ] Import statement added for `HITLResponseHandler` and `setup_web_hitl`.
- [ ] Route `/api/v1/agents/hitl/respond` is registered pointing to `HITLResponseHandler`.
- [ ] `setup_web_hitl(app)` is called in `BotManager.setup`.
- [ ] Route registration is placed next to existing `/api/v1/agents/chat/...` routes.
- [ ] All existing BotManager tests pass: `pytest packages/ai-parrot/tests/manager -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/manager/manager.py`

---

## Test Specification

```python
# No new tests required — route registration is verified by existing BotManager tests.
# Integration tests in TASK-1011 will exercise the endpoint end-to-end.
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/web-hitl-and-demo-agent.spec.md` for full context
2. **Check dependencies** — verify TASK-1006 and TASK-1007 are in `tasks/completed/`
3. **Verify the Codebase Contract** — confirm `BotManager.setup` location and route registration pattern
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** — a surgical 3-line edit (import, route, setup call)
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-1009-botmanager-route-and-bootstrap.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
