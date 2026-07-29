---
type: Wiki Overview
title: 'TASK-1596: FULL Mode Room Observer'
id: doc:sdd-tasks-completed-task-1596-fullmode-room-observer-md
tags:
- overview
timestamp: '2026-07-16T08:34:12+00:00'
summary: In FULL mode, LiveAvatar manages the LiveKit room. The backend joins as a
relates_to:
- concept: mod:parrot.integrations.liveavatar
  rel: mentions
- concept: mod:parrot.integrations.liveavatar.models
  rel: mentions
- concept: mod:parrot.integrations.liveavatar.output_bridge
  rel: mentions
---

# TASK-1596: FULL Mode Room Observer

**Feature**: FEAT-248 — LiveAvatar FULL Mode speak_text Integration (Backend)
**Spec**: `sdd/specs/liveavatar-fullmode-speaktext.spec.md`
**Status**: pending
**Priority**: low
**Estimated effort**: L (4-8h)
**Depends-on**: TASK-1591, TASK-1592
**Assigned-to**: unassigned

---

## Context

In FULL mode, LiveAvatar manages the LiveKit room. The backend joins as a
passive observer to log events, capture transcripts, and relay structured
outputs to the AgentChat UI via the existing `OutputBridge` / Redis pub/sub
transport.

**GATED by Q-room-token**: This task can only be fully implemented if the
LiveAvatar `/start` response returns a participant token that lets the backend
join the room. If not, implement the observer structure with a stub connection
and document the gate.

Implements spec §3 Module 6.

---

## Scope

- Create `fullmode_observer.py` with `FullModeRoomObserver` class.
- Connects to LiveKit room using `livekit-agents` SDK or raw LiveKit Python SDK.
- Listens for data channel events on `agent-response` topic.
- Forwards structured outputs (transcript, avatar state changes) via `OutputBridge`.
- Graceful shutdown: disconnects from room on session stop.
- Write unit tests (mocked LiveKit connection).

**NOT in scope**: Data channel SEND direction (that's frontend's job via
`avatar.speak_text`), handler endpoints (TASK-1594/1595), package wiring (TASK-1597).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/fullmode_observer.py` | CREATE | Room observer class |
| `packages/ai-parrot-integrations/tests/integrations/liveavatar/test_fullmode_observer.py` | CREATE | Unit tests |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports
```python
from parrot.integrations.liveavatar.models import FullModeSessionHandle  # TASK-1591
from parrot.integrations.liveavatar.output_bridge import OutputBridge  # output_bridge.py:25
```

### Existing Signatures to Use
```python
# packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/output_bridge.py
class OutputBridge:  # line 25
    # Publishes structured outputs to AgentChat UI WS channel
    # Reusable across all phases

# packages/ai-parrot-integrations/src/parrot/integrations/liveavatar/output_transport.py
class RedisBroadcastForwarder:  # Cross-process Redis pub/sub transport
    # Reusable
```

### Does NOT Exist
- ~~`fullmode_observer.py`~~ — does not exist yet; this task creates it
- ~~`FullModeRoomObserver`~~ — does not exist yet
- ~~Backend LiveKit participant token handling for FULL mode~~ — gated by Q-room-token

---

## Implementation Notes

### Pattern to Follow
```python
import logging
from typing import Optional
from parrot.integrations.liveavatar.models import FullModeSessionHandle

logger = logging.getLogger(__name__)


class FullModeRoomObserver:
    """Passive observer for a LiveAvatar FULL mode LiveKit room.

    Joins the room as a non-publishing participant, listens for data
    channel events on the 'agent-response' topic, and relays structured
    outputs via OutputBridge.
    """

    def __init__(
        self,
        handle: FullModeSessionHandle,
        output_bridge: Optional["OutputBridge"] = None,
    ) -> None:
        self._handle = handle
        self._bridge = output_bridge
        self._connected = False

    async def connect(self) -> None:
        """Join the LiveKit room as a passive observer."""
        if not self._handle.livekit_url:
            logger.warning("No livekit_url on handle — Q-room-token may be unresolved")
            return
        # TODO: Connect using livekit Python SDK
        # room = await Room.connect(self._handle.livekit_url, <token>)
        # room.on("data_received", self._on_data)
        self._connected = True

    async def disconnect(self) -> None:
        """Leave the LiveKit room gracefully."""
        self._connected = False

    async def _on_data(self, data: bytes, topic: str) -> None:
        """Handle incoming data channel messages."""
        if topic != "agent-response":
            return
        # Parse JSON envelope: {event_id, event_type, session_id, text}
        # Forward to OutputBridge if available
```

### Key Constraints
- **Q-room-token gate**: If the `/start` response doesn't include a backend
  participant token, `connect()` should log a warning and return (no crash).
- Observer is **passive**: it never publishes audio/video, never sends data
  channel messages.
- Must handle LiveKit disconnections gracefully (reconnect or log and stop).
- The observer lifecycle is tied to the session: created at start, destroyed at stop.

---

## Acceptance Criteria

- [ ] `FullModeRoomObserver` can be instantiated with a `FullModeSessionHandle`
- [ ] `connect()` handles missing `livekit_url` gracefully (logs warning, does not crash)
- [ ] `disconnect()` is idempotent
- [ ] Data channel messages on `agent-response` topic are parsed and forwarded to `OutputBridge`
- [ ] Q-room-token gate is documented in code
- [ ] Tests pass: `pytest packages/ai-parrot-integrations/tests/integrations/liveavatar/test_fullmode_observer.py -v`

---

## Test Specification

```python
import pytest
from parrot.integrations.liveavatar.models import FullModeSessionHandle
from parrot.integrations.liveavatar.fullmode_observer import FullModeRoomObserver


class TestFullModeRoomObserver:
    @pytest.fixture
    def handle(self):
        return FullModeSessionHandle(
            session_id="s1", liveavatar_session_id="la1",
            session_token="tok", ws_url="", agent_name="agent",
            livekit_url="wss://test.livekit.cloud",
            livekit_client_token="eyJ...",
        )

    async def test_connect_no_livekit_url(self):
        """connect() logs warning when livekit_url is empty."""
        handle = FullModeSessionHandle(
            session_id="s1", liveavatar_session_id="la1",
            session_token="tok", ws_url="", agent_name="agent",
        )
        observer = FullModeRoomObserver(handle)
        await observer.connect()
        assert not observer._connected

    async def test_disconnect_idempotent(self, handle):
        """disconnect() can be called multiple times."""
        observer = FullModeRoomObserver(handle)
        await observer.disconnect()
        await observer.disconnect()

    async def test_on_data_filters_topic(self, handle):
        """_on_data ignores non-agent-response topics."""
        observer = FullModeRoomObserver(handle)
        await observer._on_data(b'{}', "other-topic")
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** §3 Module 6 and §8 Open Questions (Q-room-token)
2. **Check dependencies** — TASK-1591 and TASK-1592 must be completed
3. **Check Q-room-token status** — if resolved, implement full connection; if not, implement stub
4. **Create** `fullmode_observer.py` with the observer class
5. **Wire OutputBridge** integration for forwarding data
6. **Write tests** and verify acceptance criteria

---

## Completion Note

*(Agent fills this in when done)*
