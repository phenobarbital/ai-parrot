# TASK-032: ReservationManager

**Feature**: FEAT-011 — FilesystemTransport
**Spec**: `sdd/specs/filesystem-transport.spec.md`
**Status**: done
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-026
**Assigned-to**: claude-session

---

## Context

The ReservationManager provides cooperative resource reservations. Agents declare which resources (file paths, IDs, etc.) they are working on so others can avoid collisions. Reservations are advisory (cooperative), not enforced at OS level. They use all-or-nothing semantics and TTL-based expiration.

Implements **Module 6** from the spec (Section 7.6 of the proposal).

---

## Scope

- Implement `ReservationManager` with: `acquire()`, `release()`, `release_all()`, `list_active()`
- Resource paths hashed to SHA-256 prefix for filenames
- All-or-nothing acquisition: if any resource is held by another agent, fail entirely
- TTL-based expiration: expired reservations can be overwritten
- Write-then-rename for atomic writes
- Write comprehensive unit tests

**NOT in scope**: `fcntl.flock()` system-level locks, transport orchestration

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `parrot/transport/filesystem/reservation.py` | CREATE | `ReservationManager` implementation |
| `tests/transport/filesystem/test_reservation.py` | CREATE | Unit tests |

---

## Implementation Notes

### Pattern to Follow
See proposal Section 7.6 for the complete reference implementation. Key points:

- `_reservation_path(resource)`: `hashlib.sha256(resource.encode()).hexdigest()[:16] + ".json"`
- `acquire(paths, reason, timeout)`: check all paths first, if any held by another (non-expired), return False. Then write all.
- `release(paths)`: remove reservation files owned by this agent
- `release_all()`: scan all `*.json`, remove those owned by this agent

### Key Constraints
- `aiofiles` for all async I/O
- Write-then-rename for atomic writes
- Reservation JSON: `resource`, `agent_id`, `reason`, `acquired_at`, `expires_at`
- All-or-nothing: no partial acquisitions
- Check `expires_at` before declaring conflict

### References in Codebase
- Proposal Section 7.6 — full `ReservationManager` implementation

---

## Acceptance Criteria

- [ ] `acquire()` returns True when all resources are available
- [ ] `acquire()` returns False when any resource is held by another active agent
- [ ] All-or-nothing: failed acquire leaves no partial reservations
- [ ] `release()` removes specific reservation files
- [ ] `release_all()` removes all reservations for this agent
- [ ] Expired reservations are treated as available
- [ ] `list_active()` returns only non-expired reservations
- [ ] Tests pass: `pytest tests/transport/filesystem/test_reservation.py -v`

---

## Test Specification

```python
# tests/transport/filesystem/test_reservation.py
import pytest
from parrot.transport.filesystem.reservation import ReservationManager


@pytest.fixture
def res_a(tmp_path):
    return ReservationManager(tmp_path / "reservations", "agent-a")


@pytest.fixture
def res_b(tmp_path):
    return ReservationManager(tmp_path / "reservations", "agent-b")


class TestReservationManager:
    @pytest.mark.asyncio
    async def test_acquire_and_release(self, res_a):
        ok = await res_a.acquire(["file_a.csv"], reason="processing")
        assert ok is True
        await res_a.release(["file_a.csv"])
        active = await res_a.list_active()
        assert len(active) == 0

    @pytest.mark.asyncio
    async def test_all_or_nothing(self, res_a, res_b):
        ok1 = await res_a.acquire(["file_a.csv", "file_b.csv"])
        assert ok1 is True
        ok2 = await res_b.acquire(["file_b.csv", "file_c.csv"])
        assert ok2 is False
        # file_c.csv must NOT be reserved
        active = await res_b.list_active()
        resources = {r["resource"] for r in active}
        assert "file_c.csv" not in resources

    @pytest.mark.asyncio
    async def test_ttl_expiry(self, res_a, res_b):
        ok1 = await res_a.acquire(["file.csv"], timeout=0.001)
        assert ok1 is True
        import asyncio
        await asyncio.sleep(0.1)
        # Expired, so agent-b can acquire
        ok2 = await res_b.acquire(["file.csv"])
        assert ok2 is True

    @pytest.mark.asyncio
    async def test_release_all(self, res_a):
        await res_a.acquire(["a.csv", "b.csv", "c.csv"])
        await res_a.release_all()
        active = await res_a.list_active()
        assert len(active) == 0

    @pytest.mark.asyncio
    async def test_same_agent_re_acquire(self, res_a):
        ok1 = await res_a.acquire(["file.csv"])
        assert ok1 is True
        ok2 = await res_a.acquire(["file.csv"])
        assert ok2 is True  # Same agent can re-acquire
```

---

## Agent Instructions

When you pick up this task:

1. **Read the spec** at `sdd/specs/filesystem-transport.spec.md` for full context
2. **Check dependencies** — verify TASK-026 is completed
3. **Update status** in `sdd/tasks/.index.json` to `"in-progress"`
4. **Implement** following the scope and notes above
5. **Verify** all acceptance criteria are met
6. **Move this file** to `sdd/tasks/completed/TASK-032-reservation-manager.md`
7. **Update index** status to `"done"`
8. **Fill in the Completion Note** below

---

## Completion Note

**Completed by**: claude-session
**Date**: 2026-02-23
**Notes**: Implemented ReservationManager with acquire(), release(), release_all(), and list_active(). SHA-256 prefix hashed filenames, all-or-nothing acquisition, TTL-based expiration, write-then-rename atomicity, same-agent re-acquire support. 9 unit tests pass covering acquire/release, all-or-nothing, TTL expiry, release_all, re-acquire, expired filtering, ownership protection, data format, and empty listing.

**Deviations from spec**: none
