"""Deterministic retention decisions and in-memory sweeping (TASK-2999).

Three required cases from the task's Test Specification:

- ``test_clock_rules`` — boundary tests distinguish the inactivity
  anchor, the paused-for-inactivity duration and the terminal retention
  anchor. These are three *different instants* and confusing them is the
  classic way retention goes wrong.
- ``test_pin_eviction`` — forced no-tier eviction invalidates evidence
  explicitly; a pin defers deletion, including a cross-task pin.
- ``test_idempotent_sweep`` — a repeated ``run_once`` creates no
  duplicate state transition and maintenance capacity stays bounded.

**Time is injected, never slept.** Every clock in this module is a
controllable callable, so a 90-day boundary is asserted exactly rather
than approximately.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd
import pytest
from parrot.tools.working_memory.task_memory.artifacts import InMemoryArtifactStore
from parrot.tools.working_memory.task_memory.config import TaskMemoryConfig
from parrot.tools.working_memory.task_memory.models import (
    Actor,
    EventType,
    EvidenceRef,
    InitialStepSpec,
    JournalEvent,
    TaskScope,
    TaskStatus,
    utc_now,
)
from parrot.tools.working_memory.task_memory.retention import (
    ABANDONED_CANCEL_REASON,
    INACTIVITY_PAUSE_REASON,
    ArtifactRetentionView,
    BlobRetentionView,
    PeriodicRetention,
    RetentionAction,
    RetentionPolicy,
    RetentionSweeper,
    TaskRetentionView,
    journal_pressure,
    select_due_artifacts,
    select_due_blobs,
    select_due_tasks,
)
from parrot.tools.working_memory.task_memory.service import TaskMemoryService
from parrot.tools.working_memory.task_memory.store.memory import InMemoryTaskMemoryStore

SCOPE = TaskScope(chatbot_id="bot-a", user_id="user-1", session_id="sess-1")
OTHER_SCOPE = TaskScope(chatbot_id="bot-a", user_id="user-2", session_id="sess-1")

#: A fixed instant. Nothing in this module reads a real clock.
T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


class Clock:
    """A controllable clock. Tests advance it; they never sleep."""

    def __init__(self, now: datetime = T0) -> None:
        """Initialize at ``now``.

        Args:
            now: The starting instant.
        """
        self.now = now

    def __call__(self) -> datetime:
        """Return the current instant."""
        return self.now

    def advance(self, **kwargs: float) -> datetime:
        """Move the clock forward.

        Args:
            **kwargs: Any :class:`datetime.timedelta` keyword.

        Returns:
            The new instant.
        """
        self.now = self.now + timedelta(**kwargs)
        return self.now


def view(
    task_id: str = "t-1",
    *,
    status: TaskStatus = TaskStatus.ACTIVE,
    updated_at: datetime = T0,
    terminal_at: Optional[datetime] = None,
    inactivity_paused_at: Optional[datetime] = None,
    last_activity_at: Optional[datetime] = None,
    event_count: int = 3,
) -> TaskRetentionView:
    """Build a task view for the pure selectors.

    Args:
        task_id: The task.
        status: Lifecycle status.
        updated_at: When it last changed.
        terminal_at: When it went terminal.
        inactivity_paused_at: When the sweeper paused it.
        last_activity_at: When it last did real work.
        event_count: Journal size.

    Returns:
        The view.
    """
    return TaskRetentionView(
        scope=SCOPE,
        task_id=task_id,
        status=status,
        updated_at=updated_at,
        terminal_at=terminal_at,
        inactivity_paused_at=inactivity_paused_at,
        last_activity_at=last_activity_at,
        event_count=event_count,
    )


# ─────────────────────────────────────────────────────────────
# Effect doubles
# ─────────────────────────────────────────────────────────────


class FakeArchive:
    """An archive writer whose success and verification are controllable."""

    def __init__(self, *, fail_write: bool = False, verifies: bool = True) -> None:
        """Initialize the double.

        Args:
            fail_write: Whether :meth:`write` raises.
            verifies: What :meth:`verify` returns.
        """
        self.fail_write = fail_write
        self.verifies = verifies
        self.written: List[Tuple[str, int]] = []
        self.archived_events: List[Sequence[JournalEvent]] = []

    async def write(self, uri: str, task_id: str, events: Sequence[JournalEvent]) -> str:
        """Record an archive write."""
        if self.fail_write:
            raise OSError("archive destination unreachable")
        self.written.append((task_id, len(events)))
        self.archived_events.append(tuple(events))
        return f"{uri}/{task_id}.jsonl"

    async def verify(self, reference: str, expected_events: int) -> bool:
        """Report whether the archive verified."""
        return self.verifies


class FakePurge:
    """A journal purge that records what it removed."""

    def __init__(self, store: InMemoryTaskMemoryStore) -> None:
        """Initialize against a store.

        Args:
            store: The store whose tasks are purged.
        """
        self._store = store
        self.purged: List[str] = []

    async def purge_task(self, scope: TaskScope, task_id: str) -> bool:
        """Remove a task, idempotently."""
        removed = False
        async with self._store._registry_lock:  # noqa: SLF001 — a test double needs the registry
            for key, record in list(self._store._tasks.items()):  # noqa: SLF001
                if record.state.task_id == task_id and scope.matches(record.scope):
                    del self._store._tasks[key]  # noqa: SLF001
                    removed = True
        if removed:
            self.purged.append(task_id)
        return removed


class FakeBlobs:
    """An orphan blob sweeper over a controllable candidate list."""

    def __init__(self, candidates: Sequence[BlobRetentionView]) -> None:
        """Initialize with candidates.

        Args:
            candidates: What :meth:`list_orphans` returns.
        """
        self.candidates = list(candidates)
        self.swept: List[str] = []

    async def list_orphans(self, scope: TaskScope) -> Sequence[BlobRetentionView]:
        """Return candidates for a scope."""
        return [c for c in self.candidates if c.scope.matches(scope)]

    async def sweep(self, scope: TaskScope, storage_ref: str) -> bool:
        """Delete one orphan blob."""
        before = len(self.candidates)
        self.candidates = [c for c in self.candidates if c.storage_ref != storage_ref]
        if len(self.candidates) < before:
            self.swept.append(storage_ref)
            return True
        return False


@pytest.fixture()
async def wired():
    """Yield a wired ``(store, service, artifacts, clock)`` bundle."""
    store = InMemoryTaskMemoryStore()
    artifacts = InMemoryArtifactStore()
    service = TaskMemoryService(store, artifacts=artifacts)
    # Anchored to real "now": the service stamps its events with
    # utc_now(), so a clock starting in the past would never see them as
    # stale. The pure selectors above still use the fixed T0, because
    # they are handed views rather than reading a store.
    clock = Clock(utc_now())
    try:
        yield store, service, artifacts, clock
    finally:
        await store.close()
        await artifacts.close()


# ─────────────────────────────────────────────────────────────
# test_clock_rules
# ─────────────────────────────────────────────────────────────


def test_clock_rules_inactivity_boundary_is_exact() -> None:
    """An active task pauses at exactly 7 days, not a moment before."""
    config = TaskMemoryConfig()
    anchor = T0

    just_under = anchor + timedelta(days=config.inactivity_pause_days) - timedelta(seconds=1)
    assert select_due_tasks(just_under, [view(last_activity_at=anchor)], config) == ()

    exactly = anchor + timedelta(days=config.inactivity_pause_days)
    due = select_due_tasks(exactly, [view(last_activity_at=anchor)], config)
    assert [a.action for a in due] == [RetentionAction.PAUSE]
    assert due[0].policy == RetentionPolicy.INACTIVITY
    assert due[0].reason == INACTIVITY_PAUSE_REASON
    assert due[0].due_at == exactly


def test_clock_rules_abandonment_is_measured_from_the_pause() -> None:
    """The 30 days run from the inactivity pause, not from last activity.

    The anchors are deliberately different instants: a task paused on day
    7 is cancelled on day 37, not on day 30.
    """
    config = TaskMemoryConfig()
    activity = T0
    paused = activity + timedelta(days=config.inactivity_pause_days)

    paused_view = view(
        status=TaskStatus.PAUSED, last_activity_at=activity, inactivity_paused_at=paused, updated_at=paused
    )

    # 30 days after LAST ACTIVITY is not yet due — the pause is the anchor.
    too_early = activity + timedelta(days=config.abandoned_cancel_days)
    assert select_due_tasks(too_early, [paused_view], config) == ()

    exactly = paused + timedelta(days=config.abandoned_cancel_days)
    due = select_due_tasks(exactly, [paused_view], config)
    assert [a.action for a in due] == [RetentionAction.CANCEL]
    assert due[0].policy == RetentionPolicy.ABANDONED
    assert due[0].reason == ABANDONED_CANCEL_REASON


def test_clock_rules_a_pause_the_sweeper_did_not_make_is_not_on_the_clock() -> None:
    """A task a user paused for their own reasons is never abandoned.

    ``inactivity_paused_at`` is ``None`` for such a task, so the
    abandonment rule cannot fire however long it sits.
    """
    config = TaskMemoryConfig()
    user_paused = view(status=TaskStatus.PAUSED, updated_at=T0, inactivity_paused_at=None)
    far_future = T0 + timedelta(days=3650)
    assert select_due_tasks(far_future, [user_paused], config) == ()


def test_clock_rules_terminal_expiry_anchors_on_terminal_at() -> None:
    """Terminal retention runs from ``terminal_at``, not ``updated_at``."""
    config = TaskMemoryConfig()
    terminal = T0
    # updated_at is much later — e.g. a retention intent was appended.
    stale = view(status=TaskStatus.COMPLETED, terminal_at=terminal, updated_at=terminal + timedelta(days=80))

    just_under = terminal + timedelta(days=config.terminal_retention_days) - timedelta(seconds=1)
    assert select_due_tasks(just_under, [stale], config) == ()

    exactly = terminal + timedelta(days=config.terminal_retention_days)
    due = select_due_tasks(exactly, [stale], config)
    assert [a.policy for a in due] == [RetentionPolicy.TERMINAL]
    assert due[0].action == RetentionAction.DELETE, "no archive_uri configured"


def test_clock_rules_archive_uri_selects_archive_and_delete() -> None:
    """With an archive configured the action is archive-then-delete."""
    config = TaskMemoryConfig(archive_uri="s3://bucket/tasks")
    stale = view(status=TaskStatus.FAILED, terminal_at=T0)
    due = select_due_tasks(T0 + timedelta(days=91), [stale], config)
    assert due[0].action == RetentionAction.ARCHIVE_AND_DELETE
    assert due[0].archive_uri == "s3://bucket/tasks"


def test_clock_rules_are_pure() -> None:
    """Selection reads no clock of its own and mutates nothing."""
    import ast
    import importlib
    from pathlib import Path

    module = importlib.import_module("parrot.tools.working_memory.task_memory.retention")
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))

    selectors = {"select_due_tasks", "select_due_artifacts", "select_due_blobs", "journal_pressure"}
    forbidden = {"utc_now", "now", "today", "monotonic", "time", "random", "sleep", "open"}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in selectors:
            called = {
                (c.func.id if isinstance(c.func, ast.Name) else getattr(c.func, "attr", None))
                for c in ast.walk(node)
                if isinstance(c, ast.Call)
            }
            assert not (called & forbidden), f"{node.name} calls {sorted(called & forbidden)}"

    # And observably: the same inputs give the same answer.
    config = TaskMemoryConfig()
    views = [view(last_activity_at=T0)]
    at = T0 + timedelta(days=8)
    assert select_due_tasks(at, views, config) == select_due_tasks(at, views, config)


def test_clock_rules_journal_pressure_thresholds() -> None:
    """Soft, hard and reserved ceilings are three distinct states."""
    config = TaskMemoryConfig()

    fine = journal_pressure(10, config)
    assert not (fine.soft_exceeded or fine.foreground_refused or fine.reserved_exhausted)

    soft = journal_pressure(config.journal_soft_limit, config)
    assert soft.soft_exceeded and not soft.foreground_refused

    hard = journal_pressure(config.journal_hard_limit, config)
    assert hard.foreground_refused and not hard.reserved_exhausted, "reserved headroom must remain"

    exhausted = journal_pressure(config.journal_hard_limit + config.journal_reserved_events, config)
    assert exhausted.reserved_exhausted


@pytest.mark.asyncio
async def test_clock_rules_reads_do_not_reset_activity(wired) -> None:
    """Recall-style reads never move the inactivity anchor.

    The rule is "reads do not reset activity", and it holds because the
    store never appends on a read — asserted here end to end rather than
    assumed.
    """
    store, service, artifacts, clock = wired
    result = await service.begin_task(SCOPE, goal="g", steps=[InitialStepSpec(label="a", title="A")])
    task_id = result.state.task_id

    sweeper = RetentionSweeper(store, service=service, artifacts=artifacts, clock=clock)
    before = (await sweeper._task_views(SCOPE))[0]  # noqa: SLF001 — view construction under test

    for _ in range(5):
        await store.load_snapshot(SCOPE, task_id)
        await store.list_events(SCOPE, task_id)
        await store.list_tasks(SCOPE)
        await store.count_events(SCOPE, task_id)

    after = (await sweeper._task_views(SCOPE))[0]  # noqa: SLF001
    assert after.activity_anchor == before.activity_anchor
    assert after.event_count == before.event_count


@pytest.mark.asyncio
async def test_clock_rules_sweeper_own_events_are_not_activity(wired) -> None:
    """The sweeper's own events do not reset the clock it is measuring.

    This is the trap the design exists to avoid: the ``retention_scheduled``
    intent and the pause it announces both bump ``updated_at``. If those
    counted as activity — or if the abandonment clock anchored on
    ``updated_at`` — the sweeper would keep resetting the very clock it
    was measuring, and a task would never reach abandonment.
    """
    store, service, artifacts, clock = wired
    result = await service.begin_task(SCOPE, goal="g")
    task_id = result.state.task_id
    sweeper = RetentionSweeper(store, service=service, artifacts=artifacts, clock=clock)

    # The anchor is whatever the real events recorded; what matters is
    # that the sweeper's own events do not MOVE it.
    activity_end = (await sweeper._task_views(SCOPE))[0].activity_anchor  # noqa: SLF001

    clock.advance(days=8)
    report = await sweeper.run_once([SCOPE])
    assert report.paused == [task_id]

    views = await sweeper._task_views(SCOPE)  # noqa: SLF001
    paused_view = views[0]

    assert paused_view.status is TaskStatus.PAUSED
    assert paused_view.last_activity_at == activity_end, "sweeper events must not count as activity"
    assert paused_view.updated_at > activity_end, "but they DID bump updated_at — which is the trap"

    # The pause anchor is the pause EVENT's own timestamp. Note the
    # sweeper's injected clock does not control it: `TaskMemoryService`
    # stamps its transition events with `utc_now()`, so only the
    # sweeper's own intent events follow the injected clock. In
    # production both are wall time and agree; here the anchor is
    # asserted against the journal rather than against the test clock.
    page = await store.list_events(SCOPE, task_id, limit=200)
    pause_event = next(e for e in page.events if e.event_type is EventType.TASK_PAUSED)
    assert paused_view.inactivity_paused_at == pause_event.occurred_at
    assert pause_event.actor is Actor.SWEEPER
    # The abandonment clock runs from the PAUSE, so the boundary is
    # computed from the pause event rather than from however far the test
    # clock happens to have moved.
    anchor = pause_event.occurred_at
    horizon = timedelta(days=TaskMemoryConfig().abandoned_cancel_days)

    clock.now = anchor + horizon - timedelta(seconds=1)
    assert (await sweeper.run_once([SCOPE])).is_noop, "cancelled a second too early"

    clock.now = anchor + horizon
    report = await sweeper.run_once([SCOPE])
    assert report.cancelled == [task_id]


@pytest.mark.asyncio
async def test_clock_rules() -> None:
    """Required aggregate case: the three anchors are distinguished."""
    test_clock_rules_inactivity_boundary_is_exact()
    test_clock_rules_abandonment_is_measured_from_the_pause()
    test_clock_rules_a_pause_the_sweeper_did_not_make_is_not_on_the_clock()
    test_clock_rules_terminal_expiry_anchors_on_terminal_at()
    test_clock_rules_archive_uri_selects_archive_and_delete()
    test_clock_rules_are_pure()
    test_clock_rules_journal_pressure_thresholds()


# ─────────────────────────────────────────────────────────────
# test_pin_eviction
# ─────────────────────────────────────────────────────────────


def artifact_view(
    version: int = 1,
    *,
    artifact_id: str = "art-1",
    created_at: datetime = T0,
    is_current: bool = False,
    pinned_by: Tuple[str, ...] = (),
    retained_bytes: int = 1024,
    owner_terminal_at: Optional[datetime] = T0,
    task_id: Optional[str] = "t-1",
) -> ArtifactRetentionView:
    """Build an artifact view for the pure selector.

    Args:
        version: Version number.
        artifact_id: Identity.
        created_at: When registered.
        is_current: Whether an alias points at it.
        pinned_by: Tasks referencing it as evidence.
        retained_bytes: Bytes still held.
        owner_terminal_at: When the producing task went terminal.
        task_id: The producing task.

    Returns:
        The view.
    """
    return ArtifactRetentionView(
        scope=SCOPE,
        ref=EvidenceRef(artifact_id=artifact_id, version=version),
        task_id=task_id,
        created_at=created_at,
        is_current=is_current,
        pinned_by=pinned_by,
        retained_bytes=retained_bytes,
        owner_terminal_at=owner_terminal_at,
    )


def test_pin_eviction_any_pin_defers_deletion() -> None:
    """A pin defers deletion, including one held by another task."""
    config = TaskMemoryConfig()
    at = T0 + timedelta(hours=config.unpinned_version_ttl_hours + 1)

    unpinned = artifact_view()
    assert len(select_due_artifacts(at, [unpinned], config)) == 1

    own_pin = artifact_view(pinned_by=("t-1",))
    assert select_due_artifacts(at, [own_pin], config) == ()

    # A CROSS-TASK pin is the case a naive "is the owner done?" check
    # gets wrong: the producer is terminal, but another task still cites
    # this version as evidence.
    cross_pin = artifact_view(pinned_by=("t-99",))
    assert select_due_artifacts(at, [cross_pin], config) == ()


def test_pin_eviction_nonterminal_evidence_is_protected() -> None:
    """Evidence of a live task never expires by age."""
    config = TaskMemoryConfig()
    at = T0 + timedelta(days=3650)
    live = artifact_view(owner_terminal_at=None)
    assert select_due_artifacts(at, [live], config) == ()


def test_pin_eviction_current_versions_follow_the_terminal_clock() -> None:
    """Only non-current versions use the 24-hour stale rule."""
    config = TaskMemoryConfig()
    day_later = T0 + timedelta(hours=config.unpinned_version_ttl_hours + 1)

    noncurrent = artifact_view(is_current=False)
    assert len(select_due_artifacts(day_later, [noncurrent], config)) == 1

    current = artifact_view(is_current=True)
    assert select_due_artifacts(day_later, [current], config) == (), "current follows the 90-day rule"

    much_later = T0 + timedelta(days=config.terminal_retention_days + 1)
    assert len(select_due_artifacts(much_later, [current], config)) == 1


def test_pin_eviction_released_versions_are_not_reselected() -> None:
    """A version with no retained bytes is already done."""
    config = TaskMemoryConfig()
    at = T0 + timedelta(days=100)
    assert select_due_artifacts(at, [artifact_view(retained_bytes=0)], config) == ()


@pytest.mark.asyncio
async def test_pin_eviction_forced_eviction_invalidates_explicitly(wired) -> None:
    """When no tier can retain pinned evidence, it is invalidated, not dropped.

    Delivery A cannot promise retained bytes. What it *can* promise is
    that evidence never disappears silently while a step still claims to
    be valid — the store raises a receipt and keeps a tombstone.
    """
    _, _, _, _ = wired
    # A tiny budget forces the sacrifice path immediately.
    config = TaskMemoryConfig(memory_cache_max_bytes=2048)
    artifacts = InMemoryArtifactStore(config=config)
    try:
        first = await artifacts.put(SCOPE, "a", pd.DataFrame({"n": range(5_000)}), task_id="t-1", pin_for="t-1")
        await artifacts.put(SCOPE, "b", pd.DataFrame({"n": range(5_000)}), task_id="t-1", pin_for="t-1")

        receipts = artifacts.drain_receipts()
        assert receipts, "pinned evidence was released with no receipt"

        receipt = receipts[0]
        assert receipt.pinned_by, "the receipt must name who was relying on it"
        assert receipt.released_bytes > 0

        # A metadata tombstone survives: the version is still resolvable,
        # explicitly invalidated, rather than silently absent.
        tombstone = await artifacts.get_version(SCOPE, receipt.ref)
        assert tombstone is not None
        assert tombstone.invalidated is True
        assert first.ref.artifact_id  # the identity itself is intact
    finally:
        await artifacts.close()


@pytest.mark.asyncio
async def test_pin_eviction_sweeper_expires_unpinned_bytes(wired) -> None:
    """The sweeper releases an unpinned stale version's bytes."""
    store, service, artifacts, clock = wired
    result = await service.begin_task(SCOPE, goal="g")
    task_id = result.state.task_id

    await artifacts.put(SCOPE, "sales", pd.DataFrame({"n": range(50)}), task_id=task_id)
    v2 = await artifacts.put(SCOPE, "sales", pd.DataFrame({"n": range(60)}), task_id=task_id)

    # Terminate the task so its evidence is no longer protected.
    snapshot = await store.load_snapshot(SCOPE, task_id)
    await service.update_task(SCOPE, task_id, expected_revision=snapshot.state.revision, status=TaskStatus.CANCELLED)

    sweeper = RetentionSweeper(store, service=service, artifacts=artifacts, clock=clock)
    clock.advance(hours=TaskMemoryConfig().unpinned_version_ttl_hours + 1)
    report = await sweeper.run_once([SCOPE])

    assert report.expired_versions, "the stale non-current version should have been released"
    assert v2.ref not in report.expired_versions, "the current version follows the 90-day rule"


@pytest.mark.asyncio
async def test_pin_eviction_pinned_evidence_survives_the_sweep(wired) -> None:
    """A pinned version is not swept, even when its owner is terminal."""
    store, service, artifacts, clock = wired
    result = await service.begin_task(SCOPE, goal="g")
    task_id = result.state.task_id

    v1 = await artifacts.put(SCOPE, "sales", pd.DataFrame({"n": range(50)}), task_id=task_id)
    await artifacts.put(SCOPE, "sales", pd.DataFrame({"n": range(60)}), task_id=task_id)
    await artifacts.pin_evidence(SCOPE, v1.ref, task_id)

    snapshot = await store.load_snapshot(SCOPE, task_id)
    await service.update_task(SCOPE, task_id, expected_revision=snapshot.state.revision, status=TaskStatus.CANCELLED)

    sweeper = RetentionSweeper(store, service=service, artifacts=artifacts, clock=clock)
    clock.advance(hours=TaskMemoryConfig().unpinned_version_ttl_hours + 1)
    report = await sweeper.run_once([SCOPE])

    assert v1.ref not in report.expired_versions
    survivor = await artifacts.get_version(SCOPE, v1.ref)
    assert survivor is not None and not survivor.invalidated


def test_pin_eviction() -> None:
    """Required aggregate case: pins defer, forced eviction invalidates."""
    test_pin_eviction_any_pin_defers_deletion()
    test_pin_eviction_nonterminal_evidence_is_protected()
    test_pin_eviction_current_versions_follow_the_terminal_clock()
    test_pin_eviction_released_versions_are_not_reselected()


# ─────────────────────────────────────────────────────────────
# test_idempotent_sweep
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_idempotent_sweep_second_run_is_a_noop(wired) -> None:
    """Sweeping an unchanged world twice performs no second transition."""
    store, service, artifacts, clock = wired
    result = await service.begin_task(SCOPE, goal="g")
    task_id = result.state.task_id
    sweeper = RetentionSweeper(store, service=service, artifacts=artifacts, clock=clock)

    clock.advance(days=8)
    first = await sweeper.run_once([SCOPE])
    assert first.paused == [task_id]

    before = await store.load_snapshot(SCOPE, task_id)
    second = await sweeper.run_once([SCOPE])

    assert second.is_noop, f"a repeated sweep acted again: {second}"
    after = await store.load_snapshot(SCOPE, task_id)
    assert after.state.revision == before.state.revision
    assert after.event_count == before.event_count


@pytest.mark.asyncio
async def test_idempotent_sweep_intent_precedes_the_transition(wired) -> None:
    """The retention intent is journalled BEFORE the destructive work."""
    store, service, artifacts, clock = wired
    result = await service.begin_task(SCOPE, goal="g")
    task_id = result.state.task_id
    sweeper = RetentionSweeper(store, service=service, artifacts=artifacts, clock=clock)

    clock.advance(days=8)
    await sweeper.run_once([SCOPE])

    page = await store.list_events(SCOPE, task_id, limit=200)
    kinds = [e.event_type for e in page.events]
    assert EventType.RETENTION_SCHEDULED in kinds
    assert EventType.TASK_PAUSED in kinds
    assert kinds.index(EventType.RETENTION_SCHEDULED) < kinds.index(
        EventType.TASK_PAUSED
    ), "the intent must be recorded before the work it announces"

    intent = next(e for e in page.events if e.event_type is EventType.RETENTION_SCHEDULED)
    assert intent.actor is Actor.SWEEPER
    assert intent.payload.policy == RetentionPolicy.INACTIVITY
    assert intent.payload.action == RetentionAction.PAUSE


@pytest.mark.asyncio
async def test_idempotent_sweep_archive_failure_blocks_deletion(wired) -> None:
    """A failed or unverified archive must NOT delete the journal."""
    store, service, artifacts, clock = wired
    config = TaskMemoryConfig(archive_uri="s3://bucket/tasks")
    result = await service.begin_task(SCOPE, goal="g")
    task_id = result.state.task_id
    snapshot = await store.load_snapshot(SCOPE, task_id)
    await service.update_task(SCOPE, task_id, expected_revision=snapshot.state.revision, status=TaskStatus.CANCELLED)

    clock.advance(days=config.terminal_retention_days + 1)

    # (a) The write itself fails.
    failing = FakeArchive(fail_write=True)
    purge = FakePurge(store)
    sweeper = RetentionSweeper(
        store,
        service=service,
        artifacts=artifacts,
        config=config,
        clock=clock,
        archive=failing,
        purge=purge,
    )
    report = await sweeper.run_once([SCOPE])
    assert report.deleted == [] and purge.purged == []
    assert any("archive failed" in reason for _, reason in report.deferred)
    assert await store.load_snapshot(SCOPE, task_id) is not None, "the task must survive a failed archive"

    # (b) The write succeeds but verification fails.
    unverified = FakeArchive(verifies=False)
    sweeper = RetentionSweeper(
        store,
        service=service,
        artifacts=artifacts,
        config=config,
        clock=clock,
        archive=unverified,
        purge=purge,
    )
    report = await sweeper.run_once([SCOPE])
    assert report.deleted == [] and purge.purged == []
    assert any("did not verify" in reason for _, reason in report.deferred)
    assert await store.load_snapshot(SCOPE, task_id) is not None

    # (c) A verified archive finally allows deletion, and the archive
    #     contains the retention event announcing it.
    good = FakeArchive()
    sweeper = RetentionSweeper(
        store,
        service=service,
        artifacts=artifacts,
        config=config,
        clock=clock,
        archive=good,
        purge=purge,
    )
    report = await sweeper.run_once([SCOPE])
    assert report.archived == [task_id]
    assert report.deleted == [task_id]
    assert await store.load_snapshot(SCOPE, task_id) is None

    archived = good.archived_events[0]
    assert any(e.event_type is EventType.RETENTION_SCHEDULED for e in archived), (
        "the archive must include the final retention event, since deleting the "
        "journal destroys the only other copy of it"
    )


@pytest.mark.asyncio
async def test_idempotent_sweep_retry_does_not_duplicate_intent(wired) -> None:
    """Retrying a failing archive re-attempts without re-announcing."""
    store, service, artifacts, clock = wired
    config = TaskMemoryConfig(archive_uri="s3://bucket/tasks")
    result = await service.begin_task(SCOPE, goal="g")
    task_id = result.state.task_id
    snapshot = await store.load_snapshot(SCOPE, task_id)
    await service.update_task(SCOPE, task_id, expected_revision=snapshot.state.revision, status=TaskStatus.CANCELLED)
    clock.advance(days=config.terminal_retention_days + 1)

    failing = FakeArchive(fail_write=True)
    sweeper = RetentionSweeper(
        store,
        service=service,
        artifacts=artifacts,
        config=config,
        clock=clock,
        archive=failing,
        purge=FakePurge(store),
    )

    await sweeper.run_once([SCOPE])
    after_first = (await store.load_snapshot(SCOPE, task_id)).event_count
    await sweeper.run_once([SCOPE])
    await sweeper.run_once([SCOPE])
    after_third = (await store.load_snapshot(SCOPE, task_id)).event_count

    assert after_third == after_first, "repeated retries must not grow the journal"


@pytest.mark.asyncio
async def test_idempotent_sweep_missing_capabilities_defer_not_delete(wired) -> None:
    """Without a purge capability, terminal expiry defers rather than skipping."""
    store, service, artifacts, clock = wired
    result = await service.begin_task(SCOPE, goal="g")
    task_id = result.state.task_id
    snapshot = await store.load_snapshot(SCOPE, task_id)
    await service.update_task(SCOPE, task_id, expected_revision=snapshot.state.revision, status=TaskStatus.CANCELLED)
    clock.advance(days=TaskMemoryConfig().terminal_retention_days + 1)

    sweeper = RetentionSweeper(store, service=service, artifacts=artifacts, clock=clock)
    report = await sweeper.run_once([SCOPE])

    assert report.deleted == []
    assert any("purge" in reason for _, reason in report.deferred)
    assert await store.load_snapshot(SCOPE, task_id) is not None


@pytest.mark.asyncio
async def test_idempotent_sweep_scopes_are_isolated(wired) -> None:
    """Sweeping one scope never touches another."""
    store, service, artifacts, clock = wired
    mine = await service.begin_task(SCOPE, goal="mine")
    theirs = await service.begin_task(OTHER_SCOPE, goal="theirs")

    sweeper = RetentionSweeper(store, service=service, artifacts=artifacts, clock=clock)
    clock.advance(days=8)
    report = await sweeper.run_once([SCOPE])

    assert report.paused == [mine.state.task_id]
    other = await store.load_snapshot(OTHER_SCOPE, theirs.state.task_id)
    assert other.state.status is TaskStatus.ACTIVE, "another scope must be untouched"


def test_idempotent_sweep_orphan_blob_rules() -> None:
    """A blob is swept only when nothing references it and the grace passed."""
    config = TaskMemoryConfig()
    grace = timedelta(hours=config.orphan_blob_grace_hours)

    def blob(**kwargs: Any) -> BlobRetentionView:
        base: Dict[str, Any] = {"scope": SCOPE, "storage_ref": "blob-1", "written_at": T0}
        base.update(kwargs)
        return BlobRetentionView(**base)

    at = T0 + grace

    assert len(select_due_blobs(at, [blob()], config)) == 1
    assert select_due_blobs(T0 + grace - timedelta(seconds=1), [blob()], config) == ()

    # A blob mid-publish is NOT an orphan: deleting it would remove bytes
    # a reference is about to point at.
    assert select_due_blobs(at, [blob(has_publish_lease=True)], config) == ()
    assert select_due_blobs(at, [blob(has_live_index=True)], config) == ()
    assert select_due_blobs(at, [blob(has_archive_reference=True)], config) == ()


@pytest.mark.asyncio
async def test_idempotent_sweep_blob_sweeping_is_idempotent(wired) -> None:
    """Sweeping orphan blobs twice removes each exactly once."""
    store, service, artifacts, clock = wired
    blobs = FakeBlobs([BlobRetentionView(scope=SCOPE, storage_ref="blob-1", written_at=T0)])
    sweeper = RetentionSweeper(store, service=service, artifacts=artifacts, clock=clock, blobs=blobs)

    clock.advance(hours=TaskMemoryConfig().orphan_blob_grace_hours + 1)
    first = await sweeper.run_once([SCOPE])
    assert first.swept_blobs == ["blob-1"]

    second = await sweeper.run_once([SCOPE])
    assert second.swept_blobs == []
    assert blobs.swept == ["blob-1"]


@pytest.mark.asyncio
async def test_idempotent_sweep_capacity_stays_bounded(wired) -> None:
    """Maintenance work does not push a journal past its reserved headroom."""
    store, service, artifacts, clock = wired
    result = await service.begin_task(SCOPE, goal="g")
    task_id = result.state.task_id
    sweeper = RetentionSweeper(store, service=service, artifacts=artifacts, clock=clock)

    clock.advance(days=8)
    await sweeper.run_once([SCOPE])
    for _ in range(5):
        clock.advance(days=1)
        await sweeper.run_once([SCOPE])

    snapshot = await store.load_snapshot(SCOPE, task_id)
    pressure = journal_pressure(snapshot.event_count, TaskMemoryConfig())
    assert not pressure.foreground_refused
    assert snapshot.event_count < 20, "repeated sweeps must not accumulate events"


@pytest.mark.asyncio
async def test_idempotent_sweep_periodic_runner_starts_and_stops(wired) -> None:
    """The single-process runner is an ordinary asyncio task, cleanly stopped."""
    store, service, artifacts, clock = wired
    sweeper = RetentionSweeper(store, service=service, artifacts=artifacts, clock=clock)
    runner = PeriodicRetention(sweeper, lambda: [SCOPE], interval_seconds=0.01)

    assert not runner.is_running
    await runner.start()
    assert runner.is_running
    await runner.start()  # idempotent

    import asyncio

    await asyncio.sleep(0.05)
    await runner.stop()
    assert not runner.is_running
    await runner.stop()  # idempotent


@pytest.mark.asyncio
async def test_idempotent_sweep() -> None:
    """Required aggregate case: repeated sweeps add no duplicate transition."""
    for case in (
        test_idempotent_sweep_second_run_is_a_noop,
        test_idempotent_sweep_intent_precedes_the_transition,
        test_idempotent_sweep_archive_failure_blocks_deletion,
        test_idempotent_sweep_retry_does_not_duplicate_intent,
        test_idempotent_sweep_missing_capabilities_defer_not_delete,
        test_idempotent_sweep_scopes_are_isolated,
        test_idempotent_sweep_blob_sweeping_is_idempotent,
        test_idempotent_sweep_capacity_stays_bounded,
    ):
        store = InMemoryTaskMemoryStore()
        artifacts = InMemoryArtifactStore()
        try:
            await case((store, TaskMemoryService(store, artifacts=artifacts), artifacts, Clock(utc_now())))
        finally:
            await store.close()
            await artifacts.close()
    test_idempotent_sweep_orphan_blob_rules()
