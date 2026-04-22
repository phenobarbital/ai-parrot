"""One-time reminder tooling for agents — FEAT-115.

Exposes three LLM-facing tools via :class:`ReminderToolkit`:

* ``schedule_reminder`` — arms a one-shot reminder persisted in APScheduler's
  Redis jobstore (db=6) so it survives process restarts.
* ``list_my_reminders`` — lists pending reminders owned by the current user.
* ``cancel_reminder`` — cancels a pending reminder owned by the current user.

The top-level coroutine :func:`deliver_reminder` is the APScheduler-invocable
callable.  It MUST remain at module scope so APScheduler can serialise its
dotted-path reference (``parrot.tools.reminder:deliver_reminder``).
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from parrot.notifications import NotificationMixin
from parrot.tools.toolkit import AbstractToolkit

if TYPE_CHECKING:
    from parrot.auth.permission import PermissionContext

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-scope notifier — NotificationMixin is stateless, safe to share.
# APScheduler serialises only the function *reference*, not captured state,
# so keeping this at module level is the correct pattern.
# ---------------------------------------------------------------------------
_notifier = NotificationMixin()


# ---------------------------------------------------------------------------
# Top-level coroutine — MUST NOT be a method, closure, or lambda.
# ---------------------------------------------------------------------------
async def deliver_reminder(
    *,
    provider: str,
    recipients: list,
    message: str,
    requested_by: str,
    requested_at: str,
) -> None:
    """Fire a reminder by delivering it through the requested notification channel.

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
    """
    prefix = f"⏰ <b>Reminder</b> (scheduled {requested_at}):\n\n"
    logger.info(
        "Delivering reminder for user=%s via provider=%s recipients=%s",
        requested_by,
        provider,
        recipients,
    )
    await _notifier.send_notification(
        message=prefix + message,
        recipients=recipients,
        provider=provider,
    )


# ---------------------------------------------------------------------------
# ReminderToolkit
# ---------------------------------------------------------------------------
class ReminderToolkit(AbstractToolkit):
    """LLM-facing tools to schedule, list, and cancel one-time reminders.

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
    """

    tool_prefix = "reminder"

    def __init__(self, scheduler_manager: Any, **kwargs: Any) -> None:
        """Initialise the toolkit with a reference to the scheduler manager.

        Args:
            scheduler_manager: Runtime scheduler manager; its ``.scheduler``
                attribute must expose the APScheduler ``AsyncIOScheduler`` API.
            **kwargs: Extra keyword arguments forwarded to
                :class:`~parrot.tools.toolkit.AbstractToolkit`.
        """
        super().__init__(**kwargs)
        self._sm = scheduler_manager
        self._pctx: "PermissionContext | None" = None

    async def _pre_execute(self, tool_name: str, **kwargs: Any) -> None:
        """Stash the per-call :class:`~parrot.auth.permission.PermissionContext`.

        Called by the framework before each tool invocation.  The context is
        popped from ``kwargs`` before the bound method is invoked, so bound
        methods read it from ``self._pctx``.

        Args:
            tool_name: Name of the tool about to be called.
            **kwargs: Per-call keyword arguments, including
                ``_permission_context``.
        """
        self._pctx = kwargs.get("_permission_context")

    # ------------------------------------------------------------------
    # Public LLM-facing tools
    # ------------------------------------------------------------------

    async def schedule_reminder(
        self,
        message: str,
        delay_seconds: int | None = None,
        remind_at: str | None = None,
        channel: str = "telegram",
    ) -> dict[str, Any]:
        """Schedule a one-time reminder delivered to the current user.

        Exactly one of *delay_seconds* or *remind_at* must be supplied.
        The reminder is persisted in the Redis jobstore and survives process
        restarts.  After firing, the job is automatically removed by
        APScheduler's ``DateTrigger`` semantics.

        Args:
            message: The reminder text to deliver to the user.
            delay_seconds: Number of seconds from now until the reminder fires.
                Mutually exclusive with *remind_at*.
            remind_at: Absolute ISO-8601 datetime (timezone-aware recommended)
                at which the reminder fires.  Mutually exclusive with
                *delay_seconds*.
            channel: Notification channel to use.  Supported values:
                ``"telegram"`` (default), ``"email"``, ``"slack"``,
                ``"teams"``.

        Returns:
            A dict with keys ``reminder_id``, ``fires_at`` (ISO-8601 UTC),
            and ``channel``.

        Raises:
            ValueError: If both or neither of *delay_seconds* / *remind_at*
                are provided, if the caller's channel-specific identifier is
                absent from :attr:`PermissionContext.extra`, or if
                ``scheduler_manager`` is not connected to a live Redis
                jobstore.
        """
        # Mutual-exclusion guard
        if (delay_seconds is None) == (remind_at is None):
            raise ValueError(
                "Provide exactly one of 'delay_seconds' or 'remind_at', not both (or neither)."
            )

        # Compute absolute UTC fire time
        if delay_seconds is not None:
            run_at = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)
        else:
            run_at = datetime.fromisoformat(remind_at).astimezone(timezone.utc)  # type: ignore[arg-type]

        pctx = self._pctx
        if pctx is None:
            raise ValueError(
                "schedule_reminder requires an active PermissionContext. "
                "Ensure the tool manager injects _permission_context before calling."
            )

        recipients = self._recipients_for_channel(channel, pctx)
        reminder_id = f"reminder-{uuid.uuid4()}"
        requested_at = datetime.now(timezone.utc).isoformat()

        self._sm.scheduler.add_job(
            deliver_reminder,
            trigger="date",
            run_date=run_at,
            kwargs={
                "provider": channel,
                "recipients": recipients,
                "message": message,
                "requested_by": str(pctx.user_id),
                "requested_at": requested_at,
            },
            id=reminder_id,
            jobstore="redis",
            replace_existing=False,
        )

        self.logger.info(
            "Scheduled %s for user=%s fires_at=%s channel=%s",
            reminder_id,
            pctx.user_id,
            run_at.isoformat(),
            channel,
        )

        return {
            "reminder_id": reminder_id,
            "fires_at": run_at.isoformat(),
            "channel": channel,
        }

    async def list_my_reminders(self) -> list[dict[str, Any]]:
        """List pending reminders owned by the current user.

        Filters the Redis jobstore to return only jobs whose id starts with
        ``reminder-`` and whose ``requested_by`` field matches the caller's
        ``user_id``.

        Returns:
            A list of dicts, each with keys ``reminder_id``, ``fires_at``
            (ISO-8601 or ``None`` if already firing), ``channel``, and
            ``message``.

        Raises:
            ValueError: If no active :class:`~parrot.auth.permission.PermissionContext`
                is available.
        """
        pctx = self._pctx
        if pctx is None:
            raise ValueError(
                "list_my_reminders requires an active PermissionContext."
            )
        me = str(pctx.user_id)
        jobs = self._sm.scheduler.get_jobs(jobstore="redis")
        result = [
            {
                "reminder_id": j.id,
                "fires_at": j.next_run_time.isoformat() if j.next_run_time else None,
                "channel": j.kwargs.get("provider"),
                "message": j.kwargs.get("message"),
            }
            for j in jobs
            if j.id.startswith("reminder-") and j.kwargs.get("requested_by") == me
        ]
        self.logger.info(
            "Listed %d reminders for user=%s", len(result), me
        )
        return result

    async def cancel_reminder(self, reminder_id: str) -> dict[str, Any]:
        """Cancel a pending reminder owned by the current user.

        Args:
            reminder_id: The ``reminder-<uuid>`` identifier returned by
                :meth:`schedule_reminder`.

        Returns:
            A dict with keys ``status`` (``"cancelled"`` or ``"not_found"``)
            and ``reminder_id``.

        Raises:
            ValueError: If no active :class:`~parrot.auth.permission.PermissionContext`
                is available.
            PermissionError: If the reminder belongs to a different user.
        """
        pctx = self._pctx
        if pctx is None:
            raise ValueError(
                "cancel_reminder requires an active PermissionContext."
            )
        me = str(pctx.user_id)

        job = self._sm.scheduler.get_job(reminder_id, jobstore="redis")
        if job is None:
            return {"status": "not_found", "reminder_id": reminder_id}

        if job.kwargs.get("requested_by") != me:
            raise PermissionError(
                f"Cannot cancel reminder '{reminder_id}': it belongs to another user."
            )

        self._sm.scheduler.remove_job(reminder_id, jobstore="redis")
        self.logger.info("Cancelled %s by user=%s", reminder_id, me)
        return {"status": "cancelled", "reminder_id": reminder_id}

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _recipients_for_channel(self, channel: str, pctx: Any) -> list:
        """Extract the notification recipient(s) for *channel* from *pctx*.

        Args:
            channel: Notification channel name.
            pctx: Active :class:`~parrot.auth.permission.PermissionContext`.

        Returns:
            A non-empty list of recipient identifiers.

        Raises:
            ValueError: If the required identifier is not present in
                ``pctx.extra`` or if *channel* is not supported.
        """
        extra: dict = pctx.extra or {}

        if channel == "telegram":
            val = extra.get("telegram_id") or extra.get("chat_id")
            if not val:
                raise ValueError(
                    "No 'telegram_id' or 'chat_id' found in PermissionContext.extra "
                    "for a Telegram reminder. Ensure the Telegram integration populates "
                    "extra['telegram_id'] on inbound requests."
                )
            return [val]

        if channel == "email":
            email = extra.get("email") or getattr(pctx.session, "email", None)
            if not email:
                raise ValueError(
                    "No 'email' found in PermissionContext.extra (or session) "
                    "for an email reminder. Ask the user to provide their email address."
                )
            return [email]

        if channel == "slack":
            val = extra.get("slack_user_id") or extra.get("slack_channel")
            if not val:
                raise ValueError(
                    "No 'slack_user_id' or 'slack_channel' found in "
                    "PermissionContext.extra for a Slack reminder."
                )
            return [val]

        if channel == "teams":
            val = extra.get("teams_user_id") or extra.get("teams_conversation_id")
            if not val:
                raise ValueError(
                    "No 'teams_user_id' or 'teams_conversation_id' found in "
                    "PermissionContext.extra for a Teams reminder."
                )
            return [val]

        raise ValueError(
            f"Unsupported notification channel: '{channel}'. "
            "Supported channels: telegram, email, slack, teams."
        )
