---
type: Wiki Entity
title: MatrixCollaborativeSession
id: class:parrot.integrations.matrix.crew.session.MatrixCollaborativeSession
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Stateful session managing one collaborative investigation in a Matrix room.
---

# MatrixCollaborativeSession

Defined in [`parrot.integrations.matrix.crew.session`](../summaries/mod:parrot.integrations.matrix.crew.session.md).

```python
class MatrixCollaborativeSession
```

Stateful session managing one collaborative investigation in a Matrix room.

Orchestrates phased rounds directly via Matrix messages. The Matrix room
is the shared memory — agents communicate by posting messages that others
can see.

Args:
    session_id: Unique identifier for this session (UUID string).
    room_id: Matrix room where the session takes place.
    question: The original question from the ``!investigate`` command.
    config: Collaborative session configuration.
    appservice: Shared ``MatrixAppService`` for sending messages.
    registry: ``MatrixCrewRegistry`` for agent discovery.
    wrappers: Mapping of agent_name → ``MatrixCrewAgentWrapper``.
    server_name: Matrix server domain (e.g. "example.com").

## Methods

- `def phase(self) -> SessionPhase` — Current lifecycle phase of the session.
- `def is_active(self) -> bool` — Whether the session is still in progress (not completed/failed).
- `async def run(self) -> CollaborativeSessionState` — Execute the full session lifecycle.
- `async def handle_inter_agent_message(self, sender_mxid: str, body: str, event_id: str) -> None` — Route an @mention from one agent to another during an active session.
- `async def cancel(self, reason: str='Cancelled by user') -> None` — Cancel the session and post a notice to the room.
