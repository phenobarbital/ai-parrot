# TASK-324: Chat Integration State Management

**Feature**: Handoff Tool for Integrations Agents
**Spec**: `sdd/specs/handoff-tool-for-integrations-agents.spec.md`
**Status**: in-progress
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-052
**Assigned-to**: antigravity

---

## Context

> Connects the chat integrations (Telegram, Matrix, Teams) with the orchestrator's new pause/resume feature. Tracks states so that intermediate replies from users don't spin up new workflows but instead resume pending handoffs.
> Implements spec Section 3.3.

---

## Scope

- Implement session tracking in `parrot/integrations/core/state.py` or equivalent base class.
- Provide a persistent store (e.g., Redis) wrapper to track if `{user_id}:{chat_id}` is in a `suspended` execution state.
- During incoming message handling, check the state.
  - If suspended: Route the message into `AutonomousOrchestrator.resume_agent(session, text)`. Use the response to reply natively.
  - If normal: Route as a standard new request or continuation of existing conversation.
- Wire up at least one platform (e.g., Telegram) logic loop to correctly forward the handoff prompt to the user when an execution suspends.

**NOT in scope**: Fixing unrelated integrations bugs.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/integrations/core/state.py` | MODIFY/CREATE | State persistence layer mapping chat to suspended tasks. |
| `parrot/integrations/telegram/handler.py` (or similar) | MODIFY | Update message interception routing to respect pending states. |

---

## Implementation Notes

- Be extremely careful about state leaks. Ensure that pending states have a TTL (e.g., 10 minutes) so a user isn't stuck if they simply ignore the bot's question forever.
- State mapping keys often depend on the context: `chat_id` and `user_id` are critical keys.

---

## Acceptance Criteria

- [ ] A session state manager supports marking a user/chat context as "waiting for handoff".
- [ ] Expiring / TTL logic prevents infinite waiting states.
- [ ] Telegram or equivalent integration intercepts messages for "waiting" users and feeds them into resume calls instead of normal queries.
- [ ] Integration successfully sends the `HandoffTool` prompt verbatim to the user via chat API.
- [ ] Complete end-to-end integration tests / mocks proving the message routing works correctly.

---

## Test Specification

```python
# tests/integrations/test_integration_state_handoff.py
import pytest
# ... imports ...

@pytest.mark.asyncio
async def test_integration_intercepts_handoff_reply():
    # 1. Setup mock chat integration with a mocked state store showing "waiting for handoff"
    # 2. Simulate incoming text message.
    # 3. Assert message is processed as a resume context, NOT a new prompt context.
    pass
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** (`sdd/specs/handoff-tool-for-integrations-agents.spec.md`) for full context.
2. **Update status** in `tasks/.index.json` → `"in-progress"`.
3. **Implement** following the scope and notes above.
4. **Verify** all acceptance criteria are met.
5. **Move this file** to `sdd/tasks/completed/TASK-053-chat-integration-state.md`.
6. **Update index** → `"done"`.
7. **Fill in the Completion Note** below.

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-03-13
**Notes**:
- Added `InMemoryStateStore` fallback to `IntegrationStateManager` so it works without Redis (store param now optional).
- Fixed `TelegramAgentWrapper.handle_message()` and `_process_group_query()` to catch `HumanInteractionInterrupt`, send prompt to user, and store suspended state.
- Added 3 new tests: in-memory store default, TTL expiry, and full handoff intercept flow.

**Deviations from spec**:
- Used in-memory store fallback instead of requiring Redis injection since the Telegram wrapper didn't have a Redis client available. Production deployments can pass a Redis store explicitly.
