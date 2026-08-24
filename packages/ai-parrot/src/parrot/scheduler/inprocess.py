"""InProcessScheduler — lightweight APScheduler wrapper for agent processes.

FEAT-453, Module 8 (Goal G6), Decision D1.

FEAT-203 deliberately moved task scheduling out of ``ai-parrot`` core into
``ai-parrot-server[scheduler]`` (``parrot/scheduler/__init__.py`` is a lazy
PEP 562 shim resolving ``AgentSchedulerManager`` and friends from that
satellite). This module is a deliberate, **partial** reversal of that move
by operator decision (spec §8): an agent process needs to schedule
reminders (e.g. Spanish tax-calendar deadlines) without taking a dependency
on the full server distribution.

**This must never shadow the satellite.** ``InProcessScheduler`` is a
distinctly-named class living alongside (not instead of)
``parrot.scheduler``'s ``_SERVER_CLASSES`` delegation — ``AgentSchedulerManager``,
``ScheduleType``, ``schedule``, ``schedule_daily_report`` and
``schedule_weekly_report`` all keep resolving through the existing
``__getattr__`` in ``parrot/scheduler/__init__.py`` (this module does not
touch that file at all).

Layering note: this is core (``ai-parrot``). ``ai-parrot-tools`` (which owns
``GoogleCalendarToolkit``) depends on core, never the reverse — so
:func:`schedule_tax_reminder` takes an already-constructed calendar-like
object and only references its type under ``TYPE_CHECKING``, never at
runtime, to avoid a reverse/circular package dependency.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable, Dict, List, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

if TYPE_CHECKING:
    from parrot.human.channels.base import HumanChannel

logger = logging.getLogger(__name__)

#: Default recipient label for retention-sweep / reminder notifications.
_DEFAULT_RECIPIENT = "operator"


class InProcessScheduler:
    """Lightweight APScheduler wrapper for agent processes that must
    schedule work WITHOUT deploying ai-parrot-server.

    Deliberately does NOT shadow ``AgentSchedulerManager``, which stays
    satellite-only.
    """

    def __init__(self) -> None:
        self._scheduler = AsyncIOScheduler()
        self._jobs: Dict[str, Any] = {}
        # Tracked independently of self._scheduler.running: AsyncIOScheduler
        # .shutdown() schedules its actual work via call_soon rather than
        # completing synchronously, so `.running` can briefly still read
        # True immediately after a shutdown() call — relying on it alone
        # makes stop() non-idempotent (a second call races the first).
        self._running = False
        self.logger = logging.getLogger(self.__class__.__name__)

    async def start(self) -> None:
        """Start the underlying APScheduler event-loop integration.

        Idempotent — calling twice is a no-op.
        """
        if not self._running:
            self._scheduler.start()
            self._running = True

    async def stop(self) -> None:
        """Stop the scheduler. Idempotent — calling twice is a no-op."""
        if self._running:
            self._running = False
            self._scheduler.shutdown(wait=False)

    def add_cron(
        self, name: str, cron: str, callback: Callable[..., Any]
    ) -> str:
        """Schedule *callback* on a 5-field cron expression.

        Args:
            name: Human-readable job name; also used as the APScheduler job
                id (re-registering the same name replaces the prior job).
            cron: A 5-field cron expression: ``"minute hour day month
                day_of_week"`` (standard crontab order).
            callback: Sync or async callable invoked on each trigger.
                APScheduler awaits coroutine functions natively.

        Returns:
            The APScheduler job id (equal to *name*).

        Raises:
            ValueError: If *cron* does not have exactly 5 fields.
        """
        fields = cron.split()
        if len(fields) != 5:
            raise ValueError(
                f"add_cron({name!r}): expected a 5-field cron expression "
                f"('minute hour day month day_of_week'), got {cron!r}"
            )
        minute, hour, day, month, day_of_week = fields
        trigger = CronTrigger(
            minute=minute, hour=hour, day=day, month=month, day_of_week=day_of_week
        )
        # NOTE: AsyncIOScheduler's `replace_existing=True` only dedupes
        # reliably once the scheduler is running — its pre-start "pending
        # jobs" queue does not check for id collisions the same way the
        # live jobstore does. Removing any prior job for *name* first makes
        # add_cron's "re-registering the same name replaces the prior job"
        # contract hold regardless of whether start() has been called yet.
        if name in self._jobs:
            try:
                self._scheduler.remove_job(name)
            except Exception:
                self.logger.debug("add_cron(%r): prior job already removed", name, exc_info=True)
        job = self._scheduler.add_job(
            callback, trigger=trigger, id=name, name=name, replace_existing=True
        )
        self._jobs[name] = job
        return job.id


@dataclass
class TaxDeadline:
    """A single filing deadline to remind about.

    Deliberately does not hardcode any real Spanish tax dates — FEAT-449
    (legal-norms-graph-boe) is adjacent, not authoritative for filing
    deadlines (spec §7 Known Risks); callers supply deadlines from their
    own (AEAT-calendar-derived) source of truth.

    Attributes:
        name: Human-readable deadline label (e.g. ``"Modelo 303 Q1"``).
        due_date: The filing deadline date.
        reminder_lead_days: How many days before ``due_date`` to fire the
            reminder (default 7).
    """

    name: str
    due_date: date
    reminder_lead_days: int = 7


def schedule_tax_reminder(
    scheduler: InProcessScheduler,
    deadline: TaxDeadline,
    *,
    on_reminder: Callable[[TaxDeadline], Awaitable[None]],
) -> str:
    """Register a cron reminder for *deadline*.

    Fires once a year on ``due_date - reminder_lead_days`` at 09:00, calling
    *on_reminder* — e.g. a closure that creates a Google Calendar event
    (:meth:`~parrot_tools.google.calendar.GoogleCalendarToolkit.create_event`)
    and/or notifies a :class:`~parrot.human.channels.base.HumanChannel`. This
    function takes a generic callback rather than importing a concrete
    calendar/toolkit type directly (layering: this module is core;
    ``GoogleCalendarToolkit`` lives in the ``ai-parrot-tools`` satellite,
    which depends on core, never the reverse).

    Args:
        scheduler: The :class:`InProcessScheduler` to register the job on.
        deadline: The :class:`TaxDeadline` to remind about.
        on_reminder: Async callback invoked with *deadline* when the
            reminder fires.

    Returns:
        The APScheduler job id.
    """
    reminder_date = deadline.due_date - timedelta(days=deadline.reminder_lead_days)
    cron = f"0 9 {reminder_date.day} {reminder_date.month} *"

    async def _fire() -> None:
        await on_reminder(deadline)

    return scheduler.add_cron(f"tax-reminder-{deadline.name}", cron, _fire)


async def notify_tax_deadline(
    deadline: TaxDeadline,
    *,
    channel: Optional[HumanChannel] = None,
    recipient: str = _DEFAULT_RECIPIENT,
) -> None:
    """Default :func:`schedule_tax_reminder` callback: notify *channel*
    that *deadline* is approaching.

    A convenience default for callers that only need the notification half
    (calendar-event creation is left to the caller's own closure, composed
    alongside this if both are wanted, since this module cannot import
    ``GoogleCalendarToolkit`` — see the layering note above).
    """
    if channel is None:
        logger.warning(
            "notify_tax_deadline: no HumanChannel configured; deadline %r "
            "(%s) will not be surfaced to a human",
            deadline.name,
            deadline.due_date,
        )
        return
    await channel.send_notification(
        recipient,
        f"Upcoming tax deadline: {deadline.name} on {deadline.due_date.isoformat()}",
    )


async def sweep_checkpoint_retention(
    checkpoint_dir: Path,
    *,
    retention_days: int = 90,
    archive_dir: Optional[Path] = None,
    channel: Optional[HumanChannel] = None,
    recipient: str = _DEFAULT_RECIPIENT,
) -> List[Path]:
    """Archive (never silently delete) checkpoint files older than
    *retention_days*, alerting over *channel* when anything is archived.

    Decision D3: a checkpoint is the record of what was already written to
    the accounting system. Deleting it early causes duplicate expense
    registration on the next resume — so aged-out checkpoints are moved to
    *archive_dir* (never removed), and the sweep always alerts so a human
    can confirm reconciliation before the archive is ever cleaned up
    manually.

    Args:
        checkpoint_dir: Directory containing ``*.json`` checkpoint/manifest
            files (see ``parrot_tools.business_automation.ingest``).
        retention_days: Age threshold in days (default 90 — a quarterly
            cycle plus margin).
        archive_dir: Where to move aged-out files (default:
            ``checkpoint_dir / "archive"``).
        channel: Optional :class:`HumanChannel` to alert when files are
            archived.
        recipient: Notification recipient label.

    Returns:
        The list of archived file paths (in their new, archived location).
        Empty if nothing was old enough to archive.
    """
    if archive_dir is None:
        archive_dir = checkpoint_dir / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_dir.chmod(0o700)

    cutoff = time.time() - (retention_days * 86400)
    archived: List[Path] = []
    for path in sorted(checkpoint_dir.glob("*.json")):
        if not path.is_file():
            continue
        if path.stat().st_mtime < cutoff:
            destination = archive_dir / path.name
            path.rename(destination)
            destination.chmod(0o600)
            archived.append(destination)

    if archived:
        logger.info(
            "sweep_checkpoint_retention: archived %d checkpoint(s) older than "
            "%d days from %s",
            len(archived), retention_days, checkpoint_dir,
        )
        if channel is not None:
            await channel.send_notification(
                recipient,
                f"Archived {len(archived)} checkpoint(s) older than "
                f"{retention_days} days: " + ", ".join(p.name for p in archived),
            )

    return archived
