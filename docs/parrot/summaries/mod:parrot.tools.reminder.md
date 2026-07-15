---
type: Wiki Summary
title: parrot.tools.reminder
id: mod:parrot.tools.reminder
tags:
- summary
timestamp: '2026-07-14T22:20:21+00:00'
summary: One-time reminder tooling for agents — FEAT-115.
relates_to:
- concept: class:parrot.tools.reminder.ReminderToolkit
  rel: defines
- concept: func:parrot.tools.reminder.deliver_reminder
  rel: defines
- concept: func:parrot.tools.reminder.register_telegram_bot
  rel: defines
- concept: func:parrot.tools.reminder.unregister_telegram_bot
  rel: defines
- concept: mod:parrot.auth.permission
  rel: references
- concept: mod:parrot.notifications
  rel: references
- concept: mod:parrot.tools.toolkit
  rel: references
---

# `parrot.tools.reminder`

One-time reminder tooling for agents — FEAT-115.

Exposes three LLM-facing tools via :class:`ReminderToolkit`:

* ``schedule_reminder`` — arms a one-shot reminder persisted in APScheduler's
  Redis jobstore (db=6) so it survives process restarts.
* ``list_my_reminders`` — lists pending reminders owned by the current user.
* ``cancel_reminder`` — cancels a pending reminder owned by the current user.

The top-level coroutine :func:`deliver_reminder` is the APScheduler-invocable
callable.  It MUST remain at module scope so APScheduler can serialise its
dotted-path reference (``parrot.tools.reminder:deliver_reminder``).

## Classes

- **`ReminderToolkit(AbstractToolkit)`** — LLM-facing tools to schedule, list, and cancel one-time reminders.

## Functions

- `def register_telegram_bot(bot_id: str | int, bot_token: str) -> None` — Register a Telegram bot token under its non-secret numeric id.
- `def unregister_telegram_bot(bot_id: str | int) -> None` — Remove a previously registered Telegram bot token.
- `async def deliver_reminder(*, provider: str, recipients: list, message: str, requested_by: str, requested_at: str, bot_id: str | None=None) -> None` — Fire a reminder by delivering it through the requested notification channel.
