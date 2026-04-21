# TASK-818: Implement `parrot/tools/reminder.py` — `deliver_reminder` + `ReminderToolkit`

**Feature**: FEAT-115 — Reminder Toolkit for Agents
**Spec**: `sdd/specs/FEAT-115-reminder-toolkit.spec.md`
**Status**: pending
**Priority**: high
**Estimated effort**: M (2-4h)
**Depends-on**: none
**Assigned-to**: unassigned

---

## Context

Foundation task for FEAT-115. Creates the new module `parrot/tools/reminder.py`
with:

1. A module-scope coroutine `deliver_reminder(...)` that APScheduler will invoke
   when a reminder fires. It wraps `NotificationMixin.send_notification(...)`.
2. A `ReminderToolkit(AbstractToolkit)` with three LLM-facing async methods:
   `schedule_reminder`, `list_my_reminders`, `cancel_reminder`.

Implements Module 1 of the spec (§3 "Module Breakdown").

---

## Scope

- Create `packages/ai-parrot/src/parrot/tools/reminder.py`.
- Implement `deliver_reminder` at **module scope** (not a method, not a closure).
- Implement `ReminderToolkit` inheriting `AbstractToolkit`, with:
  - `__init__(self, scheduler_manager, **kwargs)` that stores the manager reference.
  - `_pre_execute(self, tool_name, **kwargs)` that stashes `kwargs['_permission_context']` on `self` so bound methods can read it.
  - `schedule_reminder(message, delay_seconds=None, remind_at=None, channel='telegram')` — mutual-exclusion validation, recipient resolution, `scheduler.add_job(...)` call, returns `{reminder_id, fires_at, channel}`.
  - `list_my_reminders()` — filters `scheduler.get_jobs(jobstore='redis')` by `job.id.startswith('reminder-')` and `job.kwargs['requested_by'] == caller_user_id`.
  - `cancel_reminder(reminder_id)` — ownership check, `scheduler.remove_job(id, jobstore='redis')`.
  - A private helper `_recipients_for_channel(channel, pctx)` that extracts the recipient from `pctx.extra` for telegram/email/slack/teams.
- Use `NotificationMixin()` at module scope so `deliver_reminder` can reuse one instance.

**NOT in scope**:
- Unit tests (TASK-819).
- Integration test (TASK-820).
- Wiring into `JiraSpecialist` (TASK-821).
- Any change to `parrot/scheduler/`, `parrot/notifications/`, `parrot/scheduler/models.py`, or `parrot/scheduler/functions/__init__.py`.

---

## Files to Create / Modify

| File | Action | Description |
|---|---|---|
| `packages/ai-parrot/src/parrot/tools/reminder.py` | CREATE | Module with `deliver_reminder` + `ReminderToolkit` |

---

## Codebase Contract (Anti-Hallucination)

### Verified Imports

```python
from parrot.tools.toolkit import AbstractToolkit
# verified: packages/ai-parrot/src/parrot/tools/toolkit.py:168

from parrot.notifications import NotificationMixin
# verified: packages/ai-parrot/src/parrot/notifications/__init__.py:55
```

`PermissionContext` is **not** imported at runtime in this module — only
accessed via duck-typing through `kwargs['_permission_context']`. If a type
hint is desired, use a `TYPE_CHECKING` guard:

```python
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from parrot.auth.permission import PermissionContext
# verified: packages/ai-parrot/src/parrot/auth/permission.py:80
```

### Existing Signatures to Use

```python
# packages/ai-parrot/src/parrot/tools/toolkit.py:168
class AbstractToolkit(ABC):
    tool_prefix: Optional[str] = None                # line 219 — set to "reminder" if desired
    prefix_separator: str = "_"                      # line 222
    def __init__(self, **kwargs): ...                # line 224 — always super().__init__(**kwargs)
    async def _pre_execute(self, tool_name: str, **kwargs) -> None: ...  # line 261 — override me
    async def _post_execute(self, tool_name: str, result, **kwargs): ... # line 276 — leave default

# packages/ai-parrot/src/parrot/notifications/__init__.py:55
class NotificationMixin:
    async def send_notification(                     # line 128
        self,
        message: Union[str, Any],
        recipients: Union[List[Actor], Actor, Channel, Chat, str, List[str]],
        provider: Union[str, NotificationProvider] = NotificationProvider.EMAIL,
        subject: Optional[str] = None,
        report: Optional[Any] = None,
        template: Optional[str] = None,
        with_attachments: bool = True,
        **kwargs,
    ) -> Dict[str, Any]: ...

# packages/ai-parrot/src/parrot/auth/permission.py:80
@dataclass
class PermissionContext:
    session: UserSession                             # line 117
    channel: Optional[str] = None                    # line 119
    extra: dict[str, Any] = field(default_factory=dict)  # line 120
    @property
    def user_id(self) -> str:                        # line 123
        return self.session.user_id
```

### APScheduler external API used

```python
# external — apscheduler.schedulers.asyncio.AsyncIOScheduler
scheduler.add_job(
    func,                             # module-scope coroutine reference
    trigger="date",
    run_date=<datetime UTC>,
    kwargs={...},                     # serialized with job
    id="reminder-<uuid>",
    jobstore="redis",
    replace_existing=False,
)                                     # → apscheduler.job.Job
scheduler.get_jobs(jobstore="redis")  # → list[Job]
scheduler.get_job(job_id, jobstore="redis")  # → Job | None
scheduler.remove_job(job_id, jobstore="redis")  # → None
```

### Does NOT Exist

- ~~`parrot.scheduler.AgentSchedulerManager.add_reminder`~~ — no such method. Use `scheduler.add_job` directly.
- ~~`parrot.scheduler.functions.SendReminderCallback`~~ — intentionally NOT added. Reminders bypass `CALLBACK_REGISTRY`.
- ~~`parrot.scheduler.ScheduleType.REMINDER`~~ — no such enum value. Reminders use plain `trigger="date"`.
- ~~`NotificationMixin.send_reminder`~~ — not a method. Use `send_notification(provider=...)`.
- ~~`PermissionContext.telegram_id`~~ — not a top-level field. Read `pctx.extra['telegram_id']`.
- ~~`AbstractToolkit.add_tool(...)`~~ — toolkits expose tools via method introspection, not `add_tool`. See `toolkit.py:168` docstring.
- ~~`self._current_pctx` set automatically on the toolkit~~ — this attribute exists on `AbstractTool` (the tool wrapper) at `packages/ai-parrot/src/parrot/tools/abstract.py:132`, **not** on the toolkit. To access pctx from a bound method, override `_pre_execute` and stash it on `self`:
  ```python
  async def _pre_execute(self, tool_name, **kwargs):
      self._pctx = kwargs.get("_permission_context")
  ```
  Do NOT expect `_permission_context` to be forwarded as a parameter to the bound method — it is `pop()`ed at `parrot/tools/abstract.py:391`.

---

## Implementation Notes

### Reference implementation sketch

```python
"""One-time reminder tooling for agents — FEAT-115."""
from __future__ import annotations
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, TYPE_CHECKING

from parrot.tools.toolkit import AbstractToolkit
from parrot.notifications import NotificationMixin

if TYPE_CHECKING:
    from parrot.auth.permission import PermissionContext

# Module-scope notifier — safe to share; NotificationMixin is stateless.
_notifier = NotificationMixin()


async def deliver_reminder(
    *,
    provider: str,
    recipients: list,
    message: str,
    requested_by: str,
    requested_at: str,
) -> None:
    """Top-level coroutine invoked by APScheduler when a reminder fires.

    Kept at module scope so APScheduler can serialize the job reference
    by dotted path. MUST NOT be a method, closure, or lambda.
    """
    prefix = f"⏰ *Recordatorio* (programado {requested_at}):\n\n"
    await _notifier.send_notification(
        message=prefix + message,
        recipients=recipients,
        provider=provider,
    )


class ReminderToolkit(AbstractToolkit):
    """LLM-facing tools to schedule, list, and cancel one-time reminders."""

    tool_prefix = "reminder"  # optional — makes tool names reminder_schedule_reminder etc.

    def __init__(self, scheduler_manager, **kwargs):
        super().__init__(**kwargs)
        self._sm = scheduler_manager
        self._pctx: "PermissionContext | None" = None

    async def _pre_execute(self, tool_name: str, **kwargs) -> None:
        self._pctx = kwargs.get("_permission_context")

    async def schedule_reminder(
        self,
        message: str,
        delay_seconds: int | None = None,
        remind_at: str | None = None,
        channel: str = "telegram",
    ) -> dict[str, Any]:
        if (delay_seconds is None) == (remind_at is None):
            raise ValueError("Provide exactly one of delay_seconds or remind_at")

        run_at = (
            datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)
            if delay_seconds is not None
            else datetime.fromisoformat(remind_at).astimezone(timezone.utc)
        )

        pctx = self._pctx
        if pctx is None:
            raise ValueError("schedule_reminder requires an active PermissionContext")

        recipients = self._recipients_for_channel(channel, pctx)
        reminder_id = f"reminder-{uuid.uuid4()}"

        self._sm.scheduler.add_job(
            deliver_reminder,
            trigger="date",
            run_date=run_at,
            kwargs={
                "provider": channel,
                "recipients": recipients,
                "message": message,
                "requested_by": str(pctx.session.user_id),
                "requested_at": datetime.now(timezone.utc).isoformat(),
            },
            id=reminder_id,
            jobstore="redis",
            replace_existing=False,
        )
        self.logger.info(
            "Scheduled %s for user=%s fires_at=%s channel=%s",
            reminder_id, pctx.session.user_id, run_at.isoformat(), channel,
        )
        return {
            "reminder_id": reminder_id,
            "fires_at": run_at.isoformat(),
            "channel": channel,
        }

    async def list_my_reminders(self) -> list[dict[str, Any]]:
        pctx = self._pctx
        if pctx is None:
            raise ValueError("list_my_reminders requires an active PermissionContext")
        me = str(pctx.session.user_id)
        jobs = self._sm.scheduler.get_jobs(jobstore="redis")
        return [
            {
                "reminder_id": j.id,
                "fires_at": j.next_run_time.isoformat() if j.next_run_time else None,
                "channel": j.kwargs.get("provider"),
                "message": j.kwargs.get("message"),
            }
            for j in jobs
            if j.id.startswith("reminder-") and j.kwargs.get("requested_by") == me
        ]

    async def cancel_reminder(self, reminder_id: str) -> dict[str, Any]:
        pctx = self._pctx
        if pctx is None:
            raise ValueError("cancel_reminder requires an active PermissionContext")
        me = str(pctx.session.user_id)
        job = self._sm.scheduler.get_job(reminder_id, jobstore="redis")
        if job is None:
            return {"status": "not_found", "reminder_id": reminder_id}
        if job.kwargs.get("requested_by") != me:
            raise PermissionError("Cannot cancel a reminder belonging to another user")
        self._sm.scheduler.remove_job(reminder_id, jobstore="redis")
        self.logger.info("Cancelled %s by user=%s", reminder_id, me)
        return {"status": "cancelled", "reminder_id": reminder_id}

    def _recipients_for_channel(self, channel: str, pctx) -> list:
        ex = pctx.extra or {}
        if channel == "telegram":
            val = ex.get("telegram_id") or ex.get("chat_id")
            if not val:
                raise ValueError("No telegram_id/chat_id in PermissionContext for Telegram reminder")
            return [val]
        if channel == "email":
            email = ex.get("email") or getattr(pctx.session, "email", None)
            if not email:
                raise ValueError("No email available to deliver the reminder")
            return [email]
        if channel == "slack":
            val = ex.get("slack_user_id") or ex.get("slack_channel")
            if not val:
                raise ValueError("No Slack identifier available")
            return [val]
        if channel == "teams":
            val = ex.get("teams_user_id") or ex.get("teams_conversation_id")
            if not val:
                raise ValueError("No Teams identifier available")
            return [val]
        raise ValueError(f"Unsupported channel: {channel}")
```

### Key Constraints

- Async throughout — all toolkit methods and `deliver_reminder` are `async def`.
- `deliver_reminder` MUST be at module scope. Do not make it a method or wrap in a lambda.
- `_notifier = NotificationMixin()` also at module scope; never capture it in a closure passed to `add_job`.
- `run_date` always in UTC. `datetime.fromisoformat(remind_at).astimezone(timezone.utc)`.
- Logs at schedule / cancel via `self.logger` (already initialized by `AbstractToolkit.__init__`).
- Do NOT accept `requested_by` as a parameter from the LLM — it is derived from `pctx.session.user_id` server-side.

### References in Codebase

- `packages/ai-parrot/src/parrot/tools/toolkit.py:168` — `AbstractToolkit` base class.
- `packages/ai-parrot/src/parrot/tools/toolkit.py:151-155` — pattern showing how `_permission_context` is surfaced through `_pre_execute`.
- `packages/ai-parrot/src/parrot/bots/jira_specialist.py:580-614` — existing toolkit registration pattern (used in TASK-821, not here).
- `packages/ai-parrot/src/parrot/scheduler/__init__.py:312-321` — Redis jobstore config (already live; do NOT redefine).

---

## Acceptance Criteria

- [ ] `packages/ai-parrot/src/parrot/tools/reminder.py` exists and is importable: `from parrot.tools.reminder import ReminderToolkit, deliver_reminder` works.
- [ ] `deliver_reminder` is a top-level `async def` with the exact keyword-only signature listed above.
- [ ] `ReminderToolkit` inherits `AbstractToolkit` and exposes exactly three public async methods.
- [ ] `schedule_reminder` raises `ValueError` when both or neither of `delay_seconds`/`remind_at` are provided.
- [ ] `schedule_reminder` calls `scheduler.add_job` with `trigger="date"`, `jobstore="redis"`, `id` starting with `reminder-`, and `kwargs` carrying the five fields (`provider`, `recipients`, `message`, `requested_by`, `requested_at`).
- [ ] `list_my_reminders` filters by both `id` prefix and `requested_by` match.
- [ ] `cancel_reminder` raises `PermissionError` on foreign ownership and returns `{"status":"not_found", ...}` on missing jobs.
- [ ] `ruff check packages/ai-parrot/src/parrot/tools/reminder.py` → no errors.
- [ ] No other files modified.

---

## Test Specification

Tests live in separate tasks (TASK-819, TASK-820). This task only needs the
implementation to be **importable** and **pass ruff**. A quick smoke check:

```bash
source .venv/bin/activate
python -c "from parrot.tools.reminder import ReminderToolkit, deliver_reminder; print('ok')"
ruff check packages/ai-parrot/src/parrot/tools/reminder.py
```

---

## Agent Instructions

When you pick up this task:

1. Read the spec `sdd/specs/FEAT-115-reminder-toolkit.spec.md` — especially §6 Codebase Contract.
2. Verify each import in this task's Codebase Contract still resolves at the listed line numbers. If any have moved, update the contract first.
3. Create `packages/ai-parrot/src/parrot/tools/reminder.py` using the reference sketch as the starting shape. You may refine for style, but do not deviate from the public contract (names, signatures, return shapes).
4. Run the smoke check above. Run ruff.
5. Move this task file to `sdd/tasks/completed/TASK-818-reminder-toolkit-module.md`, flip `.index.json` status to `done`, fill in the completion note, and commit with message `sdd: complete TASK-818 — reminder toolkit module`.

---

## Completion Note

*(Agent fills this in when done)*

**Completed by**: <session or agent ID>
**Date**: YYYY-MM-DD
**Notes**: What was implemented, any deviations from scope, issues encountered.

**Deviations from spec**: none | describe if any
