"""Deterministic retention decisions and in-memory sweeping (FEAT-538).

Retention is the part of task memory most likely to destroy something a
user still needed, so every rule here is explicit, configured, and
decided by a **pure function** over captured inputs before any effect
runs.

The module separates three things that are usually tangled together:

1. **Selection** — :func:`select_due_tasks` and
   :func:`select_due_artifacts` are pure. Given a clock reading and a
   set of immutable views, they return the actions that are due. No I/O,
   no randomness, no wall clock of their own. Tests drive time by
   injection and never sleep.
2. **Ordering** — :meth:`RetentionSweeper.run_once` appends each action's
   **intent event before** doing the destructive work, so the intent is
   auditable at the moment the work is attempted rather than after it
   succeeded.
3. **Effects** — the genuinely destructive capabilities (journal purge,
   archive, blob sweep) are narrow :class:`Protocol` s the host wires in.
   Delivery A ships the in-memory artifact sweeping and none of the
   durable ones; Delivery B's cleanup task supplies those.

.. warning::

   **The audit trail does not survive terminal deletion.** Deleting a
   terminal task necessarily removes the journal that recorded the
   intent to delete it. When ``archive_uri`` is configured the archive
   includes that final retention event, so the record moves rather than
   disappears. **Without an archive, deletion is deliberately
   irreversible** and leaves only bounded operational logs. This module
   does not claim permanent in-journal audit after deleting the journal,
   because that claim would be false.

.. warning::

   Delivery A **cannot promise retained bytes**. When the byte budget
   forces out evidence that a task still references, the store records an
   invalidation and keeps a metadata tombstone. No eviction may silently
   remove evidence while leaving a step labeled valid.

Scheduling is a host concern. :meth:`RetentionSweeper.run_once` is a
plain idempotent coroutine: run it from an existing qworker deployment,
or use :class:`PeriodicRetention` for a single-process deployment with
explicit startup and shutdown. No queue dependency is introduced.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, List, Optional, Protocol, Sequence, Tuple, runtime_checkable

from parrot.interfaces.task_memory import TaskMemoryStore

from .config import TaskMemoryConfig
from .models import (
    Actor,
    EventType,
    EvidenceRef,
    JournalEvent,
    RetentionPayload,
    TaskScope,
    TaskStatus,
    new_id,
    utc_now,
)

__all__ = (
    "INACTIVITY_PAUSE_REASON",
    "ABANDONED_CANCEL_REASON",
    "RetentionPolicy",
    "RetentionAction",
    "JournalPressure",
    "TaskRetentionView",
    "ArtifactRetentionView",
    "BlobRetentionView",
    "DueAction",
    "SweepReport",
    "ArchiveWriter",
    "JournalPurge",
    "BlobSweeper",
    "journal_pressure",
    "select_due_tasks",
    "select_due_artifacts",
    "select_due_blobs",
    "RetentionSweeper",
    "PeriodicRetention",
    "ARCHIVE_VERIFY_FAILED",
    "JsonlArchiveWriter",
    "ArchiveVerificationError",
    "HotKeyCleaner",
)

logger = logging.getLogger(__name__)

#: Reason stamped on a pause the sweeper applies for inactivity. It is
#: the marker that starts the abandonment clock: a task paused by a user
#: for their own reasons is not on that clock.
INACTIVITY_PAUSE_REASON: str = "retention:inactivity"

#: Reason stamped on a cancellation for prolonged abandonment.
ABANDONED_CANCEL_REASON: str = "retention:abandoned"

#: Page size used when scanning a journal for its anchor events.
_JOURNAL_PAGE: int = 200


class RetentionPolicy(str):
    """Which rule in the specification's retention table fired."""

    #: Active task with no activity for ``inactivity_pause_days``.
    INACTIVITY = "inactivity"
    #: Task paused for inactivity for ``abandoned_cancel_days``.
    ABANDONED = "abandoned"
    #: Terminal task past ``terminal_retention_days`` from ``terminal_at``.
    TERMINAL = "terminal"
    #: Unpinned, non-current version past ``unpinned_version_ttl_hours``.
    STALE_VERSION = "stale_version"
    #: Blob with nothing referencing it, past ``orphan_blob_grace_hours``.
    ORPHAN_BLOB = "orphan_blob"


class RetentionAction(str):
    """What a due action intends to do."""

    PAUSE = "pause"
    CANCEL = "cancel"
    ARCHIVE_AND_DELETE = "archive_and_delete"
    DELETE = "delete"
    EXPIRE_VERSION = "expire_version"
    SWEEP_BLOB = "sweep_blob"


@dataclass(frozen=True)
class JournalPressure:
    """How close a task's journal is to its configured ceilings.

    Attributes:
        event_count: Events currently in the journal.
        soft_exceeded: Past ``journal_soft_limit``. Recall must stop
            retaining *optional* recent-call material — it does not stop
            recalling, and nothing is discarded.
        foreground_refused: Past ``journal_hard_limit``. New ordinary
            work is refused.
        reserved_exhausted: Past the hard limit **plus** the reserved
            headroom. Even terminal, recovery and retention events can no
            longer be appended.
    """

    event_count: int
    soft_exceeded: bool
    foreground_refused: bool
    reserved_exhausted: bool


def journal_pressure(event_count: int, config: TaskMemoryConfig) -> JournalPressure:
    """Classify a journal's size against the configured ceilings.

    History is **never** silently discarded: passing a ceiling refuses
    new work rather than trimming old events.

    Args:
        event_count: Events currently in the journal.
        config: The configuration supplying the ceilings.

    Returns:
        The :class:`JournalPressure` classification.
    """
    return JournalPressure(
        event_count=event_count,
        soft_exceeded=event_count >= config.journal_soft_limit,
        foreground_refused=config.is_journal_exhausted(event_count, reserved=False),
        reserved_exhausted=config.is_journal_exhausted(event_count, reserved=True),
    )


# ─────────────────────────────────────────────────────────────
# Immutable views — the pure selectors' only inputs
# ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class TaskRetentionView:
    """Everything the task rules are allowed to look at.

    Attributes:
        scope: Owning scope.
        task_id: The task.
        status: Its lifecycle status.
        updated_at: When it last changed.
        terminal_at: When it reached a terminal status, if it has.
        inactivity_paused_at: When the **sweeper** paused it for
            inactivity, if it did.
        last_activity_at: When the task last did real work. Distinct from
            ``updated_at`` on purpose — see :func:`select_due_tasks`.
        event_count: Journal size, for the capacity rules.
    """

    scope: TaskScope
    task_id: str
    status: TaskStatus
    updated_at: datetime
    terminal_at: Optional[datetime] = None
    inactivity_paused_at: Optional[datetime] = None
    last_activity_at: Optional[datetime] = None
    event_count: int = 0

    @property
    def activity_anchor(self) -> datetime:
        """The instant the inactivity clock is measured from."""
        return self.last_activity_at or self.updated_at


@dataclass(frozen=True)
class ArtifactRetentionView:
    """Everything the artifact rules are allowed to look at.

    Attributes:
        scope: Owning scope.
        ref: The exact version.
        task_id: The task that produced it.
        created_at: When the version was registered.
        is_current: Whether an alias still points at it.
        pinned_by: Every task referencing it as evidence. **Any** pin
            defers deletion, including a task other than the producer.
        retained_bytes: Bytes still held for it.
        owner_terminal_at: When the producing task went terminal, if it
            has. Non-terminal evidence is protected regardless of age.
    """

    scope: TaskScope
    ref: EvidenceRef
    task_id: Optional[str]
    created_at: datetime
    is_current: bool
    pinned_by: Tuple[str, ...] = ()
    retained_bytes: int = 0
    owner_terminal_at: Optional[datetime] = None


@dataclass(frozen=True)
class BlobRetentionView:
    """Everything the orphan-blob rule is allowed to look at.

    Attributes:
        scope: Owning scope.
        storage_ref: Backend reference to the bytes.
        written_at: When the blob was written.
        has_live_index: Whether an artifact row still references it.
        has_publish_lease: Whether a publish is still in flight.
        has_archive_reference: Whether an archive references it.
    """

    scope: TaskScope
    storage_ref: str
    written_at: datetime
    has_live_index: bool = False
    has_publish_lease: bool = False
    has_archive_reference: bool = False

    @property
    def is_orphan(self) -> bool:
        """Whether nothing at all references this blob."""
        return not (self.has_live_index or self.has_publish_lease or self.has_archive_reference)


@dataclass(frozen=True)
class DueAction:
    """One retention action that has come due.

    Attributes:
        policy: Which rule fired.
        action: What it intends to do.
        scope: Owning scope.
        task_id: The task, when the action is task-scoped.
        due_at: When the action became due.
        target_refs: Artifact versions the action targets.
        storage_ref: The blob the action targets, when it targets one.
        reason: Human-readable explanation, stamped on the transition.
        archive_uri: Where the archive will be written, when configured.
    """

    policy: str
    action: str
    scope: TaskScope
    task_id: Optional[str] = None
    due_at: Optional[datetime] = None
    target_refs: Tuple[EvidenceRef, ...] = ()
    storage_ref: Optional[str] = None
    reason: Optional[str] = None
    archive_uri: Optional[str] = None

    def to_payload(self) -> RetentionPayload:
        """Build the journal payload announcing this intent.

        Returns:
            The :class:`RetentionPayload` for a ``retention_scheduled``
            event.
        """
        return RetentionPayload(
            policy=self.policy,
            action=self.action,
            due_at=self.due_at,
            target_refs=self.target_refs,
            archive_uri=self.archive_uri,
        )


@dataclass
class SweepReport:
    """What one :meth:`RetentionSweeper.run_once` did.

    Attributes:
        paused: Tasks paused for inactivity.
        cancelled: Tasks cancelled for abandonment.
        deleted: Tasks whose journal and projection were removed.
        archived: Tasks archived before deletion.
        expired_versions: Artifact versions whose bytes were released.
        swept_blobs: Orphan blobs removed.
        deferred: Actions that came due but were held back, with the
            reason — a cross-task pin, a failed archive, a missing
            capability.
        invalidations: Receipts drained from the artifact store, which
            the caller turns into ``artifact_invalidated`` events.
        errors: Actions that failed, with their cause.
        audit_destroyed: One ``(task_id, archive_reference)`` pair per
            task whose journal was deleted. The second element is
            ``None`` when no archive was configured, which is the honest
            record that the audit trail for that task is **gone** rather
            than relocated. Callers that need a permanent record must
            read this and write it somewhere outside the journal — the
            journal that recorded the intent no longer exists.
    """

    paused: List[str] = field(default_factory=list)
    cancelled: List[str] = field(default_factory=list)
    deleted: List[str] = field(default_factory=list)
    archived: List[str] = field(default_factory=list)
    expired_versions: List[EvidenceRef] = field(default_factory=list)
    swept_blobs: List[str] = field(default_factory=list)
    deferred: List[Tuple[str, str]] = field(default_factory=list)
    invalidations: List[Any] = field(default_factory=list)
    errors: List[Tuple[str, str]] = field(default_factory=list)
    audit_destroyed: List[Tuple[str, Optional[str]]] = field(default_factory=list)

    @property
    def action_count(self) -> int:
        """How many destructive actions actually completed."""
        return (
            len(self.paused)
            + len(self.cancelled)
            + len(self.deleted)
            + len(self.expired_versions)
            + len(self.swept_blobs)
        )

    @property
    def is_noop(self) -> bool:
        """Whether the sweep changed nothing at all."""
        return self.action_count == 0


# ─────────────────────────────────────────────────────────────
# Pure selection
# ─────────────────────────────────────────────────────────────


def select_due_tasks(
    now: datetime,
    views: Sequence[TaskRetentionView],
    config: TaskMemoryConfig,
) -> Tuple[DueAction, ...]:
    """Select the task-level retention actions that are due.

    Pure: no clock of its own, no I/O, no randomness. The same inputs
    always yield the same actions, which is what makes the sweeper
    testable at a boundary rather than approximately.

    The three anchors are deliberately **different instants**, and
    confusing them is the classic way retention goes wrong:

    - inactivity is measured from ``activity_anchor`` — the last time the
      task did real work;
    - abandonment is measured from ``inactivity_paused_at`` — the
      sweeper's own pause, **not** from ``updated_at``. Using
      ``updated_at`` would be a bug that hides itself: the sweeper's own
      ``retention_scheduled`` intent event bumps ``updated_at``, so the
      sweeper would keep resetting the very clock it was measuring and
      the task would never be cancelled;
    - terminal expiry is measured from ``terminal_at``.

    Args:
        now: The current instant, injected.
        views: Immutable views of the candidate tasks.
        config: The configuration supplying every threshold.

    Returns:
        The due actions, in a stable order (by task id within policy).
    """
    inactivity_cutoff = now - timedelta(days=config.inactivity_pause_days)
    abandon_cutoff = now - timedelta(days=config.abandoned_cancel_days)
    terminal_cutoff = now - timedelta(days=config.terminal_retention_days)

    actions: List[DueAction] = []

    for view in sorted(views, key=lambda v: v.task_id):
        if view.status is TaskStatus.ACTIVE and view.activity_anchor <= inactivity_cutoff:
            actions.append(
                DueAction(
                    policy=RetentionPolicy.INACTIVITY,
                    action=RetentionAction.PAUSE,
                    scope=view.scope,
                    task_id=view.task_id,
                    due_at=view.activity_anchor + timedelta(days=config.inactivity_pause_days),
                    reason=INACTIVITY_PAUSE_REASON,
                )
            )
            continue

        if (
            view.status is TaskStatus.PAUSED
            and view.inactivity_paused_at is not None
            and view.inactivity_paused_at <= abandon_cutoff
        ):
            actions.append(
                DueAction(
                    policy=RetentionPolicy.ABANDONED,
                    action=RetentionAction.CANCEL,
                    scope=view.scope,
                    task_id=view.task_id,
                    due_at=view.inactivity_paused_at + timedelta(days=config.abandoned_cancel_days),
                    reason=ABANDONED_CANCEL_REASON,
                )
            )
            continue

        if view.status.is_terminal and view.terminal_at is not None and view.terminal_at <= terminal_cutoff:
            archived = config.archive_uri is not None
            actions.append(
                DueAction(
                    policy=RetentionPolicy.TERMINAL,
                    action=(RetentionAction.ARCHIVE_AND_DELETE if archived else RetentionAction.DELETE),
                    scope=view.scope,
                    task_id=view.task_id,
                    due_at=view.terminal_at + timedelta(days=config.terminal_retention_days),
                    reason="terminal retention expired",
                    archive_uri=config.archive_uri,
                )
            )

    return tuple(actions)


def select_due_artifacts(
    now: datetime,
    views: Sequence[ArtifactRetentionView],
    config: TaskMemoryConfig,
) -> Tuple[DueAction, ...]:
    """Select the artifact versions whose retained bytes may be released.

    Pure. Three protections, each of which must hold independently:

    - **Non-terminal evidence is protected.** A version whose producing
      task is still live is never expired by age, however old.
    - **Any pin defers deletion**, including a pin held by a task *other*
      than the producer. Cross-task evidence references are exactly the
      case a naive "is the owner done?" check gets wrong.
    - **Current versions are protected** from the stale-version rule.
      Only non-current versions expire on the 24-hour clock; a current
      version of a terminal task follows the 90-day terminal rule
      instead.

    Args:
        now: The current instant, injected.
        views: Immutable views of the candidate versions.
        config: The configuration supplying the thresholds.

    Returns:
        The due actions, ordered by reference for stability.
    """
    stale_cutoff = now - timedelta(hours=config.unpinned_version_ttl_hours)
    terminal_cutoff = now - timedelta(days=config.terminal_retention_days)

    actions: List[DueAction] = []
    for view in sorted(views, key=lambda v: (v.ref.artifact_id, v.ref.version)):
        if not view.retained_bytes:
            # Already released. Selecting it again would make repeated
            # sweeps look like repeated work.
            continue
        if view.pinned_by:
            continue
        if view.owner_terminal_at is None:
            # The producing task is still live: its evidence is protected
            # regardless of age.
            continue

        due_at: Optional[datetime] = None
        if not view.is_current and view.created_at <= stale_cutoff:
            due_at = view.created_at + timedelta(hours=config.unpinned_version_ttl_hours)
        elif view.is_current and view.owner_terminal_at <= terminal_cutoff:
            due_at = view.owner_terminal_at + timedelta(days=config.terminal_retention_days)

        if due_at is None:
            continue

        actions.append(
            DueAction(
                policy=RetentionPolicy.STALE_VERSION,
                action=RetentionAction.EXPIRE_VERSION,
                scope=view.scope,
                task_id=view.task_id,
                due_at=due_at,
                target_refs=(view.ref,),
                reason="unpinned version past its retention",
            )
        )
    return tuple(actions)


def select_due_blobs(
    now: datetime,
    views: Sequence[BlobRetentionView],
    config: TaskMemoryConfig,
) -> Tuple[DueAction, ...]:
    """Select orphan blobs old enough to sweep.

    Pure. A blob is swept **only** when nothing references it — no live
    index row, no pending publish lease, no archive — and only after the
    grace period. Orphans are expected after a crash; a blob that is
    merely mid-publish is not an orphan, and sweeping it would delete
    bytes a reference is about to point at.

    Args:
        now: The current instant, injected.
        views: Immutable views of the candidate blobs.
        config: The configuration supplying the grace period.

    Returns:
        The due actions, ordered by storage reference.
    """
    cutoff = now - timedelta(hours=config.orphan_blob_grace_hours)
    return tuple(
        DueAction(
            policy=RetentionPolicy.ORPHAN_BLOB,
            action=RetentionAction.SWEEP_BLOB,
            scope=view.scope,
            storage_ref=view.storage_ref,
            due_at=view.written_at + timedelta(hours=config.orphan_blob_grace_hours),
            reason="orphan blob past its grace period",
        )
        for view in sorted(views, key=lambda v: v.storage_ref)
        if view.is_orphan and view.written_at <= cutoff
    )


# ─────────────────────────────────────────────────────────────
# Effect capabilities the host wires in
# ─────────────────────────────────────────────────────────────


@runtime_checkable
class ArchiveWriter(Protocol):
    """Writes a terminal task's journal somewhere durable, and verifies it.

    The verification step is not optional. Deletion proceeds **only**
    after :meth:`verify` confirms the archive is readable, because an
    unverified archive plus a deleted journal is indistinguishable from
    data loss.
    """

    async def write(self, uri: str, task_id: str, events: Sequence[JournalEvent]) -> str:
        """Write a task's journal as JSONL and return its location.

        Args:
            uri: Configured archive destination.
            task_id: The task being archived.
            events: Its complete journal, **including** the final
                retention event announcing the deletion.

        Returns:
            A reference to the written archive.
        """
        ...

    async def verify(self, reference: str, expected_events: int) -> bool:
        """Confirm a written archive is readable and complete.

        Args:
            reference: What :meth:`write` returned.
            expected_events: How many events it should contain.

        Returns:
            ``True`` only when the archive is verified.
        """
        ...


@runtime_checkable
class JournalPurge(Protocol):
    """Removes a terminal task's journal and projection.

    Delivery A supplies no implementation: without one, terminal expiry
    is reported as deferred rather than silently skipped.
    """

    async def purge_task(self, scope: TaskScope, task_id: str) -> bool:
        """Delete one task's journal and projection.

        Args:
            scope: Trusted runtime scope.
            task_id: The task to remove.

        Returns:
            ``True`` when something was removed. Idempotent: a repeated
            purge of an already-deleted task returns ``False`` rather
            than failing.
        """
        ...


@runtime_checkable
class BlobSweeper(Protocol):
    """Removes orphan blobs from durable storage."""

    async def list_orphans(self, scope: TaskScope) -> Sequence[BlobRetentionView]:
        """Return candidate orphan blobs for a scope.

        Args:
            scope: Trusted runtime scope.

        Returns:
            The candidates, with their reference flags already resolved.
        """
        ...

    async def sweep(self, scope: TaskScope, storage_ref: str) -> bool:
        """Delete one orphan blob.

        Args:
            scope: Trusted runtime scope.
            storage_ref: The blob to delete.

        Returns:
            ``True`` when bytes were removed.
        """
        ...


# ─────────────────────────────────────────────────────────────
# The sweeper
# ─────────────────────────────────────────────────────────────


class RetentionSweeper:
    """Applies due retention actions, intent first.

    Idempotent by construction rather than by bookkeeping: every action
    changes the state that made it due, so a second
    :meth:`run_once` over an unchanged world selects nothing. The one
    deliberate exception is a **failed archive**, which is retried —
    "failed archive/deletion retries are idempotent" is a requirement,
    not an accident.

    Args:
        store: The task store to read and append to.
        service: Optional command service used for lifecycle
            transitions, so pauses and cancellations go through exactly
            the same event rules as an agent's own. Without it, those
            transitions are reported as deferred rather than performed by
            a second, divergent code path.
        artifacts: Optional artifact store, for in-memory version
            expiry.
        config: Thresholds. Defaults to :class:`TaskMemoryConfig`.
        clock: Injected clock. Tests pass a controllable one; nothing
            here ever sleeps to advance time.
        archive: Optional archive writer. Required before a terminal
            journal may be deleted when ``archive_uri`` is configured.
        purge: Optional journal purge capability.
        blobs: Optional orphan blob sweeper.
        hot_keys: Optional :class:`HotKeyCleaner`, to drop a purged
            task's Redis keys instead of waiting out their TTLs.
    """

    def __init__(
        self,
        store: TaskMemoryStore,
        *,
        service: Optional[Any] = None,
        artifacts: Optional[Any] = None,
        config: Optional[TaskMemoryConfig] = None,
        clock: Callable[[], datetime] = utc_now,
        archive: Optional[ArchiveWriter] = None,
        purge: Optional[JournalPurge] = None,
        blobs: Optional[BlobSweeper] = None,
        hot_keys: Optional[Any] = None,
    ) -> None:
        """Initialize the sweeper."""
        self._store = store
        self._service = service
        self._artifacts = artifacts
        self._config = config or TaskMemoryConfig()
        self._clock = clock
        self._archive = archive
        self._purge = purge
        self._blobs = blobs
        self._hot_keys = hot_keys
        self.logger = logging.getLogger(__name__)

    # ── view construction ────────────────────────────────────────────

    async def _journal(self, scope: TaskScope, task_id: str) -> List[JournalEvent]:
        """Read a task's whole journal in bounded pages.

        Args:
            scope: Trusted runtime scope.
            task_id: The task to read.

        Returns:
            Its events, ascending.
        """
        events: List[JournalEvent] = []
        after = 0
        while True:
            page = await self._store.list_events(scope, task_id, after_seq=after, limit=_JOURNAL_PAGE)
            events.extend(page.events)
            if not page.has_more or not page.events:
                break
            after = page.next_seq
        return events

    @staticmethod
    def _anchors(events: Sequence[JournalEvent]) -> Tuple[Optional[datetime], Optional[datetime]]:
        """Derive the inactivity-pause and last-activity anchors.

        The sweeper's own events are **excluded** from "activity". A
        ``retention_scheduled`` intent, or the pause it announces, is
        maintenance — counting it as activity would let the sweeper keep
        resetting the clock it is measuring, so nothing would ever reach
        abandonment.

        Args:
            events: The task's journal, ascending.

        Returns:
            A ``(inactivity_paused_at, last_activity_at)`` pair.

        """
        paused_at: Optional[datetime] = None
        last_activity: Optional[datetime] = None

        for event in events:
            if event.actor is Actor.SWEEPER:
                if event.event_type is EventType.TASK_PAUSED:
                    paused_at = event.occurred_at
                elif event.event_type is EventType.TASK_RESUMED:
                    paused_at = None
                continue
            # Any non-sweeper event is real activity, and it also clears
            # a previous inactivity pause: the task is alive again.
            last_activity = event.occurred_at
            if event.event_type is EventType.TASK_RESUMED:
                paused_at = None

        return paused_at, last_activity

    async def _task_views(self, scope: TaskScope) -> List[TaskRetentionView]:
        """Build the immutable task views the pure selector consumes.

        Args:
            scope: Trusted runtime scope.

        Returns:
            One view per task in the scope, open and terminal alike.
        """
        views: List[TaskRetentionView] = []
        seen: set = set()

        for statuses in (None, tuple(s for s in TaskStatus if s.is_terminal)):
            cursor: Optional[str] = None
            while True:
                page = await self._store.list_tasks(scope, statuses=statuses, limit=_JOURNAL_PAGE, cursor=cursor)
                for summary in page.items:
                    if summary.task_id in seen:
                        continue
                    seen.add(summary.task_id)
                    snapshot = await self._store.load_snapshot(scope, summary.task_id)
                    if snapshot is None:
                        continue
                    events = await self._journal(scope, summary.task_id)
                    paused_at, last_activity = self._anchors(events)
                    views.append(
                        TaskRetentionView(
                            scope=scope,
                            task_id=snapshot.state.task_id,
                            status=snapshot.state.status,
                            updated_at=snapshot.state.updated_at,
                            terminal_at=snapshot.state.terminal_at,
                            inactivity_paused_at=paused_at,
                            last_activity_at=last_activity,
                            event_count=snapshot.event_count,
                        )
                    )
                cursor = page.next_cursor
                if cursor is None:
                    break
        return views

    async def _artifact_views(
        self, scope: TaskScope, tasks: Sequence[TaskRetentionView]
    ) -> List[ArtifactRetentionView]:
        """Build the immutable artifact views the pure selector consumes.

        Args:
            scope: Trusted runtime scope.
            tasks: The task views, for resolving each owner's terminal
                time.

        Returns:
            One view per retained artifact version.
        """
        if self._artifacts is None:
            return []

        terminal_by_task = {v.task_id: v.terminal_at for v in tasks}
        views: List[ArtifactRetentionView] = []
        cursor: Optional[str] = None
        while True:
            page = await self._artifacts.list(scope, limit=_JOURNAL_PAGE, cursor=cursor)
            for descriptor in page.items:
                pins = await self._artifacts.pins_for(scope, descriptor.ref)
                current = await self._artifacts.get_current(scope, descriptor.alias, task_id=descriptor.task_id)
                views.append(
                    ArtifactRetentionView(
                        scope=scope,
                        ref=descriptor.ref,
                        task_id=descriptor.task_id,
                        created_at=descriptor.created_at,
                        is_current=current is not None and current.ref == descriptor.ref,
                        pinned_by=pins,
                        retained_bytes=descriptor.byte_size or 0,
                        owner_terminal_at=terminal_by_task.get(descriptor.task_id),
                    )
                )
            cursor = page.next_cursor
            if cursor is None:
                break
        return views

    # ── intent ───────────────────────────────────────────────────────

    def _intent_event(self, action: DueAction) -> JournalEvent:
        """Build the ``retention_scheduled`` event announcing an action.

        Args:
            action: The action about to be attempted.

        Returns:
            The event, unsequenced.
        """
        return JournalEvent(
            event_id=new_id(),
            task_id=action.task_id or "",
            occurred_at=self._clock(),
            event_type=EventType.RETENTION_SCHEDULED,
            actor=Actor.SWEEPER,
            payload=action.to_payload(),
        )

    async def _announce(self, action: DueAction) -> bool:
        """Append an action's intent, unless an identical one is pending.

        Re-announcing on every retry of a failing archive would grow the
        journal without adding information, so an identical trailing
        intent suppresses a duplicate. The action itself still runs.

        Args:
            action: The action about to be attempted.

        Returns:
            ``True`` when the intent was appended or already present.
        """
        if action.task_id is None:
            return True
        events = await self._journal(action.scope, action.task_id)
        if events:
            last = events[-1]
            if (
                last.event_type is EventType.RETENTION_SCHEDULED
                and getattr(last.payload, "policy", None) == action.policy
                and getattr(last.payload, "action", None) == action.action
            ):
                return True
        await self._store.append_events(action.scope, action.task_id, [self._intent_event(action)])
        return True

    # ── the sweep ────────────────────────────────────────────────────

    async def run_once(self, scopes: Sequence[TaskScope]) -> SweepReport:
        """Apply every due retention action, once.

        Idempotent: over an unchanged world a second call selects nothing
        and the report is a no-op. Every action appends its intent event
        **before** the destructive work.

        Args:
            scopes: The scopes to sweep. Scope is always explicit —
                there is no "sweep everything" that could cross a
                boundary.

        Returns:
            A :class:`SweepReport` describing what happened, including
            what was deliberately deferred.
        """
        now = self._clock()
        report = SweepReport()

        for scope in scopes:
            tasks = await self._task_views(scope)

            for action in select_due_tasks(now, tasks, self._config):
                await self._apply_task_action(action, report)

            artifacts = await self._artifact_views(scope, tasks)
            for action in select_due_artifacts(now, artifacts, self._config):
                await self._apply_artifact_action(action, report)

            if self._blobs is not None:
                candidates = await self._blobs.list_orphans(scope)
                for action in select_due_blobs(now, candidates, self._config):
                    await self._apply_blob_action(action, report)

        if self._artifacts is not None:
            report.invalidations.extend(self._artifacts.drain_receipts())

        return report

    async def _apply_task_action(self, action: DueAction, report: SweepReport) -> None:
        """Apply one task-level action, intent first.

        Args:
            action: The due action.
            report: The report to record into.
        """
        assert action.task_id is not None

        if action.action in (RetentionAction.PAUSE, RetentionAction.CANCEL):
            if self._service is None:
                report.deferred.append((action.task_id, "no command service wired for lifecycle transitions"))
                return
            await self._announce(action)
            snapshot = await self._store.load_snapshot(action.scope, action.task_id)
            if snapshot is None:
                return
            status = TaskStatus.PAUSED if action.action == RetentionAction.PAUSE else TaskStatus.CANCELLED
            try:
                await self._service.update_task(
                    action.scope,
                    action.task_id,
                    expected_revision=snapshot.state.revision,
                    status=status,
                    reason=action.reason,
                    actor=Actor.SWEEPER,
                )
            except Exception as exc:  # noqa: BLE001 — one bad task must not stop the sweep
                report.errors.append((action.task_id, f"{type(exc).__name__}: {exc}"))
                return
            (report.paused if status is TaskStatus.PAUSED else report.cancelled).append(action.task_id)
            return

        # Terminal expiry.
        await self._announce(action)

        reference: Optional[str] = None
        if action.action == RetentionAction.ARCHIVE_AND_DELETE:
            if self._archive is None:
                report.deferred.append((action.task_id, "archive_uri is configured but no archive writer is wired"))
                return
            # Read AFTER announcing, so the archive contains the very
            # event recording the intent to destroy it. Without that the
            # archive would omit the one fact a reader most needs: why
            # this journal ends here.
            events = await self._journal(action.scope, action.task_id)
            try:
                reference = await self._archive.write(action.archive_uri or "", action.task_id, events)
                verified = await self._archive.verify(reference, len(events))
            except Exception as exc:  # noqa: BLE001 — a failed archive must not delete
                report.errors.append((action.task_id, f"archive failed: {type(exc).__name__}: {exc}"))
                report.deferred.append((action.task_id, "archive failed; deletion not attempted"))
                return
            if not verified:
                report.deferred.append((action.task_id, ARCHIVE_VERIFY_FAILED))
                return
            report.archived.append(action.task_id)

        if self._purge is None:
            report.deferred.append((action.task_id, "no journal purge capability wired"))
            return
        try:
            if await self._purge.purge_task(action.scope, action.task_id):
                report.deleted.append(action.task_id)
                # Honest accounting: the journal holding this task's
                # retention intent is now gone. Say where it went, or
                # that it went nowhere.
                report.audit_destroyed.append((action.task_id, reference))
                if self._hot_keys is not None:
                    await self._hot_keys.forget_task(action.scope, action.task_id)
        except Exception as exc:  # noqa: BLE001
            report.errors.append((action.task_id, f"purge failed: {type(exc).__name__}: {exc}"))

    async def _apply_artifact_action(self, action: DueAction, report: SweepReport) -> None:
        """Apply one artifact expiry, intent first.

        Args:
            action: The due action.
            report: The report to record into.
        """
        if self._artifacts is None:
            return
        await self._announce(action)
        for ref in action.target_refs:
            try:
                if await self._artifacts.evict(action.scope, ref):
                    report.expired_versions.append(ref)
            except Exception as exc:  # noqa: BLE001
                report.errors.append((str(ref), f"{type(exc).__name__}: {exc}"))

    async def _apply_blob_action(self, action: DueAction, report: SweepReport) -> None:
        """Apply one orphan blob sweep.

        Args:
            action: The due action.
            report: The report to record into.
        """
        if self._blobs is None or action.storage_ref is None:
            return
        try:
            if await self._blobs.sweep(action.scope, action.storage_ref):
                report.swept_blobs.append(action.storage_ref)
        except Exception as exc:  # noqa: BLE001
            report.errors.append((action.storage_ref, f"{type(exc).__name__}: {exc}"))


class ArchiveVerificationError(Exception):
    """A written archive could not be read back and confirmed complete.

    Raised only by :class:`JsonlArchiveWriter` internals; the sweeper
    turns it into a deferral. It exists so "the archive is bad" is
    distinguishable from "the write raised", because the two have
    different causes and the same consequence: **do not delete**.
    """


#: Deferral reason recorded when an archive is written but does not
#: verify. Named so operators can grep for it.
ARCHIVE_VERIFY_FAILED: str = "archive did not verify; deletion not attempted"


class JsonlArchiveWriter:
    """Writes a terminal task's journal as JSONL and verifies it.

    The format is one canonical JSON object per line, in sequence order,
    which is append-friendly, streamable and trivially countable — the
    last property is what makes verification cheap enough to be
    mandatory rather than aspirational.

    **Verification re-reads the object.** It is not enough to trust the
    write call's return value: the whole point is to catch a storage
    layer that accepted bytes it did not durably keep. :meth:`verify`
    downloads what was written, parses every line, and checks the count
    against what was archived. Only then may the source be deleted.

    **Re-archiving is idempotent.** A retry after a crash between write
    and delete finds byte-identical content already present and accepts
    it, rather than writing a second copy under a new name. That is what
    stops "crash, retry" producing duplicate archives.

    Args:
        blobs: The blob store, reused for its verified file-manager
            access rather than duplicating that logic here.
        scope: Trusted runtime scope, which fixes the archive sub-tree.
        segment: Archive path segment.
    """

    def __init__(self, blobs: Any, scope: TaskScope, *, segment: str = "_archive") -> None:
        """Initialize the writer."""
        self._blobs = blobs
        self._scope = scope
        self._segment = segment
        self.logger = logging.getLogger(__name__)

    def archive_key(self, task_id: str) -> str:
        """Return the deterministic archive key for one task.

        Deterministic on purpose: a retry must land on the *same* key so
        the second attempt is recognisably the same archive rather than
        a duplicate.

        Args:
            task_id: The task being archived.

        Returns:
            The storage key.
        """
        root = self._blobs.archive_prefix(self._scope, segment=self._segment)
        return f"{root}/{self._blobs._segment(task_id)}.jsonl"

    @staticmethod
    def encode(events: Sequence[JournalEvent]) -> bytes:
        """Serialize a journal as canonical JSONL.

        Args:
            events: The events, in sequence order.

        Returns:
            The encoded bytes, one event per line.
        """
        import orjson

        lines = [orjson.dumps(e.model_dump(mode="json"), option=orjson.OPT_SORT_KEYS) for e in events]
        return b"\n".join(lines) + (b"\n" if lines else b"")

    async def write(self, uri: str, task_id: str, events: Sequence[JournalEvent]) -> str:
        """Write a task's journal as JSONL and return its location.

        Args:
            uri: Configured archive destination. Recorded in the intent
                event; the concrete location comes from the blob store's
                own scope sub-tree, so an archive can never be written
                outside it.
            task_id: The task being archived.
            events: Its complete journal, INCLUDING the final retention
                event announcing the deletion.

        Returns:
            The storage key written.

        Raises:
            ArchiveVerificationError: If the write is refused. No
                reference is returned, so the caller cannot proceed to
                delete.
        """
        key = self.archive_key(task_id)
        payload = self.encode(events)

        existing = await self._existing(key)
        if existing is not None and existing == payload:
            # An identical archive is already there: this is a retry
            # after a crash between archive and delete. Accept it rather
            # than writing a duplicate.
            self.logger.info("[TaskMemory] archive for %s already present and identical", task_id)
            return key

        try:
            written = await self._blobs._fm.create_from_bytes(key, payload)
        except Exception as exc:  # noqa: BLE001
            raise ArchiveVerificationError(f"failed to write archive {key!r}: {exc}") from exc
        if written is False:
            raise ArchiveVerificationError(f"file manager declined to write archive {key!r}")
        return key

    async def verify(self, reference: str, expected_events: int) -> bool:
        """Confirm a written archive is readable and complete.

        Args:
            reference: What :meth:`write` returned.
            expected_events: How many events it should contain.

        Returns:
            ``True`` only when the object reads back, every line parses,
            and the count matches. Any doubt returns ``False``, which
            the sweeper treats as "do not delete".
        """
        try:
            payload = await self._blobs._download(reference)
        except Exception as exc:  # noqa: BLE001 — unreadable is unverified
            self.logger.warning("Archive %s could not be read back: %s", reference, exc)
            return False

        import orjson

        lines = [line for line in payload.split(b"\n") if line.strip()]
        if len(lines) != expected_events:
            self.logger.warning("Archive %s holds %d events, expected %d", reference, len(lines), expected_events)
            return False
        for line in lines:
            try:
                orjson.loads(line)
            except Exception as exc:  # noqa: BLE001
                self.logger.warning("Archive %s has an unparseable line: %s", reference, exc)
                return False
        return True

    async def _existing(self, key: str) -> Optional[bytes]:
        """Return an already-written archive's bytes, if any.

        Args:
            key: The archive key.

        Returns:
            The bytes, or ``None`` when absent or unreadable.
        """
        try:
            if not await self._blobs._fm.exists(key):
                return None
            return await self._blobs._download(key)
        except Exception:  # noqa: BLE001 — treat as absent and rewrite
            return None


class HotKeyCleaner:
    """Removes a purged task's Redis hot keys.

    Terminal deletion removes the durable rows; the lease, recall and
    context keys for that task would otherwise linger until their TTLs
    expire. They are all TTL-bounded already, so this is tidiness rather
    than correctness — which is exactly why it never raises: a failure
    here must not turn a completed purge into a reported error.

    Args:
        association: A ``TaskAssociationStore``, which owns the key
            families and their naming.
    """

    def __init__(self, association: Any) -> None:
        """Initialize the cleaner."""
        self._association = association
        self.logger = logging.getLogger(__name__)

    async def forget_task(self, scope: TaskScope, task_id: str) -> int:
        """Delete the hot keys belonging to one task.

        Args:
            scope: Trusted runtime scope.
            task_id: The purged task.

        Returns:
            How many keys were removed. ``0`` on any failure.
        """
        try:
            redis = self._association._redis()
            keys = [self._association.lease_key(scope, task_id)]
            removed = await redis.delete(*keys)
            return int(removed or 0)
        except Exception as exc:  # noqa: BLE001 — see class docstring
            self.logger.debug("Could not clear hot keys for %s: %s", task_id, exc)
            return 0


class PeriodicRetention:
    """Runs a sweeper on an interval, for single-process deployments.

    A host with a qworker deployment should schedule
    :meth:`RetentionSweeper.run_once` there instead. This exists so a
    single-process deployment does not have to invent one, and it
    introduces **no queue dependency** — it is an ``asyncio`` task with
    explicit startup and shutdown.

    Args:
        sweeper: The sweeper to run.
        scopes: A callable returning the scopes to sweep each cycle, so
            the set can change without restarting the loop.
        interval_seconds: Seconds between sweeps.
    """

    def __init__(
        self,
        sweeper: RetentionSweeper,
        scopes: Callable[[], Sequence[TaskScope]],
        *,
        interval_seconds: float = 3600.0,
    ) -> None:
        """Initialize the periodic runner."""
        self._sweeper = sweeper
        self._scopes = scopes
        self._interval = interval_seconds
        self._task: Optional[asyncio.Task] = None
        self.logger = logging.getLogger(__name__)

    @property
    def is_running(self) -> bool:
        """Whether the loop is active."""
        return self._task is not None and not self._task.done()

    async def start(self) -> None:
        """Start the loop. Idempotent."""
        if self.is_running:
            return
        self._task = asyncio.create_task(self._loop(), name="task-memory-retention")

    async def stop(self) -> None:
        """Stop the loop and wait for it to finish. Idempotent."""
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _loop(self) -> None:
        """Sweep on the configured interval until cancelled."""
        while True:
            try:
                await self._sweeper.run_once(self._scopes())
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — a bad sweep must not kill the loop
                self.logger.warning("[TaskMemory] retention sweep failed: %s", exc)
            await asyncio.sleep(self._interval)
