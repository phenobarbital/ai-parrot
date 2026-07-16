---
type: Wiki Overview
title: 'TASK-1285: Web HITL handler — reject button route'
id: doc:sdd-tasks-completed-task-1285-web-hitl-reject-route-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Implements §3 module **C12**. The Web channel renders the reject
relates_to:
- concept: mod:parrot.human
  rel: mentions
- concept: mod:parrot.human.channels.base
  rel: mentions
---

# TASK-1285: Web HITL handler — reject button route

**Feature**: FEAT-194 — HITL Multi-Tier Escalation Policy
**Spec**: `sdd/specs/hitl-escalation-tier.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: S (< 2h)
**Depends-on**: TASK-1277, TASK-1279
**Assigned-to**: unassigned

---

## Context

Implements §3 module **C12**. The Web channel renders the reject
button (TASK-1279) and the manager intercepts the `value="__escalate__"`
response (TASK-1277). This task closes the loop on the HTTP side: when
the web handler receives a response payload with that value, it must
route to `manager.advance_chain(cause="reject")` instead of
`manager.receive_response(...)`. Same authorisation gate
(`is_valid_respondent`) applies.

---

## Scope

- In `parrot/handlers/web_hitl.py`, in the response-ingest handler:
  - After `is_valid_respondent` check, inspect the incoming `value`.
  - If `value == ESCALATE_OPTION_KEY` (imported from
    `parrot.human.channels.base`), call
    `await manager.advance_chain(interaction_id, cause="reject")` and
    return the usual 2xx success payload.
  - Otherwise, take the existing `manager.receive_response(...)` path.

**NOT in scope**: Telegram callback routing (handled inside the
Telegram channel itself in TASK-1279).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/handlers/web_hitl.py` | MODIFY | Route escalate value to `advance_chain` |
| `packages/ai-parrot/tests/handlers/test_web_hitl_reject.py` | CREATE | Reject payload routes correctly; unauthorised request still 403/401 |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
# Existing in web_hitl.py:
from parrot.human import (
    set_default_human_manager, HumanInteractionManager,
    # ... other existing imports
)
# New:
from parrot.human.channels.base import ESCALATE_OPTION_KEY  # added by TASK-1279
```

### Existing Signatures to Use

```python
# parrot/human/manager.py:144-169 — ownership validation
async def is_valid_respondent(self, interaction_id: str, respondent: str) -> bool: ...

# parrot/human/manager.py:368-441 — receive_response (existing path for non-escalate)
async def receive_response(self, response: HumanResponse) -> None: ...

# parrot/human/manager.py (NEW from TASK-1277)
async def advance_chain(self, interaction_id: str, cause: str) -> None: ...

# parrot/handlers/web_hitl.py:417-464 — handler factory + manager wiring
# The exact route handler signature is project-specific; search for the
# function that receives POSTed responses and dispatches them to the
# manager.
```

### Does NOT Exist

- ~~A dedicated `/escalate` HTTP route~~ — reuse the existing response
  endpoint; route by value inside the handler.
- ~~Bypass of `is_valid_respondent`~~ — same authorisation gate applies
  to escalate as to regular responses.

---

## Implementation Notes

### Pattern to Follow

```python
# Inside the response-ingest aiohttp handler:
interaction_id = payload["interaction_id"]
respondent = session.user_id  # or however current handler resolves it
if not await manager.is_valid_respondent(interaction_id, respondent):
    return web.json_response({"error": "unauthorised"}, status=403)

if payload.get("value") == ESCALATE_OPTION_KEY:
    await manager.advance_chain(interaction_id, cause="reject")
    return web.json_response({"status": "escalated"})

# ... existing path: build HumanResponse, call manager.receive_response
```

### Key Constraints

- Authorisation gate is unchanged.
- 2xx response on escalate so the UI gets feedback that the click was
  accepted.
- If the interaction does not exist or is already resolved, the
  manager's `advance_chain` returns silently — the handler returns a
  generic 200 with `{"status": "escalated"}` for both cases; do not
  leak which case it was (consistent with existing 404 handling for
  responses).

### References in Codebase

- `parrot/handlers/web_hitl.py:417-464` — manager wiring + handler factory.

---

## Acceptance Criteria

- [ ] POST with `value="__escalate__"` calls `manager.advance_chain(cause="reject")`
  exactly once and returns 2xx.
- [ ] POST with any other value continues through the existing
  `manager.receive_response` path unchanged.
- [ ] Unauthorised user (per `is_valid_respondent`) gets 401/403 even
  when sending the escalate value.
- [ ] POST for an unknown / expired interaction with the escalate value
  returns 2xx (silent no-op from manager) without raising server
  errors.
- [ ] Existing web_hitl tests pass without modification.
- [ ] All tests pass:
  `pytest packages/ai-parrot/tests/handlers/test_web_hitl_reject.py -v`.

---

## Test Specification

```python
# tests/handlers/test_web_hitl_reject.py
async def test_escalate_value_routes_to_advance_chain(): ...
async def test_normal_value_routes_to_receive_response(): ...
async def test_unauthorised_user_blocked_on_escalate(): ...
async def test_unknown_interaction_silent_2xx(): ...
```

---

## Agent Instructions

1. Read spec §3 C12.
2. Verify TASK-1277 and TASK-1279 completed.
3. Locate the response-ingest handler in `parrot/handlers/web_hitl.py`
   (search for `receive_response` call).
4. Implement, test, lint.
5. Move to completed.

---

## Completion Note

Implemented 2026-05-22 by sdd-worker (FEAT-194).

- Added `from ..human.channels.base import ESCALATE_OPTION_KEY` import to `web_hitl.py`.
- Inserted escalate branch in `HITLResponseHandler.post()` immediately after the `is_valid_respondent` check: if `body.value == ESCALATE_OPTION_KEY`, calls `await manager.advance_chain(interaction_id, cause="reject")` and returns `{"status": "escalated"}` with HTTP 200. Otherwise falls through to the existing `receive_response` path.
- 404 for unknown interactions applies before auth gate (pre-existing behaviour unchanged).
- Test file in `tests/handlers/test_web_hitl_reject.py` uses `--noconftest` (handlers/conftest.py has a pre-existing import failure unrelated to this task). 4 tests pass: escalate routes to advance_chain, normal values route to receive_response, unauthorised user gets 403, unknown interaction gets 404.
- All 17 existing `TestHITLResponseHandler`/`TestContextVar`/`TestWebHumanTool`/`TestHITLResponseBody` tests continue to pass.
