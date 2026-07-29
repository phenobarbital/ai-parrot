---
type: Wiki Overview
title: 'TASK-1383: AgentTalk resume branch (hitl_response → receive_response → resume)'
id: doc:sdd-tasks-completed-task-1383-agenttalk-resume-branch-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'Spec §3 Module 5. The second new `AgentTalk.post` branch: when a later request'
relates_to:
- concept: mod:parrot.human
  rel: mentions
- concept: mod:parrot.human.models
  rel: mentions
- concept: mod:parrot.human.suspended_store
  rel: mentions
---

# TASK-1383: AgentTalk resume branch (hitl_response → receive_response → resume)

**Feature**: FEAT-204 — HITL over Stateless Web Request/Response (AgentTalk HTTP)
**Spec**: `sdd/specs/hitl_web.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1380, TASK-1382
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 5. The second new `AgentTalk.post` branch: when a later request
carries the human's answer (a `hitl_response` tag), validate it, route it through
`manager.receive_response()` (OQ-3 resolved: always, to keep the HITL ledger
coherent), load the suspended tool-loop state, and call `agent.resume(...)` so the
answer is injected as the `tool_result` of the pending `ask_human` call and the
loop runs to a final `success` reply.

Depends on TASK-1382 because both edit `AgentTalk.post` — serialize to avoid
conflict.

---

## Scope

- Detect a `hitl_response` tag in the request body early in `AgentTalk.post`
  (shape: `hitl_response: {turn_id, value, response_type?}`). Unwrap `turn_id` →
  `interaction_id` (inverse of TASK-1382's wrapping).
- Derive `respondent` from the authenticated session
  (`request.session.get("user_id")`), never from the body. Reject unauthenticated
  (403), mirroring `HITLResponseHandler`.
- `manager.is_valid_respondent(interaction_id, respondent)` gate (403 on fail).
- **Three-state TTL/tombstone check** (Decision B):
  - `hitl:result:{id}` present (`get_result`) → return "already answered" (HTTP
    200 informational; do NOT re-run the loop).
  - `hitl:interaction:{id}` present, no result → **alive** → proceed.
  - neither present → return "that question expired" (HTTP 200 informational).
- On alive: `await manager.receive_response(HumanResponse(interaction_id,
  respondent, response_type, value))`.
- Load `SuspendedExecution` via `SuspendedExecutionStore.load(interaction_id)`;
  build the `state` dict `{session_id, messages, tool_call_id, agent_name}` and
  call `await agent.resume(session_id, user_input=value, state=state)`.
- Return the resumed `AIMessage`/response as the normal `success` reply (a second
  suspend may occur — let it hit the TASK-1382 catch, which already handles it).
- Apply tombstone-before-resume ordering for idempotency (OQ-4): check
  `hitl:result` first; document any lease used.

**NOT in scope**: the store (TASK-1380); the suspend catch + envelope
(TASK-1382); a brand-new route (resume reuses `/api/v1/agents/chat/{agent_id}`).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/agent.py` | MODIFY | Add `hitl_response` detection + resume branch in `post()` |
| `packages/ai-parrot-server/tests/test_agenttalk_resume_unit.py` | CREATE | Unit tests for the 3-state check / auth (mocked manager) |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.human.models import HumanResponse, InteractionType        # human/models.py
from parrot.human import get_default_human_manager                    # human/__init__.py
from parrot.human.suspended_store import SuspendedExecutionStore      # TASK-1380 (verify path)
```

### Existing Signatures to Use
```python
# packages/ai-parrot/src/parrot/human/manager.py
async def is_valid_respondent(self, interaction_id, respondent) -> bool: ...   # 222  (fails closed)
async def get_result(self, ...): ...                                          # 511
def has_pending(self, interaction_id: str) -> bool: ...                       # 1283
async def receive_response(self, response: HumanResponse) -> None: ...        # 580
#   hitl:result:{id} (215), hitl:interaction:{id} (165)

# packages/ai-parrot/src/parrot/human/models.py
class HumanResponse(BaseModel):                                               # 427-475
    interaction_id: str; respondent: str
    response_type: InteractionType; value: Any
    # timestamp/metadata default

# clients resume contract — packages/ai-parrot/src/parrot/clients/*.py
async def resume(self, session_id: str, user_input: str, state: Dict[str, Any]) -> AIMessage: ...
#   claude.py:479 ; base.py:1564 (abstract) ; gpt.py:1129 ; groq/grok/hf/gemma4/claude_agent
#   state requires keys: messages, tool_call_id, agent_name  (used at claude.py:494-509)

# packages/ai-parrot-server/src/parrot/handlers/agent.py
async def post(self):                                # 1245
    followup_turn_id = data.pop('turn_id', None)     # 1377  (reuse the same body-parsing area)
    respondent via self.request.session.get("user_id")  # cf. web_hitl.py:313 for the exact pattern
```

### Does NOT Exist
- ~~a dedicated `/resume` route~~ — resume reuses the chat route via the
  `hitl_response` body tag.
- ~~`agent.resume` that takes the answer positionally other than
  `(session_id, user_input, state)`~~ — match the verified signature exactly.
- ~~`receive_response` returning the resumed answer~~ — it returns `None`; it
  only persists/ledgers. You must separately call `agent.resume(...)`.
- ~~a manager method that both records AND resumes~~ — there is none; record then
  resume in two steps (OQ-3).
- ~~`get_result` being sync~~ — it is `async` (manager.py:511); `await` it.

---

## Implementation Notes

### Pattern to Follow
- Borrow the auth + 3-state + respondent logic shape from `HITLResponseHandler`
  (`web_hitl.py:311-356`) but DO the resume here (the existing handler only
  records). Return informational HTTP-200 JSON for expired / already-answered,
  consistent with the `paused`/`AuthRequired` envelope style.
- Resolve the agent the same way the normal `post()` path resolves it; reuse the
  `agent.session(...)` context if required for `resume`.

### Key Constraints
- `respondent` from session only; reject cross-session (`is_valid_respondent`).
- Tombstone (`hitl:result`) checked BEFORE resume → idempotent double-submit.
- Async throughout; `self.logger` at each branch.
- A second suspend during resume must bubble to the TASK-1382 catch (do not
  swallow `HumanInteractionInterrupt` here).

### References in Codebase
- `web_hitl.py:311-356` — auth/respondent/3-state shape (record-only there).
- `clients/claude.py:479-578` — `resume` injecting `tool_result(tool_call_id)`.
- `autonomous/orchestrator.py:482-610` — `resume_agent` reference flow.

---

## Acceptance Criteria

- [ ] A `hitl_response`-tagged request is detected and unwraps `turn_id` →
      `interaction_id`.
- [ ] Unauthenticated / wrong respondent → 403 (fails closed).
- [ ] 3-state check: result → "already answered" (no re-run); interaction-only →
      resume; neither → "expired".
- [ ] On alive: `receive_response` is called, THEN `agent.resume(session_id,
      value, state)` with `state={session_id,messages,tool_call_id,agent_name}`.
- [ ] Final reply is the resumed `success` response; a second suspend bubbles to
      the TASK-1382 catch.
- [ ] Double-submit does not double-run the tool-loop (tombstone-before-resume).
- [ ] Unit tests pass: `pytest packages/ai-parrot-server/tests/test_agenttalk_resume_unit.py -v`
- [ ] No lint errors: `ruff check packages/ai-parrot-server/src/parrot/handlers/agent.py`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/test_agenttalk_resume_unit.py
# Unit-level: mock manager + store; assert branch behaviour. Full e2e is TASK-1384.

async def test_expired_when_neither_key(mocked):
    # get_result -> None, has_pending -> False  => "expired" informational reply
    ...

async def test_already_answered_tombstone(mocked):
    # get_result -> InteractionResult  => "already answered", resume NOT called
    ...

async def test_cross_session_rejected(mocked):
    # is_valid_respondent -> False => 403
    ...

async def test_alive_records_then_resumes(mocked):
    # interaction present, no result => receive_response called THEN agent.resume called
    ...
```

---

## Agent Instructions

Standard flow. Verify TASK-1382 landed (the suspend catch + `turn_id` wrapping
scheme) and match the inverse unwrap. Confirm the client `resume` signature by
`grep "async def resume"` across `clients/`. Implement, test, move to
`sdd/tasks/completed/`, update `sdd/tasks/index/hitl_web.json` to `done`, fill the
Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
