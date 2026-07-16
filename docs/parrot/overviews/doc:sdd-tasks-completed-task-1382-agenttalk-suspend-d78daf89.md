---
type: Wiki Overview
title: 'TASK-1382: AgentTalk suspend catch → PausedEnvelope'
id: doc:sdd-tasks-completed-task-1382-agenttalk-suspend-catch-paused-envelope-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: Spec §3 Module 4. Today `AgentTalk.post` catches only `AuthorizationRequired`
  and
relates_to:
- concept: mod:parrot.auth.oauth2.models
  rel: mentions
- concept: mod:parrot.core.exceptions
  rel: mentions
- concept: mod:parrot.handlers.agent
  rel: mentions
- concept: mod:parrot.human
  rel: mentions
- concept: mod:parrot.human.suspended_store
  rel: mentions
---

# TASK-1382: AgentTalk suspend catch → PausedEnvelope

**Feature**: FEAT-204 — HITL over Stateless Web Request/Response (AgentTalk HTTP)
**Spec**: `sdd/specs/hitl_web.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1380, TASK-1381
**Assigned-to**: unassigned

---

## Context

Spec §3 Module 4. Today `AgentTalk.post` catches only `AuthorizationRequired` and
returns a structured HTTP-200 `AuthRequiredEnvelope`. When a SUSPEND tool raises
`HumanInteractionInterrupt`, `BasicAgent.ask()` lets it bubble (verified) but the
handler does not catch it → it would 500. This task adds the **suspend catch**:
persist the tool-loop state, rehydrate the interaction, and return a `paused`
envelope the frontend can render — exactly mirroring the `AuthRequiredEnvelope`
precedent.

---

## Scope

- Add `PausedEnvelope(BaseModel)` (modelled on `AuthRequiredEnvelope`) with:
  `status: str = "paused"`, `turn_id: str`, `interaction_id: str`,
  `interaction_type: str`, `question: str`, `context: Optional[str]`,
  `options: Optional[list[dict]]`, `form_schema: Optional[dict]`,
  `default_response: Any`, `deadline: Optional[str]`, `source_agent: Optional[str]`.
- In `AgentTalk.post`, add `except HumanInteractionInterrupt as exc:` **after** the
  existing `except AuthorizationRequired` (inside the same try block around
  `bot.ask()` / `bot.followup()`):
  1. Read `messages`/`tool_call_id`/`agent_name` from the enriched interrupt
     (`exc.messages`, `exc.tool_call_id`, `exc.agent_name`).
  2. Build and `save` a `SuspendedExecution` to `hitl:suspended:{interaction_id}`
     via `SuspendedExecutionStore`, with `ttl = manager._compute_ttl(interaction)`.
  3. Rehydrate the full `HumanInteraction` from `hitl:interaction:{id}` (via the
     manager) to obtain `interaction_type` / `options` / `form_schema` /
     `deadline`.
  4. Build `turn_id` wrapping `interaction_id` (OQ-1 — keep it recoverable; e.g.
     `turn_id == interaction_id` or a documented wrapper).
  5. `return web.json_response(PausedEnvelope(...).model_dump(), status=200)`.
- Do NOT delete `hitl:interaction:{id}`.
- Unit test for `PausedEnvelope` shape; the e2e is TASK-1384.

**NOT in scope**: the resume branch (TASK-1383); the store impl (TASK-1380); the
tool (TASK-1379/1381). Keep changes inside the existing `try/except` around
`bot.ask()`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-server/src/parrot/handlers/agent.py` | MODIFY | `PausedEnvelope` model + `except HumanInteractionInterrupt` branch in `post()` |
| `packages/ai-parrot-server/tests/test_paused_envelope.py` | CREATE | Unit test for envelope shape |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.core.exceptions import HumanInteractionInterrupt          # core/exceptions.py:12
from parrot.auth.oauth2.models import AuthRequiredEnvelope            # already imported at agent.py:46
from parrot.human import get_default_human_manager                   # human/__init__.py
from parrot.human.suspended_store import (SuspendedExecution,
    SuspendedExecutionStore)                                         # created by TASK-1380 (verify path)
# aiohttp web is already imported in agent.py
```

### Existing Signatures to Use
```python
# packages/ai-parrot-server/src/parrot/handlers/agent.py
class AgentTalk(...):
    async def post(self):                                  # 1245
        followup_turn_id = data.pop('turn_id', None)       # 1377
        _hitl_token = set_current_web_session(ws_channel_id or session_id)  # 1405
        try:
            async with agent.session(...) as bot:
                ... response = await bot.ask(question=query, ...)   # 1555
        except AuthorizationRequired as exc:               # 1569  <-- add new except AFTER this
            envelope = AuthRequiredEnvelope(provider=exc.provider, tool_name=exc.tool_name,
                auth_url=exc.auth_url, scopes=exc.scopes or [], message=str(exc))
            return web.json_response(envelope.model_dump(), status=200)     # 1573-1580
        finally:
            reset_current_web_session(_hitl_token)          # 1610

# packages/ai-parrot/src/parrot/core/exceptions.py
class HumanInteractionInterrupt(ParrotError):              # 12
    # .prompt .interaction_id .policy_id .state .tool_call_id .agent_name .messages

# packages/ai-parrot/src/parrot/human/manager.py
def _compute_ttl(self, interaction: HumanInteraction) -> int: ...   # 141
#   to load the interaction: the manager persists it at hitl:interaction:{id} (165);
#   use the manager's own loader (e.g. is_valid_respondent path reads it) — verify the
#   exact public loader method (grep "hitl:interaction" in manager.py) before use.
```

### Does NOT Exist
- ~~`PausedEnvelope`~~ — you are creating it.
- ~~`AgentTalk.post` already handling the interrupt~~ — it does not; only
  `AuthorizationRequired` is caught.
- ~~a manager method named `get_interaction`~~ — DO NOT assume the name; `grep`
  `hitl:interaction` in `manager.py` and use the actual public accessor (or add a
  thin loader if none is public — but verify first).
- ~~`exc.messages` being pre-populated outside a client tool-loop~~ — it is set by
  the client enrichment (claude.py:551-557); if `None`, fall back to `[]` and log.

---

## Implementation Notes

### Pattern to Follow
Copy the `except AuthorizationRequired` block structure verbatim (build a Pydantic
envelope, `return web.json_response(envelope.model_dump(), status=200)`). The
`finally: reset_current_web_session(...)` already runs for any exception — do not
duplicate teardown.

### Key Constraints
- New `except` must sit between `except AuthorizationRequired` and `finally`.
- TTL from `manager._compute_ttl(interaction)` so the suspended blob expires with
  the interaction.
- Async throughout; `self.logger.info` at suspend with `interaction_id`.
- `turn_id` must be recoverable to `interaction_id` by TASK-1383.

### References in Codebase
- `agent.py:1569-1580` — envelope-return precedent.
- `parrot/auth/oauth2/models.py` — `AuthRequiredEnvelope` definition.
- `parrot/human/manager.py:141,165` — TTL + interaction key.

---

## Acceptance Criteria

- [ ] `PausedEnvelope` exists with the fields in scope and `status="paused"`.
- [ ] `AgentTalk.post` catches `HumanInteractionInterrupt` after
      `AuthorizationRequired` and returns HTTP 200 with the envelope.
- [ ] A `SuspendedExecution` is saved to `hitl:suspended:{id}` with TTL from
      `_compute_ttl`; `hitl:interaction:{id}` is NOT deleted.
- [ ] The envelope carries rehydrated `interaction_type`/`options`/`form_schema`
      and a `turn_id` wrapping `interaction_id`.
- [ ] Unit test passes: `pytest packages/ai-parrot-server/tests/test_paused_envelope.py -v`
- [ ] No lint errors: `ruff check packages/ai-parrot-server/src/parrot/handlers/agent.py`

---

## Test Specification

```python
# packages/ai-parrot-server/tests/test_paused_envelope.py
from parrot.handlers.agent import PausedEnvelope

def test_paused_envelope_structured():
    env = PausedEnvelope(turn_id="t1", interaction_id="t1",
        interaction_type="single_choice", question="pick one",
        options=[{"key":"a","label":"A"}], form_schema=None)
    d = env.model_dump()
    assert d["status"] == "paused"
    assert d["options"][0]["key"] == "a"
    assert d["turn_id"] == "t1"
```

---

## Agent Instructions

Standard flow. CRITICAL: `grep "hitl:interaction" packages/.../human/manager.py`
to find the real interaction loader before referencing one. Verify TASK-1380's
module path. Implement, test, move to `sdd/tasks/completed/`, update
`sdd/tasks/index/hitl_web.json` to `done`, fill the Completion Note.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**:
**Date**:
**Notes**:
**Deviations from spec**: none | describe if any
