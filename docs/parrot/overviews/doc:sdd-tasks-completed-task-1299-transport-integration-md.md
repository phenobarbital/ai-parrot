---
type: Wiki Overview
title: 'TASK-1299: Transport Integration'
id: doc:sdd-tasks-completed-task-1299-transport-integration-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: The collaborative session orchestrator (TASK-1298) exists but is not wired
  into the
relates_to:
- concept: mod:parrot.integrations.matrix.crew.config
  rel: mentions
- concept: mod:parrot.integrations.matrix.crew.mention
  rel: mentions
- concept: mod:parrot.integrations.matrix.crew.session
  rel: mentions
- concept: mod:parrot.integrations.matrix.crew.session_models
  rel: mentions
---

# TASK-1299: Transport Integration

**Feature**: FEAT-195 — Matrix Collaborative Multi-Agent Crew
**Spec**: `sdd/specs/matrix-collaborative-crew.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-1298
**Assigned-to**: unassigned

---

## Context

The collaborative session orchestrator (TASK-1298) exists but is not wired into the
Matrix message flow. This task modifies `MatrixCrewTransport.on_room_message()` to
detect `!investigate` commands, create/manage `MatrixCollaborativeSession` instances,
and route inter-agent @mentions through an active session instead of the normal path
(selective self-filter bypass).

Implements Spec Module 5.

---

## Scope

- Modify `MatrixCrewTransport.on_room_message()` to:
  1. Detect `!investigate <question>` prefix from human users.
  2. Reject concurrent sessions in the same room (one active session per room).
  3. Create `MatrixCollaborativeSession` and run it.
  4. Selectively bypass the agent self-filter (`sender in self._agent_mxids`) when
     the sender is an agent posting an @mention during an active session.
- Add `_active_sessions: Dict[str, MatrixCollaborativeSession]` to `MatrixCrewTransport`.
- Add `_is_collaborative_command(body: str) -> Optional[str]` helper.
- Ensure existing `@agent question` routing is completely unaffected.
- Write unit tests for command detection, session lifecycle, and routing changes.

**NOT in scope**: Session orchestrator internals (TASK-1298), tool delegation, example code.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/integrations/matrix/crew/transport.py` | MODIFY | Add `!investigate` handling, session management, selective self-filter bypass |
| `tests/test_matrix_transport_collaborative.py` | CREATE | Unit tests for transport integration |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.integrations.matrix.crew.session import MatrixCollaborativeSession  # created in TASK-1298
from parrot.integrations.matrix.crew.session_models import SessionPhase  # created in TASK-1297
from parrot.integrations.matrix.crew.config import CollaborativeConfig  # created in TASK-1296
from parrot.integrations.matrix.crew.mention import parse_mention  # crew/mention.py:19
```

### Existing Signatures to Use
```python
# parrot/integrations/matrix/crew/transport.py:214
class MatrixCrewTransport:
    _agent_mxids: set[str]                              # line 43
    _wrappers: Dict[str, MatrixCrewAgentWrapper]        # line 41
    _room_to_agent: Dict[str, str]                      # line 42
    _config: MatrixCrewConfig                           # line 37
    _appservice: Optional[object]                       # line 38
    _coordinator: Optional[MatrixCoordinator]           # line 39
    _registry: MatrixCrewRegistry                       # line 40

    async def on_room_message(                          # line 214
        self, room_id: str, sender: str, body: str, event_id: str
    ) -> None:
        if sender in self._agent_mxids:                 # line 237 — SELF-FILTER
            return

# parrot/integrations/matrix/crew/config.py:91
class MatrixCrewConfig(BaseModel):
    homeserver_url: str
    server_name: str
    # collaborative: Optional[CollaborativeConfig] = None  # added by TASK-1296

# parrot/integrations/matrix/crew/mention.py:19
def parse_mention(body: str, server_name: str) -> Optional[str]:
```

### Does NOT Exist
- ~~`MatrixCrewTransport._active_sessions`~~ — this is what we're adding
- ~~`MatrixCrewTransport.broadcast_message()`~~ — no broadcast method
- ~~`MatrixCrewTransport._is_collaborative_command()`~~ — this is what we're adding

---

## Implementation Notes

### Pattern to Follow
```python
# In MatrixCrewTransport.__init__(), add:
self._active_sessions: Dict[str, MatrixCollaborativeSession] = {}

# Modified on_room_message flow:
async def on_room_message(self, room_id, sender, body, event_id):
    # 1. Check if this is an inter-agent message during active session
    if sender in self._agent_mxids:
        session = self._active_sessions.get(room_id)
        if session and session.is_active:
            # Check for @mention — if present, route through session
            mentioned = parse_mention(body, self._config.server_name)
            if mentioned:
                await session.handle_inter_agent_message(sender, body, event_id)
                return
        return  # Normal self-filter: drop non-mention agent messages

    # 2. Check for !investigate command (human message)
    question = self._is_collaborative_command(body)
    if question:
        collab = self._config.collaborative
        if not collab:
            return  # collaborative not configured
        if room_id in self._active_sessions:
            await self._appservice.send_as_bot(
                room_id, "A collaborative session is already active in this room."
            )
            return
        session = MatrixCollaborativeSession(
            session_id=str(uuid.uuid4()),
            room_id=room_id,
            question=question,
            config=collab,
            appservice=self._appservice,
            registry=self._registry,
            wrappers=self._wrappers,
            server_name=self._config.server_name,
        )
        self._active_sessions[room_id] = session
        try:
            await session.run()
        finally:
            del self._active_sessions[room_id]
        return

    # 3. Normal routing (existing code unchanged)
    ...
```

### Key Constraints
- The self-filter bypass is the most sensitive change. Only allow agent messages through
  when: (a) there IS an active session in the room, AND (b) the message contains an @mention.
- `_is_collaborative_command()` checks if body starts with `config.collaborative.command_prefix`.
- Must check `self._config.collaborative is not None` before creating a session.
- Session cleanup in `finally` block — always remove from `_active_sessions`.
- Existing `@agent question` routing (dedicated room, @mention, default agent) MUST
  remain completely unaffected for non-collaborative messages.

### References in Codebase
- `parrot/integrations/matrix/crew/transport.py:214-280` — current `on_room_message()` flow
- `parrot/integrations/matrix/crew/transport.py:237` — self-filter line to modify
- `parrot/integrations/matrix/crew/mention.py:19` — `parse_mention()` for @mention detection

---

## Acceptance Criteria

- [ ] `!investigate <question>` triggers collaborative session creation
- [ ] Second `!investigate` during active session is rejected with a message
- [ ] Agent @mentions during active session are routed through session
- [ ] Agent messages without @mentions during active session are still filtered
- [ ] Agent messages in rooms with no active session are still filtered (unchanged)
- [ ] Normal `@agent question` routing is completely unaffected
- [ ] Session is removed from `_active_sessions` on completion or failure
- [ ] `collaborative: null` config (missing section) → `!investigate` is ignored
- [ ] All tests pass: `pytest tests/test_matrix_transport_collaborative.py -v`
- [ ] No linting errors: `ruff check parrot/integrations/matrix/crew/transport.py`

---

## Test Specification

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestInvestigateCommand:
    def test_detect_command(self):
        """_is_collaborative_command detects !investigate prefix."""
        ...

    def test_detect_custom_prefix(self):
        """Custom command_prefix is respected."""
        ...

    def test_non_command_ignored(self):
        """Regular messages don't trigger collaborative sessions."""
        ...


class TestTransportCollaborativeRouting:
    @pytest.fixture
    def transport(self):
        """MatrixCrewTransport with collaborative config."""
        ...

    async def test_investigate_creates_session(self, transport):
        """!investigate from human creates and runs a session."""
        ...

    async def test_concurrent_session_rejected(self, transport):
        """Second !investigate in same room rejected while session active."""
        ...

    async def test_no_collaborative_config_ignores_command(self, transport):
        """Without collaborative config, !investigate is a normal message."""
        ...

    async def test_agent_mention_routed_during_session(self, transport):
        """Agent @mention during active session bypasses self-filter."""
        ...

    async def test_agent_no_mention_filtered_during_session(self, transport):
        """Agent message without @mention during active session is still filtered."""
        ...

    async def test_normal_routing_unaffected(self, transport):
        """@agent question routing works identically with collaborative config present."""
        ...

    async def test_session_cleanup_on_failure(self, transport):
        """Session removed from _active_sessions even on exception."""
        ...
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at the path listed above for full context
2. **Check dependencies** — verify TASK-1298 is in `tasks/completed/`
3. **Verify the Codebase Contract** — read `transport.py` to confirm `on_room_message()` signature
4. **Update status** in `sdd/tasks/index/matrix-collaborative-crew.json` → `"in-progress"`
5. **Implement** following the scope, codebase contract, and notes above
6. **Verify** all acceptance criteria are met
7. **Move this file** to `tasks/completed/TASK-1299-transport-integration.md`
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

Modified `packages/ai-parrot/src/parrot/integrations/matrix/crew/transport.py`:
- Added `_active_sessions: Dict[str, MatrixCollaborativeSession] = {}` to `__init__`
- Added `import uuid` and `from .session import MatrixCollaborativeSession`
- Modified `on_room_message()` to handle: (1) inter-agent self-filter bypass for @mentions during active sessions, (2) `!investigate` command detection with session creation/cleanup in `finally` block
- Added `_is_collaborative_command(body) -> Optional[str]` helper

Created `packages/ai-parrot/tests/test_matrix_transport_collaborative.py` with 17 tests.
All acceptance criteria met. Lint clean. 17/17 tests pass.
