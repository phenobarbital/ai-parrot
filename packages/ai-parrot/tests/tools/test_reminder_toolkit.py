"""Unit tests for ReminderToolkit — FEAT-115 / TASK-819.

Tests the three LLM-facing tool methods:
  - schedule_reminder
  - list_my_reminders
  - cancel_reminder

and the private _recipients_for_channel helper.

The APScheduler is fully mocked; no Redis or real scheduler is needed.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.auth.permission import PermissionContext, UserSession
from parrot.tools.reminder import ReminderToolkit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pctx(user_id: str = "user-123", extra: dict | None = None) -> PermissionContext:
    """Build a PermissionContext with sensible defaults."""
    return PermissionContext(
        session=UserSession(
            user_id=user_id,
            tenant_id="acme",
            roles=frozenset(),
        ),
        channel="telegram",
        extra=extra if extra is not None else {"telegram_id": 987654321},
    )


async def _run(toolkit: ReminderToolkit, pctx: PermissionContext, coro_factory):
    """Drive _pre_execute then call the factory coroutine."""
    await toolkit._pre_execute("schedule_reminder", _permission_context=pctx)
    return await coro_factory()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_sm():
    """Stub AgentSchedulerManager exposing a MagicMock .scheduler."""
    sm = MagicMock()
    sm.scheduler = MagicMock()
    return sm


@pytest.fixture
def toolkit(mock_sm):
    """ReminderToolkit wired to a mock scheduler manager."""
    return ReminderToolkit(scheduler_manager=mock_sm)


# ---------------------------------------------------------------------------
# 1. Mutual-exclusion validation
# ---------------------------------------------------------------------------

async def test_schedule_rejects_both_delay_and_remind_at(toolkit):
    """Providing both delay_seconds AND remind_at raises ValueError."""
    pctx = _pctx()
    with pytest.raises(ValueError, match="exactly one"):
        await _run(
            toolkit, pctx,
            lambda: toolkit.schedule_reminder(
                message="x",
                delay_seconds=60,
                remind_at="2026-06-01T08:00:00+00:00",
            ),
        )


async def test_schedule_rejects_neither_delay_nor_remind_at(toolkit):
    """Omitting both delay_seconds AND remind_at raises ValueError."""
    pctx = _pctx()
    with pytest.raises(ValueError, match="exactly one"):
        await _run(
            toolkit, pctx,
            lambda: toolkit.schedule_reminder(message="x"),
        )


# ---------------------------------------------------------------------------
# 2. Fire-time computation
# ---------------------------------------------------------------------------

async def test_schedule_uses_delay_seconds(toolkit, mock_sm):
    """delay_seconds=300 → run_date ≈ now + 5 min (within ±5s)."""
    pctx = _pctx()
    before = datetime.now(timezone.utc)

    await _run(
        toolkit, pctx,
        lambda: toolkit.schedule_reminder(message="ping", delay_seconds=300),
    )

    after = datetime.now(timezone.utc)
    call_kwargs = mock_sm.scheduler.add_job.call_args.kwargs
    run_date: datetime = call_kwargs["run_date"]

    assert abs((run_date - before).total_seconds() - 300) < 5
    assert abs((run_date - after).total_seconds() - 300) < 5


async def test_schedule_uses_absolute_remind_at(toolkit, mock_sm):
    """remind_at string → run_date matches after UTC conversion."""
    pctx = _pctx()
    remind_at = "2026-06-01T08:00:00+00:00"

    await _run(
        toolkit, pctx,
        lambda: toolkit.schedule_reminder(message="ping", remind_at=remind_at),
    )

    call_kwargs = mock_sm.scheduler.add_job.call_args.kwargs
    run_date: datetime = call_kwargs["run_date"]
    expected = datetime(2026, 6, 1, 8, 0, 0, tzinfo=timezone.utc)
    assert run_date == expected


# ---------------------------------------------------------------------------
# 3. Recipient resolution per channel
# ---------------------------------------------------------------------------

async def test_schedule_telegram_extracts_chat_id_from_pctx(toolkit, mock_sm):
    """telegram channel → recipients == [telegram_id from pctx.extra]."""
    pctx = _pctx(extra={"telegram_id": 987654321})
    await _run(
        toolkit, pctx,
        lambda: toolkit.schedule_reminder(message="x", delay_seconds=60, channel="telegram"),
    )
    call_kwargs = mock_sm.scheduler.add_job.call_args.kwargs
    assert call_kwargs["kwargs"]["recipients"] == [987654321]


async def test_schedule_email_requires_email_in_pctx(toolkit):
    """Missing email in pctx + channel='email' → clear ValueError."""
    pctx = _pctx(extra={})  # no email field
    with pytest.raises(ValueError, match="email"):
        await _run(
            toolkit, pctx,
            lambda: toolkit.schedule_reminder(message="x", delay_seconds=60, channel="email"),
        )


async def test_schedule_slack_and_teams_recipients(toolkit, mock_sm):
    """slack/teams channel identifiers are extracted from pctx.extra."""
    # Slack
    pctx_slack = _pctx(extra={"slack_user_id": "U12345"})
    await _run(
        toolkit, pctx_slack,
        lambda: toolkit.schedule_reminder(message="x", delay_seconds=60, channel="slack"),
    )
    slack_kwargs = mock_sm.scheduler.add_job.call_args.kwargs
    assert slack_kwargs["kwargs"]["recipients"] == ["U12345"]

    # Teams
    pctx_teams = _pctx(extra={"teams_user_id": "T99999"})
    await _run(
        toolkit, pctx_teams,
        lambda: toolkit.schedule_reminder(message="x", delay_seconds=60, channel="teams"),
    )
    teams_kwargs = mock_sm.scheduler.add_job.call_args.kwargs
    assert teams_kwargs["kwargs"]["recipients"] == ["T99999"]


# ---------------------------------------------------------------------------
# 4. Job creation in Redis jobstore
# ---------------------------------------------------------------------------

async def test_schedule_adds_job_with_redis_jobstore(toolkit, mock_sm):
    """add_job is called with jobstore='redis', trigger='date', reminder- id."""
    pctx = _pctx()
    await _run(
        toolkit, pctx,
        lambda: toolkit.schedule_reminder(message="x", delay_seconds=30),
    )
    call_kwargs = mock_sm.scheduler.add_job.call_args.kwargs
    assert call_kwargs["jobstore"] == "redis"
    assert call_kwargs["trigger"] == "date"
    assert call_kwargs["id"].startswith("reminder-")


async def test_schedule_kwargs_payload(toolkit, mock_sm):
    """The job kwargs payload contains all five required fields."""
    pctx = _pctx()
    await _run(
        toolkit, pctx,
        lambda: toolkit.schedule_reminder(message="do the thing", delay_seconds=60),
    )
    call_kwargs = mock_sm.scheduler.add_job.call_args.kwargs
    payload = call_kwargs["kwargs"]
    assert "provider" in payload
    assert "recipients" in payload
    assert "message" in payload
    assert payload["message"] == "do the thing"
    assert payload["requested_by"] == "user-123"
    assert "requested_at" in payload


# ---------------------------------------------------------------------------
# 5. Return shape
# ---------------------------------------------------------------------------

async def test_schedule_returns_reminder_id_and_fires_at(toolkit, mock_sm):
    """Response has exactly {reminder_id, fires_at, channel}."""
    pctx = _pctx()
    result = await _run(
        toolkit, pctx,
        lambda: toolkit.schedule_reminder(message="x", delay_seconds=10),
    )
    assert set(result.keys()) == {"reminder_id", "fires_at", "channel"}
    assert result["reminder_id"].startswith("reminder-")
    assert result["channel"] == "telegram"
    # fires_at should be a valid ISO-8601 string
    datetime.fromisoformat(result["fires_at"])


# ---------------------------------------------------------------------------
# 6. list_my_reminders
# ---------------------------------------------------------------------------

def _fake_job(job_id: str, requested_by: str, message: str = "hello") -> MagicMock:
    j = MagicMock()
    j.id = job_id
    j.kwargs = {"requested_by": requested_by, "provider": "telegram", "message": message}
    j.next_run_time = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)
    return j


async def test_list_filters_by_requested_by(toolkit, mock_sm):
    """Only jobs owned by the current user are returned."""
    jobs = [
        _fake_job("reminder-aaa", "user-123", "mine"),
        _fake_job("reminder-bbb", "user-999", "other"),
        _fake_job("some-other-job-ccc", "user-123", "not a reminder"),
    ]
    mock_sm.scheduler.get_jobs.return_value = jobs

    pctx = _pctx(user_id="user-123")
    await toolkit._pre_execute("list_my_reminders", _permission_context=pctx)
    result = await toolkit.list_my_reminders()

    assert len(result) == 1
    assert result[0]["reminder_id"] == "reminder-aaa"
    assert result[0]["message"] == "mine"


async def test_list_only_reminder_ids(toolkit, mock_sm):
    """Jobs without the 'reminder-' prefix are excluded."""
    jobs = [
        _fake_job("reminder-zzz", "user-123"),
        _fake_job("cron-job-001", "user-123"),  # same owner but wrong prefix
    ]
    mock_sm.scheduler.get_jobs.return_value = jobs

    pctx = _pctx(user_id="user-123")
    await toolkit._pre_execute("list_my_reminders", _permission_context=pctx)
    result = await toolkit.list_my_reminders()

    ids = [r["reminder_id"] for r in result]
    assert "cron-job-001" not in ids
    assert "reminder-zzz" in ids


# ---------------------------------------------------------------------------
# 7. cancel_reminder — ownership & not-found
# ---------------------------------------------------------------------------

async def test_cancel_ownership_check(toolkit, mock_sm):
    """Foreign job → PermissionError; missing job → {'status': 'not_found'}."""
    # Foreign job
    foreign_job = _fake_job("reminder-foreign", "user-999")
    mock_sm.scheduler.get_job.return_value = foreign_job

    pctx = _pctx(user_id="user-123")
    await toolkit._pre_execute("cancel_reminder", _permission_context=pctx)
    with pytest.raises(PermissionError):
        await toolkit.cancel_reminder("reminder-foreign")

    # Missing job
    mock_sm.scheduler.get_job.return_value = None
    await toolkit._pre_execute("cancel_reminder", _permission_context=pctx)
    result = await toolkit.cancel_reminder("reminder-ghost")
    assert result == {"status": "not_found", "reminder_id": "reminder-ghost"}


async def test_cancel_removes_job(toolkit, mock_sm):
    """Owned job → scheduler.remove_job called with correct args."""
    owned_job = _fake_job("reminder-mine", "user-123")
    mock_sm.scheduler.get_job.return_value = owned_job

    pctx = _pctx(user_id="user-123")
    await toolkit._pre_execute("cancel_reminder", _permission_context=pctx)
    result = await toolkit.cancel_reminder("reminder-mine")

    mock_sm.scheduler.remove_job.assert_called_once_with("reminder-mine", jobstore="redis")
    assert result == {"status": "cancelled", "reminder_id": "reminder-mine"}
