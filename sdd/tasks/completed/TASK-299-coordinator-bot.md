# TASK-299 — Matrix Crew Coordinator Bot

**Feature**: FEAT-044 (Matrix Multi-Agent Crew Integration)
**Spec**: `sdd/specs/integrations-matrix-multi.spec.md`
**Status**: pending
**Priority**: high
**Effort**: M
**Depends on**: TASK-296, TASK-298
**Parallel**: false
**Parallelism notes**: Imports MatrixCrewRegistry and MatrixAgentCard from TASK-298, uses MatrixClientWrapper for sending/pinning messages.

---

## Objective

Create the `MatrixCoordinator` bot that maintains a pinned status board message in the general room, updating it whenever agent status changes (join, leave, busy, ready, offline).

## Files to Create/Modify

- `parrot/integrations/matrix/crew/coordinator.py` — new file

## Implementation Details

### MatrixCoordinator

```python
class MatrixCoordinator:
    def __init__(
        self,
        client: MatrixClientWrapper,
        registry: MatrixCrewRegistry,
        general_room_id: str,
    ) -> None:
        self._client = client
        self._registry = registry
        self._room_id = general_room_id
        self._status_event_id: str | None = None  # Event ID of pinned message
        self._rate_limit_interval: float = 0.5     # Min seconds between edits
        self._last_update: float = 0.0
        self.logger = logging.getLogger(__name__)
```

### Methods

- `async start()`:
  1. Render initial status board text from `registry.all_agents()`.
  2. Send message to `general_room_id` via `client.send_message()`.
  3. Store the returned event ID in `_status_event_id`.
  4. Pin the message via Matrix API (`m.room.pinned_events` state event).

- `async stop()`:
  1. Send a shutdown notice to the room.
  2. Optionally unpin the status message.

- `async on_agent_join(card: MatrixAgentCard)`:
  1. Log agent join.
  2. Call `refresh_status_board()`.

- `async on_agent_leave(agent_name: str)`:
  1. Log agent leave.
  2. Call `refresh_status_board()`.

- `async on_status_change(agent_name: str)`:
  1. Call `refresh_status_board()`.

- `async refresh_status_board()`:
  1. Rate-limit check: skip if < `_rate_limit_interval` since last update.
  2. Get all agents from registry.
  3. Render status board text (see format in spec section 3.3).
  4. Edit the pinned message using `client.edit_message(_status_event_id, new_text)`.
  5. Update `_last_update` timestamp.

### Status Board Format

```
AI-Parrot Crew -- Agent Status

[ready] @analyst -- Financial Analyst
  Skills: Stock analysis, Financial ratios
[busy: summarizing report] @researcher -- Research Assistant
  Skills: Web search, Document summarization
[ready] @assistant -- General Assistant
  Skills: General Q&A, Task coordination

Last updated: 2026-03-11 14:32 UTC
```

Use `MatrixAgentCard.to_status_line()` from TASK-298 for per-agent rendering.

### Pinning

Use the MatrixClientWrapper or direct mautrix client to set `m.room.pinned_events` state:
```python
await client.client.send_state_event(
    room_id, "m.room.pinned_events", {"pinned": [self._status_event_id]}
)
```

## Acceptance Criteria

- [ ] `start()` sends a status board message and pins it.
- [ ] `refresh_status_board()` edits the pinned message with current agent statuses.
- [ ] Rate limiting prevents excessive edits (min 0.5s between updates).
- [ ] `on_agent_join/leave/status_change` trigger a status board refresh.
- [ ] `stop()` posts a shutdown notice.
