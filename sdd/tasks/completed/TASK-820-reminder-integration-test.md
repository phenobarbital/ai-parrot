# TASK-820: Integration test — end-to-end reminder with real scheduler

**Feature**: FEAT-115 — Reminder Toolkit for Agents
**Spec**: `sdd/specs/FEAT-115-reminder-toolkit.spec.md`
**Status**: pending
**Priority**: medium
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-818
**Assigned-to**: unassigned

---

## Context

Implements Module 5 of the spec (§3). Exercises the full reminder path against a
real `AsyncIOScheduler` (backed by `MemoryJobStore` keyed as `"redis"` to mirror
production) to validate three properties that unit tests cannot prove:

1. The job **fires** at `run_date` and invokes `deliver_reminder` with the right kwargs.
2. After firing, the job is **removed from the jobstore** automatically (DateTrigger exhausted).
3. Cancelled reminders never invoke the notifier.

No live Redis is required — the fixture binds `MemoryJobStore` to the same
`"redis"` key name the production code uses, so the toolkit does not need
to know it is being tested.

---

## Scope

- Create `packages/ai-parrot/tests/integration/test_reminder_e2e.py`.
- Spin up a real `AsyncIOScheduler` with `MemoryJobStore()` as the `"redis"` jobstore.
- Patch `parrot.tools.reminder._notifier.send_notification` with `AsyncMock`.
- Three tests:
  - `test_end_to_end_reminder_fires_and_cleans_up`
  - `test_cancel_removes_from_jobstore`
  - (Optional but recommended) `test_restart_preserves_pending_reminder` — schedule,
    then pause/resume the scheduler to simulate lifecycle; assert the job is still
    present and fires. Skip if complexity outweighs value for the MVP.

**NOT in scope**:
- Testing against a real Redis instance.
- Testing `JiraSpecialist` wiring (TASK-821).
- Changes to production code.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/integration/test_reminder_e2e.py` | CREATE | End-to-end tests with real scheduler |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.memory import MemoryJobStore
# optional deps — declared by ai-parrot[scheduler]; already installed in dev env
# Module path confirmed against packages/ai-parrot/src/parrot/scheduler/__init__.py:294-309

from parrot.tools.reminder import ReminderToolkit, deliver_reminder
# created by TASK-818
from parrot.auth.permission import PermissionContext, UserSession
# verified: packages/ai-parrot/src/parrot/auth/permission.py:20,80
```

### Scheduler wiring pattern

```python
@pytest.fixture
async def scheduler():
    """AsyncIOScheduler with MemoryJobStore aliased as 'redis' to match prod.

    The toolkit calls scheduler.add_job(..., jobstore='redis'), so we bind
    the name 'redis' to MemoryJobStore for the test.
    """
    s = AsyncIOScheduler(
        jobstores={"default": MemoryJobStore(), "redis": MemoryJobStore()},
        timezone="UTC",
    )
    s.start()
    try:
        yield s
    finally:
        s.shutdown(wait=False)


@pytest.fixture
def sm(scheduler):
    sm = MagicMock()
    sm.scheduler = scheduler  # real scheduler, mocked manager wrapper
    return sm
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/scheduler/__init__.py:331-336 — prod scheduler config
# jobstores={"default": MemoryJobStore(), "redis": RedisJobStore(...)}
# timezone="UTC"
# Tests must match timezone and jobstore key names to reproduce behaviour.
```

### Does NOT Exist

- ~~`parrot.tools.reminder.run_reminder`~~ / ~~`parrot.tools.reminder.fire_reminder`~~ — only `deliver_reminder`.
- ~~`AgentSchedulerManager` exposed as a fixture~~ — this test bypasses the manager and binds the scheduler directly.
- ~~A `fake_redis` library~~ — not needed; MemoryJobStore is sufficient.
- ~~`scheduler.wait_for_job(id)`~~ — no such API on APScheduler. Use `asyncio.sleep` with a tight bound (e.g., 3 seconds for a T+1s reminder).

---

## Implementation Notes

### Test sketches

```python
import asyncio
from datetime import datetime, timezone
from unittest.mock import MagicMock, AsyncMock, patch
import pytest

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.memory import MemoryJobStore

from parrot.auth.permission import PermissionContext, UserSession
from parrot.tools.reminder import ReminderToolkit


@pytest.fixture
async def scheduler():
    s = AsyncIOScheduler(
        jobstores={"default": MemoryJobStore(), "redis": MemoryJobStore()},
        timezone="UTC",
    )
    s.start()
    yield s
    s.shutdown(wait=False)


@pytest.fixture
def toolkit(scheduler):
    sm = MagicMock(); sm.scheduler = scheduler
    return ReminderToolkit(scheduler_manager=sm)


def _pctx(user="user-123"):
    return PermissionContext(
        session=UserSession(user_id=user, tenant_id="acme", roles=frozenset()),
        channel="telegram",
        extra={"telegram_id": 987654321},
    )


@pytest.mark.asyncio
async def test_end_to_end_reminder_fires_and_cleans_up(toolkit, scheduler):
    with patch("parrot.tools.reminder._notifier") as mock_notifier:
        mock_notifier.send_notification = AsyncMock()
        await toolkit._pre_execute("schedule_reminder", _permission_context=_pctx())
        out = await toolkit.schedule_reminder(
            message="hello", delay_seconds=1, channel="telegram"
        )
        rid = out["reminder_id"]
        assert scheduler.get_job(rid, jobstore="redis") is not None

        # Wait long enough for the DateTrigger to fire, then for the executor.
        await asyncio.sleep(2.5)

        mock_notifier.send_notification.assert_awaited_once()
        assert scheduler.get_job(rid, jobstore="redis") is None  # auto-cleanup


@pytest.mark.asyncio
async def test_cancel_removes_from_jobstore(toolkit, scheduler):
    with patch("parrot.tools.reminder._notifier") as mock_notifier:
        mock_notifier.send_notification = AsyncMock()
        pctx = _pctx()
        await toolkit._pre_execute("schedule_reminder", _permission_context=pctx)
        out = await toolkit.schedule_reminder(
            message="x", delay_seconds=60, channel="telegram"
        )
        rid = out["reminder_id"]

        await toolkit._pre_execute("cancel_reminder", _permission_context=pctx)
        result = await toolkit.cancel_reminder(rid)
        assert result == {"status": "cancelled", "reminder_id": rid}
        assert scheduler.get_job(rid, jobstore="redis") is None

        await asyncio.sleep(0.2)  # give the loop a chance
        mock_notifier.send_notification.assert_not_awaited()
```

### Key Constraints

- Use `pytest.mark.asyncio` on all test functions.
- Patch `_notifier` at the module path `parrot.tools.reminder._notifier` so
  `deliver_reminder` picks up the mock at fire time (it reads the module global).
- Keep reminder delays small (1-2s) so tests stay under ~3s each.
- Always `scheduler.shutdown(wait=False)` in fixture teardown so tests don't leak tasks.
- If flakiness appears on `asyncio.sleep(2.5)`, increase slightly — do NOT poll
  `get_job` in a loop (that masks real failures).

### References in Codebase

- `packages/ai-parrot/src/parrot/scheduler/__init__.py:294-336` — production scheduler wiring; the test fixture mirrors it.

---

## Acceptance Criteria

- [ ] `packages/ai-parrot/tests/integration/test_reminder_e2e.py` exists.
- [ ] Tests run green: `pytest packages/ai-parrot/tests/integration/test_reminder_e2e.py -v`.
- [ ] `test_end_to_end_reminder_fires_and_cleans_up` asserts both the notifier call AND job auto-removal.
- [ ] `test_cancel_removes_from_jobstore` asserts the notifier is NEVER awaited after cancellation.
- [ ] Tests do not depend on a real Redis instance.
- [ ] No production code modified by this task.

---

## Agent Instructions

1. Verify TASK-818 is complete and importable.
2. Write the two (optionally three) integration tests.
3. Run them with `-v --log-cli-level=INFO` to confirm scheduler events fire.
4. On green, move to `sdd/tasks/completed/`, update `.index.json`, commit as `sdd: complete TASK-820 — reminder integration test`.
5. If a test is flaky, prefer widening the sleep to 3s before changing timing-sensitive logic; do not mask real bugs.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations, issues encountered.

**Deviations from spec**: none | describe if any

---
**Completed by**: sdd-worker agent
**Date**: 2026-04-22
**Notes**: Created `test_reminder_e2e.py` with 3 tests: fire+cleanup, cancel, and list-by-owner. All pass in 3.5s using MemoryJobStore aliased as "redis". Real scheduler fires deliver_reminder and auto-removes job. No Redis required.

**Deviations from spec**: Added a third test (test_list_reminders_reflects_live_jobstore) beyond the two required.
