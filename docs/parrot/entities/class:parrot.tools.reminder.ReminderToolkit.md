---
type: Wiki Entity
title: ReminderToolkit
id: class:parrot.tools.reminder.ReminderToolkit
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: LLM-facing tools to schedule, list, and cancel one-time reminders.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# ReminderToolkit

Defined in [`parrot.tools.reminder`](../summaries/mod:parrot.tools.reminder.md).

```python
class ReminderToolkit(AbstractToolkit)
```

LLM-facing tools to schedule, list, and cancel one-time reminders.

Reminders are stored as APScheduler jobs with ``trigger="date"`` in the
``"redis"`` jobstore, keyed as ``reminder-<uuid4>``.  All per-reminder
data (channel, recipients, message, owner) is serialised inside the job's
``kwargs`` payload — no new database schema is introduced.

Ownership is enforced server-side via :class:`~parrot.auth.permission.PermissionContext`
injected through the ``_pre_execute`` lifecycle hook.  The LLM cannot
spoof the ``requested_by`` field.

Args:
    scheduler_manager: An :class:`~parrot.scheduler.AgentSchedulerManager`
        instance (or any object exposing a ``.scheduler`` attribute that
        implements the APScheduler ``AsyncIOScheduler`` API).
    **kwargs: Forwarded to :class:`~parrot.tools.toolkit.AbstractToolkit`.

## Methods

- `async def schedule_reminder(self, message: str, delay_seconds: int | None=None, remind_at: str | None=None, channel: str='telegram') -> dict[str, Any]` — Schedule a one-time reminder delivered to the current user.
- `async def list_my_reminders(self) -> list[dict[str, Any]]` — List pending reminders owned by the current user.
- `async def cancel_reminder(self, reminder_id: str) -> dict[str, Any]` — Cancel a pending reminder owned by the current user.
