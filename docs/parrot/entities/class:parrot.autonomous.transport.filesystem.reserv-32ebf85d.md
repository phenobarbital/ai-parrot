---
type: Wiki Entity
title: ReservationManager
id: class:parrot.autonomous.transport.filesystem.reservation.ReservationManager
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Cooperative resource reservation using JSON files on the filesystem.
---

# ReservationManager

Defined in [`parrot.autonomous.transport.filesystem.reservation`](../summaries/mod:parrot.autonomous.transport.filesystem.reservation.md).

```python
class ReservationManager
```

Cooperative resource reservation using JSON files on the filesystem.

Agents declare which resources they are working on so others can avoid
collisions. Reservations are advisory (cooperative), not enforced at
OS level. They use all-or-nothing semantics: if any requested resource
is held by another agent, the entire acquisition fails.

Resource paths are hashed to SHA-256 prefix filenames to avoid
filesystem path issues.

Args:
    reservations_dir: Path to the reservations directory.
    agent_id: The agent ID that owns reservations from this manager.

## Methods

- `async def acquire(self, paths: List[str], reason: str='', timeout: Optional[float]=None) -> bool` — Acquire reservations on a list of resources (all-or-nothing).
- `async def release(self, paths: List[str]) -> None` — Release reservations on specific resources.
- `async def release_all(self) -> None` — Release all reservations owned by this agent.
- `async def list_active(self) -> List[Dict[str, Any]]` — List all non-expired reservations.
