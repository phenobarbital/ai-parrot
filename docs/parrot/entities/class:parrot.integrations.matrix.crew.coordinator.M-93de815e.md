---
type: Wiki Entity
title: MatrixCoordinator
id: class:parrot.integrations.matrix.crew.coordinator.MatrixCoordinator
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Manages the pinned status board in the general room.
---

# MatrixCoordinator

Defined in [`parrot.integrations.matrix.crew.coordinator`](../summaries/mod:parrot.integrations.matrix.crew.coordinator.md).

```python
class MatrixCoordinator
```

Manages the pinned status board in the general room.

Creates (or updates) a single pinned message in the general room that
reflects the current state of all registered agents.  Updates are
rate-limited to ``_rate_limit_interval`` seconds to avoid excessive edits.

Args:
    client: A ``MatrixClientWrapper`` (or any object exposing
        ``send_text``, ``edit_message``, and ``client.send_state_event``).
    registry: The shared ``MatrixCrewRegistry``.
    general_room_id: Room ID of the shared general room.
    rate_limit_interval: Minimum seconds between status-board edits.

## Methods

- `async def start(self) -> None` — Create the initial status board message and pin it.
- `async def stop(self) -> None` — Post a shutdown notice to the general room.
- `async def on_agent_join(self, card: MatrixAgentCard) -> None` — Called when an agent joins the crew.
- `async def on_agent_leave(self, agent_name: str) -> None` — Called when an agent leaves the crew.
- `async def on_status_change(self, agent_name: str) -> None` — Called when an agent's status changes.
- `async def refresh_status_board(self) -> None` — Re-render and edit the pinned status board message.
