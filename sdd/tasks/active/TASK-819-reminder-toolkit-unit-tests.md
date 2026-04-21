# TASK-819: Unit tests for `ReminderToolkit` and `deliver_reminder`

**Feature**: FEAT-115 — Reminder Toolkit for Agents
**Spec**: `sdd/specs/FEAT-115-reminder-toolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: TASK-818
**Assigned-to**: unassigned

---

## Context

Covers Modules 3 and 4 of the spec (§3). Two test files:

1. `test_reminder_toolkit.py` — mocks the scheduler, drives the three tool methods.
2. `test_deliver_reminder.py` — verifies the top-level coroutine forwards correctly to `NotificationMixin.send_notification`.

Provides the safety net for FEAT-115 before the integration test (TASK-820) and the wiring (TASK-821) go in.

---

## Scope

- Create `packages/ai-parrot/tests/tools/test_reminder_toolkit.py` covering the unit tests listed in §4 of the spec.
- Create `packages/ai-parrot/tests/tools/test_deliver_reminder.py` covering the single spec unit test for `deliver_reminder`.
- Use `unittest.mock.MagicMock` / `AsyncMock` for the scheduler and for `NotificationMixin`.
- Build a reusable `telegram_pctx` fixture that constructs a real `PermissionContext` with `UserSession`.
- Use `pytest.mark.asyncio` for async tests (the project already uses `pytest-asyncio`).

**NOT in scope**:
- Integration test with a real `AsyncIOScheduler` (TASK-820).
- Any production code changes (must go into TASK-818 or TASK-821).
- Wiring into `JiraSpecialist` (TASK-821).

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/tests/tools/test_reminder_toolkit.py` | CREATE | Toolkit behaviour tests (≥13 cases) |
| `packages/ai-parrot/tests/tools/test_deliver_reminder.py` | CREATE | Notifier forwarding test |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.tools.reminder import ReminderToolkit, deliver_reminder
# will exist after TASK-818: packages/ai-parrot/src/parrot/tools/reminder.py

from parrot.auth.permission import PermissionContext, UserSession
# verified: packages/ai-parrot/src/parrot/auth/permission.py:80 (PermissionContext)
# verified: packages/ai-parrot/src/parrot/auth/permission.py:20 (UserSession)
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/auth/permission.py:20
@dataclass(frozen=True)
class UserSession:
    user_id: str
    tenant_id: str | None = None
    roles: frozenset[str] = frozenset()
    # ... (additional fields may exist; verify at task pickup time)

# packages/ai-parrot/src/parrot/auth/permission.py:80
@dataclass
class PermissionContext:
    session: UserSession
    request_id: Optional[str] = None
    channel: Optional[str] = None
    extra: dict[str, Any] = field(default_factory=dict)
```

### Test-running conventions

- pytest + pytest-asyncio are available.
- Async test functions are decorated with `@pytest.mark.asyncio`.
- Test discovery root: `packages/ai-parrot/tests/`.
- Invocation: `source .venv/bin/activate && pytest packages/ai-parrot/tests/tools/test_reminder_toolkit.py packages/ai-parrot/tests/tools/test_deliver_reminder.py -v`.

### Does NOT Exist

- ~~`parrot.tools.reminder.build_reminder`~~ / ~~`parrot.tools.reminder.Reminder`~~ — only `ReminderToolkit` and `deliver_reminder` are exported.
- ~~`ReminderToolkit.add_reminder`~~ — the public method is `schedule_reminder`.
- ~~`PermissionContext.telegram_id` as attribute~~ — it's in `extra`.
- ~~`parrot.auth.session` module~~ — `UserSession` lives in `parrot.auth.permission`.
- ~~A pre-existing fixture `telegram_pctx`~~ — this task creates it; do not reach for a shared conftest.

---

## Implementation Notes

### Fixtures to define locally (conftest-free)

```python
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, timezone
import pytest
from parrot.auth.permission import PermissionContext, UserSession
from parrot.tools.reminder import ReminderToolkit


@pytest.fixture
def mock_sm():
    sm = MagicMock()
    sm.scheduler = MagicMock()
    return sm


def _pctx(user_id="user-123", extra=None):
    return PermissionContext(
        session=UserSession(user_id=user_id, tenant_id="acme", roles=frozenset()),
        channel="telegram",
        extra=extra or {"telegram_id": 987654321},
    )


@pytest.fixture
def toolkit(mock_sm):
    return ReminderToolkit(scheduler_manager=mock_sm)
```

### Cases to implement (test_reminder_toolkit.py)

Minimum 13 tests listed in §4 of the spec:

1. `test_schedule_rejects_both_delay_and_remind_at` — both args → `ValueError`.
2. `test_schedule_rejects_neither_delay_nor_remind_at` — neither → `ValueError`.
3. `test_schedule_uses_delay_seconds` — verify `add_job.call_args.kwargs['run_date']` is ~now + delay in UTC (assert `abs(delta) < 5s`).
4. `test_schedule_uses_absolute_remind_at` — `remind_at="2026-06-01T08:00:00+00:00"` → `add_job` called with matching `run_date`.
5. `test_schedule_telegram_extracts_chat_id_from_pctx` — `recipients == [987654321]`.
6. `test_schedule_email_requires_email_in_pctx` — pctx without email + `channel="email"` → `ValueError`.
7. `test_schedule_slack_and_teams_recipients` — `slack_user_id` / `teams_user_id` extracted from `pctx.extra`.
8. `test_schedule_adds_job_with_redis_jobstore` — verify `jobstore="redis"`, `trigger="date"`, id starting with `reminder-`.
9. `test_schedule_returns_reminder_id_and_fires_at` — response shape has exactly `{reminder_id, fires_at, channel}`.
10. `test_list_filters_by_requested_by` — `get_jobs` returns 3 fake jobs: one owned by `user-123`, one by `user-999`, one non-reminder id. Assert only the first appears.
11. `test_list_only_reminder_ids` — covered by (10); ensure non-`reminder-*` ids excluded.
12. `test_cancel_ownership_check` — fake job with `requested_by="other"` → `PermissionError`. Missing job → `{"status": "not_found"}`.
13. `test_cancel_removes_job` — owned job → `scheduler.remove_job(id, jobstore="redis")` called once.

**How to drive `_pre_execute` in tests**: call it manually before invoking a
method, because `ReminderToolkit` relies on the `_permission_context` being
stashed on `self`:

```python
async def _run(toolkit, pctx, coro_factory):
    await toolkit._pre_execute("schedule_reminder", _permission_context=pctx)
    return await coro_factory()

# Example usage inside a test:
result = await _run(toolkit, pctx, lambda: toolkit.schedule_reminder(
    message="ping", delay_seconds=60, channel="telegram"
))
```

### Cases to implement (test_deliver_reminder.py)

1. `test_deliver_reminder_forwards_to_send_notification` — patch
   `parrot.tools.reminder._notifier.send_notification` with `AsyncMock`,
   call `deliver_reminder(provider="telegram", recipients=[1], message="x",
   requested_by="u", requested_at="2026-04-22T12:00:00+00:00")`, verify the
   mock was awaited once with:
     - `message` starting with `"⏰ *Recordatorio* (programado 2026-04-22T12:00:00+00:00):\n\n"` and ending with `"x"`.
     - `recipients=[1]`.
     - `provider="telegram"`.

### Patch target

`parrot.tools.reminder._notifier.send_notification` (the module-scope singleton).
Use:

```python
@patch("parrot.tools.reminder._notifier")
async def test_...(mock_notifier):
    mock_notifier.send_notification = AsyncMock()
    ...
```

### Key Constraints

- Do NOT import `apscheduler` at all — the scheduler is fully mocked.
- Do NOT hit Redis.
- All assertions must tolerate ±5s drift on `run_date` computations.
- Assertions on `add_job` use `mock_sm.scheduler.add_job.call_args.kwargs`.

### References in Codebase

- `packages/ai-parrot/tests/tools/` — existing test layout.
- `packages/ai-parrot/src/parrot/tools/reminder.py` — code under test (from TASK-818).

---

## Acceptance Criteria

- [ ] Both test files created at the specified paths.
- [ ] `pytest packages/ai-parrot/tests/tools/test_reminder_toolkit.py packages/ai-parrot/tests/tools/test_deliver_reminder.py -v` → all pass.
- [ ] ≥13 test cases in `test_reminder_toolkit.py` (at minimum the list above).
- [ ] ≥1 test case in `test_deliver_reminder.py` covering forwarding + prefix.
- [ ] No production code modified by this task (only test files added).
- [ ] Tests import neither `apscheduler` nor `redis`.

---

## Agent Instructions

1. Verify TASK-818 is in `sdd/tasks/completed/`. If not, stop and escalate.
2. Implement the two test files following the patterns above.
3. Run the tests. If any fail because of small drift in `ReminderToolkit` behaviour, first check whether the drift is acceptable per the spec (§2, §4) before touching tests; if production is wrong, flag it and open a follow-up task — do not fix prod from this task.
4. On green, move this task to `sdd/tasks/completed/`, flip `.index.json` to `done`, commit as `sdd: complete TASK-819 — reminder toolkit unit tests`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations, issues encountered.

**Deviations from spec**: none | describe if any
