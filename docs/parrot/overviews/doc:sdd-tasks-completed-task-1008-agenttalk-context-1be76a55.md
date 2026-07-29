---
type: Wiki Overview
title: 'TASK-1008: Wire current_web_session in AgentTalk.post'
id: doc:sdd-tasks-completed-task-1008-agenttalk-contextvar-wiring-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: 'This task adds ContextVar wiring to the `AgentTalk.post` request handler
  so that the `current_web_session` ContextVar is set at request entry and reset in
  a `finally` block (§3 Module 5 in the spec). This ensures that any tools invoked
  by the agent (including `WebHumanTool`) can '
relates_to:
- concept: mod:parrot.handlers.web_hitl
  rel: mentions
---

# TASK-1008: Wire current_web_session in AgentTalk.post

**Feature**: FEAT-146 — web-hitl-and-demo-agent
**Spec**: `sdd/specs/web-hitl-and-demo-agent.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: S
**Depends-on**: TASK-1004
**Assigned-to**: unassigned

---

## Context

This task adds ContextVar wiring to the `AgentTalk.post` request handler so that the `current_web_session` ContextVar is set at request entry and reset in a `finally` block (§3 Module 5 in the spec). This ensures that any tools invoked by the agent (including `WebHumanTool`) can access the current web session ID.

The modification is minimal and surgical — it leverages existing `session_id` and `ws_channel_id` extraction code that is already in place.

---

## Scope

- Locate `AgentTalk.post` method in `packages/ai-parrot/src/parrot/handlers/agent.py`.
- After extracting `session_id`/`ws_channel_id` (existing lines 1297, 1381), add:
  ```python
  hitl_token = set_current_web_session(ws_channel_id or session_id)
  try:
      # ... existing post logic ...
  finally:
      reset_current_web_session(hitl_token)
  ```
- Import `set_current_web_session` and `reset_current_web_session` from `parrot.handlers.web_hitl`.
- No other behavioral changes to `AgentTalk.post`.

**NOT in scope**:
- Modifying any other handlers.
- Changing agent logic or tool execution.
- Tests for `AgentTalk` itself (covered by existing test suite).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/handlers/agent.py` | MODIFY | Add ContextVar set/reset in `AgentTalk.post`. |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.handlers.web_hitl import (                                          # (created in TASK-1004)
    set_current_web_session,
    reset_current_web_session,
)
```

### Existing Signatures to Use

```python
# parrot/handlers/agent.py:50
class AgentTalk(BaseView):
    async def post(self): ...                                                   # line 1237
    # Existing session_id extraction at lines 1297, 1381
    # user_id, user_session = await self._get_user_session(data)  # line 1297
    # session_id = user_session  # line 1303
    # ws_channel_id = data.pop('ws_channel_id', None)  # line 1381

# parrot/handlers/web_hitl.py (from TASK-1004)
def set_current_web_session(session: Optional[str]) -> Token: ...
def reset_current_web_session(token: Token) -> None: ...
```

### Does NOT Exist

- No new ContextVar functions beyond those from TASK-1004.

---

## Implementation Notes

### Pattern to Follow

Use the Token-based reset pattern from `parrot/integrations/telegram/context.py`:
```python
token = set_current_web_session(value)
try:
    # ... work that uses the ContextVar ...
finally:
    reset_current_web_session(token)
```

### Key Constraints

- The ContextVar must be set BEFORE any tool execution (after `session_id`/`ws_channel_id` extraction).
- The reset MUST happen in a `finally` block to ensure it runs even on exception.
- The value set is `ws_channel_id or session_id` (prefer WebSocket channel if provided).
- No other modifications to `AgentTalk.post` logic.

---

## Acceptance Criteria

- [ ] `AgentTalk.post` imports `set_current_web_session` and `reset_current_web_session`.
- [ ] ContextVar is set after session extraction and before main POST logic.
- [ ] ContextVar is reset in a `finally` block.
- [ ] Value set is `ws_channel_id or session_id`.
- [ ] All existing AgentTalk tests pass: `pytest packages/ai-parrot/tests/handlers/test_agent.py -v`
- [ ] No linting errors: `ruff check packages/ai-parrot/src/parrot/handlers/agent.py`

---

## Test Specification

```python
# No new tests required — wiring is covered by existing AgentTalk tests.
# The ContextVar isolation test (test_context_var_isolation) in TASK-1004
# ensures that concurrent requests maintain separate ContextVar values.
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/web-hitl-and-demo-agent.spec.md` for full context
2. **Check dependencies** — verify TASK-1004 is in `tasks/completed/`
3. **Verify the Codebase Contract** — confirm `AgentTalk.post` signature and session extraction lines (1297, 1303, 1381)
4. **Update status** in `tasks/.index.json` → `"in-progress"` with your session ID
5. **Implement** — a surgical 5-line edit adding the set/reset pair
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-1008-agenttalk-contextvar-wiring.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
