---
type: Wiki Overview
title: 'TASK-1295: Reply-to Threading Support'
id: doc:sdd-tasks-completed-task-1295-reply-to-threading-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The collaborative session requires agents to post reply-to messages so that
relates_to:
- concept: mod:parrot.integrations.matrix.appservice
  rel: mentions
- concept: mod:parrot.integrations.matrix.crew.mention
  rel: mentions
---

# TASK-1295: Reply-to Threading Support

**Feature**: FEAT-195 — Matrix Collaborative Multi-Agent Crew
**Spec**: `sdd/specs/matrix-collaborative-crew.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

The collaborative session requires agents to post reply-to messages so that
cross-pollination conversations appear as threaded replies in Matrix clients.
Currently only `m.replace` (edit) relations are implemented. This task adds
`m.in_reply_to` support to the AppService and mention utilities.

Implements Spec Module 1.

---

## Scope

- Add `send_reply_as_agent()` method to `MatrixAppService` that sends a message
  as a virtual agent MXID with `m.in_reply_to` relation set.
- Add `send_reply_as_bot()` method to `MatrixAppService` for coordinator replies.
- Add a `send_reply()` helper in `mention.py` (or a new `threading.py`) that
  builds the `m.relates_to` content dict with `m.in_reply_to`.
- Extend `_AppServiceBotClient` in `transport.py` with a `send_reply()` method.
- Write unit tests for all new methods.

**NOT in scope**: Collaborative session logic, config changes, agent-to-agent routing.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/integrations/matrix/appservice.py` | MODIFY | Add `send_reply_as_agent()` and `send_reply_as_bot()` |
| `parrot/integrations/matrix/crew/mention.py` | MODIFY | Add reply-to content builder helper |
| `parrot/integrations/matrix/crew/transport.py` | MODIFY | Extend `_AppServiceBotClient` with `send_reply()` |
| `tests/test_matrix_reply_to.py` | CREATE | Unit tests for reply-to support |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.integrations.matrix.appservice import MatrixAppService  # matrix/__init__.py
from parrot.integrations.matrix.crew.mention import parse_mention, build_pill  # crew/__init__.py
from mautrix.types import EventID, MessageType, RoomID, TextMessageEventContent, UserID  # mautrix
from mautrix.appservice import IntentAPI  # mautrix
```

### Existing Signatures to Use
```python
# parrot/integrations/matrix/appservice.py:239
async def send_as_agent(
    self, agent_name: str, room_id: str, message: str
) -> str:  # returns event_id

# parrot/integrations/matrix/appservice.py:263
async def send_as_bot(self, room_id: str, message: str) -> str

# parrot/integrations/matrix/appservice.py:343
def _get_intent(self, mxid: str) -> IntentAPI:

# parrot/integrations/matrix/appservice.py:160
self._registered_agents: Dict[str, str]  # name → mxid

# parrot/integrations/matrix/crew/transport.py:305
class _AppServiceBotClient:
    async def send_text(self, room_id: str, text: str) -> str:    # line 317
    async def edit_message(self, room_id: str, event_id: str, new_text: str) -> str:  # line 329

# parrot/integrations/matrix/crew/mention.py:68
def build_pill(mxid: str, display_name: str) -> str:
```

### Does NOT Exist
- ~~`MatrixAppService.send_reply_as_agent()`~~ — this is what we're building
- ~~`m.in_reply_to` support anywhere~~ — only `m.replace` (edit) exists
- ~~`mention.send_reply()`~~ — no reply helper exists yet

---

## Implementation Notes

### Pattern to Follow
```python
# The m.in_reply_to relation structure per Matrix spec:
content = TextMessageEventContent(
    msgtype=MessageType.TEXT,
    body=text,
)
content["m.relates_to"] = {
    "m.in_reply_to": {
        "event_id": reply_to_event_id
    }
}
# Send via intent.send_message(room_id, content)
```

### Key Constraints
- Must use the IntentAPI (virtual user identity), not the raw client.
- The `send_reply_as_agent()` method should mirror `send_as_agent()` signature
  but add a `reply_to_event_id: str` parameter.
- Test with mocked IntentAPI — no live homeserver needed.

### References in Codebase
- `parrot/integrations/matrix/appservice.py:239` — `send_as_agent()` pattern to follow
- `parrot/integrations/matrix/crew/crew_wrapper.py:172-188` — existing `m.relates_to` usage (for edits)

---

## Acceptance Criteria

- [ ] `MatrixAppService.send_reply_as_agent(agent_name, room_id, message, reply_to_event_id)` works
- [ ] `MatrixAppService.send_reply_as_bot(room_id, message, reply_to_event_id)` works
- [ ] `_AppServiceBotClient.send_reply(room_id, text, reply_to_event_id)` works
- [ ] Reply-to content contains correct `m.in_reply_to` relation
- [ ] All tests pass: `pytest tests/test_matrix_reply_to.py -v`
- [ ] No linting errors: `ruff check parrot/integrations/matrix/`

---

## Test Specification

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestReplyToSupport:
    @pytest.fixture
    def mock_appservice(self):
        """Mock MatrixAppService with intent API."""
        ...

    async def test_send_reply_as_agent_sets_relation(self, mock_appservice):
        """send_reply_as_agent includes m.in_reply_to in content."""
        event_id = await mock_appservice.send_reply_as_agent(
            "analyst", "!room:server", "reply text", "$orig_event"
        )
        # Verify the sent content has m.relates_to.m.in_reply_to
        ...

    async def test_send_reply_as_bot_sets_relation(self, mock_appservice):
        """send_reply_as_bot includes m.in_reply_to in content."""
        ...

    async def test_send_reply_unregistered_agent_raises(self, mock_appservice):
        """send_reply_as_agent raises ValueError for unknown agent."""
        with pytest.raises(ValueError, match="not registered"):
            await mock_appservice.send_reply_as_agent(
                "unknown", "!room:server", "text", "$event"
            )

    async def test_bot_client_send_reply(self):
        """_AppServiceBotClient.send_reply delegates correctly."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify `Depends-on` tasks are in `tasks/completed/`
3. **Verify the Codebase Contract** — before writing ANY code:
   - Confirm every import in "Verified Imports" still exists (`grep` or `read` the source)
   - Confirm every class/method in "Existing Signatures" still has the listed attributes
   - If anything has changed, update the contract FIRST, then implement
   - **NEVER** reference an import, attribute, or method not in the contract without verifying it exists
4. **Update status** in `sdd/tasks/index/matrix-collaborative-crew.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-1295-reply-to-threading.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: sdd-worker (claude-sonnet-4-6)
**Date**: 2026-05-26
**Notes**: Implemented send_reply_as_agent() and send_reply_as_bot() on MatrixAppService
using m.in_reply_to relation. Added build_reply_content() helper to mention.py. Added
send_reply() to _AppServiceBotClient in transport.py. All 7 tests pass. Files are at
packages/ai-parrot/src/parrot/integrations/matrix/appservice.py,
packages/ai-parrot/src/parrot/integrations/matrix/crew/mention.py,
packages/ai-parrot/src/parrot/integrations/matrix/crew/transport.py, and
packages/ai-parrot/tests/test_matrix_reply_to.py.

**Deviations from spec**: none
