---
type: Wiki Overview
title: 'TASK-1300: Hybrid Tool Delegation'
id: doc:sdd-tasks-completed-task-1300-hybrid-tool-delegation-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: During cross-pollination, agents may need to delegate tool execution to a
  peer with
relates_to:
- concept: mod:parrot
  rel: mentions
- concept: mod:parrot.integrations.matrix.appservice
  rel: mentions
- concept: mod:parrot.integrations.matrix.crew
  rel: mentions
- concept: mod:parrot.integrations.matrix.crew.mention
  rel: mentions
- concept: mod:parrot.integrations.matrix.events
  rel: mentions
---

# TASK-1300: Hybrid Tool Delegation

**Feature**: FEAT-195 — Matrix Collaborative Multi-Agent Crew
**Spec**: `sdd/specs/matrix-collaborative-crew.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1295, TASK-1298
**Assigned-to**: unassigned

---

## Context

During cross-pollination, agents may need to delegate tool execution to a peer with
privileged access (e.g., only Agent B has access to a financial database). This task
implements the hybrid delegation flow: post a visible "Asking @peer to..." message in
the room, send a `m.parrot.task` custom event via the AppService, wait for the
`m.parrot.result` response, and post the result as a visible reply-to message.

This bridges the A2A transport concepts (task/result events) into the AppService mode
used by the collaborative crew.

Implements Spec Module 6.

---

## Scope

- Create `parrot/integrations/matrix/crew/delegation.py` with:
  - `DelegationRequest` Pydantic model: requester_name, target_agent, task_description,
    room_id, context.
  - `HybridDelegator` class that:
    1. Posts visible message: "🔧 {requester} is asking @{target} to: {task_description}"
    2. Sends `m.parrot.task` custom event via AppService intent API.
    3. Waits for `m.parrot.result` event (with timeout).
    4. Posts result as a visible reply-to the original request message.
- Extend `MatrixAppService._handle_event()` to also route `m.parrot.task` and
  `m.parrot.result` custom events (currently only handles `EventType.ROOM_MESSAGE`).
- Export `HybridDelegator` from `crew/__init__.py`.
- Write unit tests.

**NOT in scope**: Session orchestrator changes, transport routing, example code.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/integrations/matrix/crew/delegation.py` | CREATE | Hybrid delegation logic |
| `parrot/integrations/matrix/appservice.py` | MODIFY | Extend `_handle_event()` for custom events |
| `parrot/integrations/matrix/crew/__init__.py` | MODIFY | Add `HybridDelegator` export |
| `tests/test_matrix_delegation.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.integrations.matrix.appservice import MatrixAppService  # matrix/__init__.py
from parrot.integrations.matrix.events import ParrotEventType  # events.py:21
from parrot.integrations.matrix.events import TaskEventContent  # events.py
from parrot.integrations.matrix.events import ResultEventContent  # events.py
from parrot.integrations.matrix.crew.mention import build_pill  # crew/mention.py:68
from mautrix.types import EventType, RoomID
from mautrix.appservice import IntentAPI
from pydantic import BaseModel, Field
import asyncio
import logging
```

### Existing Signatures to Use
```python
# parrot/integrations/matrix/appservice.py:287
async def _handle_event(self, event: Event) -> None:
    if event.type != EventType.ROOM_MESSAGE:           # line 291 — ONLY handles messages
        return

# parrot/integrations/matrix/appservice.py:343
def _get_intent(self, mxid: str) -> IntentAPI:

# parrot/integrations/matrix/appservice.py:239
async def send_as_agent(
    self, agent_name: str, room_id: str, message: str
) -> str:

# parrot/integrations/matrix/appservice.py — NEW from TASK-1295:
async def send_reply_as_agent(
    self, agent_name: str, room_id: str, message: str, reply_to_event_id: str
) -> str

async def send_reply_as_bot(
    self, room_id: str, message: str, reply_to_event_id: str
) -> str

# parrot/integrations/matrix/events.py:21
class ParrotEventType:
    TASK = "m.parrot.task"
    RESULT = "m.parrot.result"

# parrot/integrations/matrix/events.py (TaskEventContent)
class TaskEventContent(BaseModel):
    task_id: str
    content: str
    context_id: Optional[str] = None
    target_agent: Optional[str] = None
    skill_id: Optional[str] = None
    metadata: Optional[Dict] = None

# parrot/integrations/matrix/events.py (ResultEventContent)
class ResultEventContent(BaseModel):
    task_id: str
    content: str
    success: bool = True
    error: Optional[str] = None
    artifacts: Optional[List] = None
    metadata: Optional[Dict] = None

# parrot/integrations/matrix/a2a_transport.py:249
class MatrixA2ATransport:
    async def wait_for_result(
        self, room_id: str, task_id: str, *, timeout=60.0
    ) -> Optional[ResultEventContent]:
```

### Does NOT Exist
- ~~`MatrixAppService` custom event routing~~ — `_handle_event()` only handles `ROOM_MESSAGE`
- ~~`MatrixA2ATransport` integration with AppService~~ — A2A uses `MatrixClientWrapper`, NOT `MatrixAppService`
- ~~`HybridDelegator`~~ — this is what we're creating
- ~~`DelegationRequest`~~ — this is what we're creating

---

## Implementation Notes

### Pattern to Follow
```python
class DelegationRequest(BaseModel):
    requester_name: str
    target_agent: str
    task_description: str
    room_id: str
    context: Optional[str] = None


class HybridDelegator:
    def __init__(self, appservice: MatrixAppService, registry: MatrixCrewRegistry):
        self._appservice = appservice
        self._registry = registry
        self._pending: Dict[str, asyncio.Future] = {}
        self.logger = logging.getLogger(__name__)

    async def delegate(
        self,
        request: DelegationRequest,
        timeout: float = 60.0,
    ) -> Optional[str]:
        """Execute hybrid delegation: visible msg + custom event + wait for result."""
        # 1. Post visible message
        target_card = await self._registry.get(request.target_agent)
        pill = build_pill(target_card.mxid, target_card.display_name)
        visible_msg = f"Asking {pill} to: {request.task_description}"
        visible_event_id = await self._appservice.send_as_agent(
            request.requester_name, request.room_id, visible_msg,
        )

        # 2. Send m.parrot.task custom event
        task_id = str(uuid.uuid4())
        task_content = TaskEventContent(
            task_id=task_id,
            content=request.task_description,
            target_agent=request.target_agent,
            context_id=request.context,
        )
        # Send via intent as the requester agent
        ...

        # 3. Wait for m.parrot.result
        result = await self._wait_for_result(task_id, timeout)

        # 4. Post result as reply-to
        if result:
            await self._appservice.send_reply_as_agent(
                request.target_agent, request.room_id,
                result.content, visible_event_id,
            )
        return result.content if result else None

    async def on_custom_event(self, event_type: str, content: dict):
        """Called by AppService when a m.parrot.result event is received."""
        if event_type == ParrotEventType.RESULT:
            result = ResultEventContent(**content)
            future = self._pending.get(result.task_id)
            if future and not future.done():
                future.set_result(result)
```

### Key Constraints
- `_handle_event()` in `appservice.py` must be extended to route `m.parrot.task` and
  `m.parrot.result` to a callback/handler — not just silently drop them.
- The delegation is agent-autonomous: the requesting agent's LLM decides when to
  delegate by @mentioning a peer and describing the task.
- Use `asyncio.Future` for waiting on the result event.
- Timeout must be honored — return None if result not received in time.
- Visible messages ensure the human can follow the delegation flow in the room.

### References in Codebase
- `parrot/integrations/matrix/a2a_transport.py:111-170` — `send_task()`/`send_result()` pattern
- `parrot/integrations/matrix/a2a_transport.py:249` — `wait_for_result()` timeout pattern
- `parrot/integrations/matrix/events.py:21` — custom event type constants
- `parrot/integrations/matrix/appservice.py:287-300` — `_handle_event()` to extend

---

## Acceptance Criteria

- [ ] `DelegationRequest` model created with all fields
- [ ] `HybridDelegator.delegate()` posts visible "Asking @peer..." message
- [ ] `HybridDelegator.delegate()` sends `m.parrot.task` custom event
- [ ] `HybridDelegator` waits for `m.parrot.result` with timeout
- [ ] Result posted as visible reply-to the original request message
- [ ] `MatrixAppService._handle_event()` routes `m.parrot.task` and `m.parrot.result`
- [ ] Timeout returns None gracefully (no crash)
- [ ] `HybridDelegator` exported from `parrot.integrations.matrix.crew`
- [ ] All tests pass: `pytest tests/test_matrix_delegation.py -v`
- [ ] No linting errors: `ruff check parrot/integrations/matrix/crew/delegation.py`

---

## Test Specification

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestDelegationRequest:
    def test_creation(self):
        req = DelegationRequest(
            requester_name="analyst",
            target_agent="db_agent",
            task_description="Query revenue data for Q4",
            room_id="!room:server",
        )
        assert req.target_agent == "db_agent"


class TestHybridDelegator:
    @pytest.fixture
    def delegator(self):
        appservice = AsyncMock()
        registry = AsyncMock()
        return HybridDelegator(appservice=appservice, registry=registry)

    async def test_delegate_posts_visible_message(self, delegator):
        """Visible 'Asking @peer...' message is posted."""
        ...

    async def test_delegate_sends_custom_event(self, delegator):
        """m.parrot.task custom event is sent after visible message."""
        ...

    async def test_delegate_timeout_returns_none(self, delegator):
        """Timeout waiting for result returns None."""
        ...

    async def test_result_posted_as_reply(self, delegator):
        """Result is posted as reply-to the visible request message."""
        ...

    async def test_on_custom_event_resolves_future(self, delegator):
        """Incoming m.parrot.result resolves the pending future."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-1295 and TASK-1298 are in `tasks/completed/`
3. **Verify the Codebase Contract** — read `appservice.py` and `events.py` to confirm signatures
4. **Update status** in `sdd/tasks/index/matrix-collaborative-crew.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-1300-hybrid-tool-delegation.md`
8. **Update index** → `"done"`
9. **Fill in the Completion Note** below

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any

### Completion Note

Created `packages/ai-parrot/src/parrot/integrations/matrix/crew/delegation.py`:
- `DelegationRequest` Pydantic model with all required fields
- `HybridDelegator` class with `delegate()`, `on_custom_event()`, `_send_custom_event()`, `_wait_for_result()`
- `asyncio.Future` pattern for waiting on m.parrot.result events (matches a2a_transport.py pattern)

Modified `packages/ai-parrot/src/parrot/integrations/matrix/appservice.py`:
- Added `_custom_event_callback` attribute to `__init__`
- Added `set_custom_event_callback()` method
- Extended `_handle_event()` to check for m.parrot.TASK and m.parrot.RESULT before the ROOM_MESSAGE filter

Modified `packages/ai-parrot/src/parrot/integrations/matrix/crew/__init__.py`:
- Added `DelegationRequest` and `HybridDelegator` to exports

Created `packages/ai-parrot/tests/test_matrix_delegation.py` with 14 tests.
All 14 tests pass. Lint clean (pre-existing unused imports in appservice.py are out of scope).
