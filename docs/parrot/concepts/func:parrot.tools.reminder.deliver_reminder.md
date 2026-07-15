---
type: Concept
title: deliver_reminder()
id: func:parrot.tools.reminder.deliver_reminder
tags:
- concept
timestamp: '2026-07-14T22:20:21+00:00'
summary: Fire a reminder by delivering it through the requested notification channel.
---

# deliver_reminder

```python
async def deliver_reminder(*, provider: str, recipients: list, message: str, requested_by: str, requested_at: str, bot_id: str | None=None) -> None
```

Fire a reminder by delivering it through the requested notification channel.

Invoked directly by APScheduler's ``AsyncIOExecutor`` when the
``DateTrigger`` fires.  After execution, APScheduler automatically removes
the exhausted job from the jobstore — no manual cleanup is required.

Args:
    provider: Notification channel (``"telegram"``, ``"email"``,
        ``"slack"``, ``"teams"``).
    recipients: List of channel-specific recipient identifiers (e.g.
        Telegram chat ids, email addresses, Slack user ids, Teams
        conversation ids).
    message: Free-form reminder text provided by the user at schedule time.
    requested_by: ``user_id`` of the user who scheduled the reminder.
        Stored for audit purposes; not used for delivery logic here.
    requested_at: ISO-8601 UTC timestamp of when the reminder was
        scheduled.  Included in the delivered message prefix.
    bot_id: For Telegram reminders, the non-secret numeric id of the bot
        that scheduled the reminder. Used to resolve the matching token
        from :data:`_TELEGRAM_BOT_TOKENS` so delivery goes through the
        originating bot. When ``None`` or unregistered, the provider falls
        back to the global ``TELEGRAM_BOT_TOKEN`` env default (legacy
        behaviour).
