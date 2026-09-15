"""In-memory task journal and projection store (FEAT-538 / TASK-2978).

Three required cases from the task's Test Specification:

- ``test_concurrent_append`` — two revisions race; only one applicable
  batch wins and journal sequences have no gaps.
- ``test_idempotency`` — an exact retry returns the existing result even
  with a stale ``expected_revision``; a different payload under the same
  id fails.
- ``test_limits`` — foreign scope and exhausted capacity reject *before*
  mutation, and reserved recovery events stay appendable.

The module also runs the shared :class:`TaskMemoryStoreConformance` suite
published by TASK-2972, so this backend is held to exactly the same
storage invariants the PostgreSQL one will be (AC2).
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator, List, Optional

import pytest
from parrot.interfaces.task_memory import TaskMemoryStore
from parrot.tools.working_memory.task_memory.config import TaskMemoryConfig
from parrot.tools.working_memory.task_memory.models import (
    EventType,
    JournalEvent,
    LimitExceeded,
    ReducerError,
    RevisionConflict,
    ScopeViolation,
    TaskLifecyclePayload,
    TaskScope,
    TaskStatus,
)
from parrot.tools.working_memory.task_memory.reducer import REDUCER_VERSION
from parrot.tools.working_memory.task_memory.store.memory import InMemoryTaskMemoryStore, NoOpTransaction

from .conftest import TM_EPOCH
from .test_contracts import SCOPE_A, SCOPE_B, TaskMemoryStoreConformance

# ─────────────────────────────────────────────────────────────
# Conformance
# ─────────────────────────────────────────────────────────────


class TestInMemoryStoreConformance(TaskMemoryStoreConformance):
    """The in-memory backend must satisfy every shared storage invariant."""

    @pytest.fixture()
    async def store(self) -> AsyncIterator[TaskMemoryStore]:
        """Yield a fresh in-memory backend."""
        backend = InMemoryTaskMemoryStore()
        try:
            yield backend
        finally:
            await backend.close()


# ─────────────────────────────────────────────────────────────
# Local helpers
# ─────────────────────────────────────────────────────────────


def _event(
    task_id: str,
    *,
    event_id: str,
    event_type: EventType = EventType.TASK_STARTED,
    status: TaskStatus = TaskStatus.ACTIVE,
    goal: Optional[str] = None,
    reason: Optional[str] = None,
    seconds: int = 1,
) -> JournalEvent:
    """Build a deterministic lifecycle event.

    Args:
        task_id: Owning task.
        event_id: Explicit id, so redelivery can be simulated exactly.
        event_type: The event type.
        status: Status carried in the payload.
        goal: Goal, for a ``task_started``.
        reason: Optional reason, used to make two same-id events differ.
        seconds: Offset from :data:`TM_EPOCH`.

    Returns:
        The event.
    """
    from datetime import timedelta

    return JournalEvent(
        event_id=event_id,
        task_id=task_id,
        event_type=event_type,
        occurred_at=TM_EPOCH + timedelta(seconds=seconds),
        payload=TaskLifecyclePayload(status=status, goal=goal, reason=reason),
    )


async def _create(store: InMemoryTaskMemoryStore, scope: TaskScope, task_id: str, goal: str = "do the thing"):
    """Create one task with a goal-carrying ``task_started``.

    Args:
        store: The backend.
        scope: Owning scope.
        task_id: The task id.
        goal: The task's goal.

    Returns:
        The append result.
    """
    return await store.create_task(scope, goal=goal, events=[_event(task_id, event_id=f"{task_id}-e1", goal=goal)])


def _pause(task_id: str, event_id: str, *, reason: Optional[str] = None, seconds: int = 2) -> JournalEvent:
    """Build a ``task_paused`` event.

    Args:
        task_id: Owning task.
        event_id: Explicit id.
        reason: Optional reason.
        seconds: Offset from :data:`TM_EPOCH`.

    Returns:
        The event.
    """
    return _event(
        task_id,
        event_id=event_id,
        event_type=EventType.TASK_PAUSED,
        status=TaskStatus.PAUSED,
        reason=reason,
        seconds=seconds,
    )


def _resume(task_id: str, event_id: str, *, seconds: int = 3) -> JournalEvent:
    """Build a ``task_resumed`` event.

    Args:
        task_id: Owning task.
        event_id: Explicit id.
        seconds: Offset from :data:`TM_EPOCH`.

    Returns:
        The event.
    """
    return _event(
        task_id,
        event_id=event_id,
        event_type=EventType.TASK_RESUMED,
        status=TaskStatus.ACTIVE,
        seconds=seconds,
    )


# ─────────────────────────────────────────────────────────────
# test_concurrent_append
# ─────────────────────────────────────────────────────────────


async def test_concurrent_append_only_one_revision_wins(tm_store: InMemoryTaskMemoryStore) -> None:
    """Two batches racing on the same expected revision: exactly one wins."""
    created = await _create(tm_store, SCOPE_A, "t-1")

    async def attempt(event_id: str, reason: str):
        return await tm_store.append_events(
            SCOPE_A,
            "t-1",
            [_pause("t-1", event_id, reason=reason)],
            expected_revision=created.revision,
        )

    results = await asyncio.gather(
        attempt("t-1-a", "first"),
        attempt("t-1-b", "second"),
        return_exceptions=True,
    )

    winners = [r for r in results if not isinstance(r, BaseException)]
    conflicts = [r for r in results if isinstance(r, RevisionConflict)]
    assert len(winners) == 1, f"exactly one batch may win the race, got {results}"
    assert len(conflicts) == 1, f"the loser must see a RevisionConflict, got {results}"

    snapshot = await tm_store.load_snapshot(SCOPE_A, "t-1")
    assert snapshot is not None
    assert snapshot.event_count == 2, "the losing batch must not have been journalled"
    assert snapshot.state.revision == created.revision + 1


async def test_concurrent_append_sequences_have_no_gaps(tm_store: InMemoryTaskMemoryStore) -> None:
    """Heavy concurrency on one task still yields a contiguous journal."""
    await _create(tm_store, SCOPE_A, "t-1")

    async def append(n: int) -> None:
        # expected_revision=None: these are unconditional appends, so all
        # of them should land — the point is sequence integrity, not
        # optimistic concurrency.
        await tm_store.append_events(SCOPE_A, "t-1", [_pause("t-1", f"t-1-p{n}", reason=str(n))])

    await asyncio.gather(*(append(n) for n in range(25)))

    page = await tm_store.list_events(SCOPE_A, "t-1", limit=200)
    sequences = [e.seq for e in page.events]
    assert sequences == list(range(1, 27)), f"sequences must be contiguous and complete: {sequences}"
    assert len(set(e.event_id for e in page.events)) == 26, "no event may be journalled twice"


async def test_concurrent_append_different_tasks_progress_independently(
    tm_store: InMemoryTaskMemoryStore,
) -> None:
    """The lock is per task: unrelated tasks never block or corrupt each other."""
    task_ids = [f"t-{n}" for n in range(8)]
    await asyncio.gather(*(_create(tm_store, SCOPE_A, tid) for tid in task_ids))

    async def churn(tid: str) -> None:
        for n in range(5):
            await tm_store.append_events(SCOPE_A, tid, [_pause(tid, f"{tid}-p{n}", reason=str(n))])

    await asyncio.gather(*(churn(tid) for tid in task_ids))

    for tid in task_ids:
        snapshot = await tm_store.load_snapshot(SCOPE_A, tid)
        assert snapshot is not None
        assert snapshot.event_count == 6, f"{tid} lost or gained events under concurrency"
        page = await tm_store.list_events(SCOPE_A, tid, limit=200)
        assert [e.seq for e in page.events] == list(range(1, 7))
        assert all(e.task_id == tid for e in page.events), "an event leaked between tasks"


async def test_concurrent_append_creation_races_are_serialized(tm_store: InMemoryTaskMemoryStore) -> None:
    """Concurrent creation of the same id yields one task, not two."""
    results = await asyncio.gather(
        *(_create(tm_store, SCOPE_A, "t-dup") for _ in range(5)),
        return_exceptions=True,
    )
    succeeded = [r for r in results if not isinstance(r, BaseException)]
    assert len(succeeded) == 5, f"identical creation is idempotent, not an error: {results}"

    snapshot = await tm_store.load_snapshot(SCOPE_A, "t-dup")
    assert snapshot is not None
    assert snapshot.event_count == 1, "an idempotent re-creation must not duplicate the journal"


async def test_concurrent_append_a_rejected_batch_mutates_nothing(
    tm_store: InMemoryTaskMemoryStore,
) -> None:
    """A batch whose LAST event is malformed leaves the whole batch unapplied.

    This is the property that distinguishes stage-then-publish from
    apply-as-you-go: a partially reduced batch must never reach the
    journal.
    """
    created = await _create(tm_store, SCOPE_A, "t-1")
    before = await tm_store.load_snapshot(SCOPE_A, "t-1")
    assert before is not None

    good = _pause("t-1", "t-1-good")
    # A second task_started on a live task is malformed — the reducer
    # refuses it, and it sits AFTER a perfectly valid event.
    malformed = _event("t-1", event_id="t-1-bad", goal="another goal", seconds=9)

    with pytest.raises(ReducerError):
        await tm_store.append_events(SCOPE_A, "t-1", [good, malformed], expected_revision=created.revision)

    after = await tm_store.load_snapshot(SCOPE_A, "t-1")
    assert after is not None
    assert after.event_count == before.event_count, "the valid prefix of a failed batch was journalled"
    assert after.state.revision == before.state.revision
    assert after.as_of_seq == before.as_of_seq


async def test_concurrent_append() -> None:
    """Required aggregate case: races resolve to one winner with no gaps."""
    store = InMemoryTaskMemoryStore()
    try:
        await test_concurrent_append_only_one_revision_wins(store)
    finally:
        await store.close()

    store = InMemoryTaskMemoryStore()
    try:
        await test_concurrent_append_sequences_have_no_gaps(store)
    finally:
        await store.close()

    store = InMemoryTaskMemoryStore()
    try:
        await test_concurrent_append_different_tasks_progress_independently(store)
    finally:
        await store.close()


# ─────────────────────────────────────────────────────────────
# test_idempotency
# ─────────────────────────────────────────────────────────────


async def test_idempotency_exact_retry_survives_a_stale_revision(
    tm_store: InMemoryTaskMemoryStore,
) -> None:
    """A retry of a committed batch is a no-op, even though its revision is stale.

    The caller's revision is stale *because its own first attempt
    succeeded*. Rejecting that as a conflict would punish a correct
    client for a lost acknowledgement.
    """
    created = await _create(tm_store, SCOPE_A, "t-1")
    event = _pause("t-1", "t-1-e2")

    first = await tm_store.append_events(SCOPE_A, "t-1", [event], expected_revision=created.revision)
    assert first.appended_event_ids == ("t-1-e2",)
    assert first.was_noop is False

    retry = await tm_store.append_events(SCOPE_A, "t-1", [event], expected_revision=created.revision)
    assert retry.was_noop is True
    assert retry.deduplicated_event_ids == ("t-1-e2",)
    assert retry.appended_event_ids == ()
    assert retry.last_seq == first.last_seq
    assert retry.revision == first.revision
    assert retry.state == first.state, "a retry returns the existing result, not a new one"

    snapshot = await tm_store.load_snapshot(SCOPE_A, "t-1")
    assert snapshot is not None and snapshot.event_count == 2


async def test_idempotency_same_id_different_payload_fails(tm_store: InMemoryTaskMemoryStore) -> None:
    """An event id may be redelivered, never rewritten."""
    created = await _create(tm_store, SCOPE_A, "t-1")
    original = _pause("t-1", "t-1-e2", reason="original")
    await tm_store.append_events(SCOPE_A, "t-1", [original], expected_revision=created.revision)

    forged = _pause("t-1", "t-1-e2", reason="tampered")
    with pytest.raises(ReducerError, match="never rewritten"):
        await tm_store.append_events(SCOPE_A, "t-1", [forged], expected_revision=None)

    snapshot = await tm_store.load_snapshot(SCOPE_A, "t-1")
    assert snapshot is not None
    assert snapshot.event_count == 2, "a rejected rewrite must not append anything"


async def test_idempotency_partial_redelivery_appends_only_the_new(
    tm_store: InMemoryTaskMemoryStore,
) -> None:
    """A batch mixing a redelivery with a fresh event appends only the fresh one."""
    created = await _create(tm_store, SCOPE_A, "t-1")
    first = _pause("t-1", "t-1-e2")
    result = await tm_store.append_events(SCOPE_A, "t-1", [first], expected_revision=created.revision)

    fresh = _resume("t-1", "t-1-e3")
    mixed = await tm_store.append_events(SCOPE_A, "t-1", [first, fresh], expected_revision=result.revision)

    assert mixed.deduplicated_event_ids == ("t-1-e2",)
    assert mixed.appended_event_ids == ("t-1-e3",)
    assert mixed.first_seq == 3, "a deduplicated event consumes no sequence number"

    page = await tm_store.list_events(SCOPE_A, "t-1", limit=200)
    assert [e.seq for e in page.events] == [1, 2, 3]


async def test_idempotency_duplicate_within_one_batch(tm_store: InMemoryTaskMemoryStore) -> None:
    """The same id twice in one batch dedupes; the same id with two payloads fails."""
    created = await _create(tm_store, SCOPE_A, "t-1")
    event = _pause("t-1", "t-1-e2")

    result = await tm_store.append_events(SCOPE_A, "t-1", [event, event], expected_revision=created.revision)
    assert result.appended_event_ids == ("t-1-e2",)
    assert result.deduplicated_event_ids == ("t-1-e2",)

    with pytest.raises(ReducerError, match="within one batch"):
        await tm_store.append_events(
            SCOPE_A,
            "t-1",
            [_resume("t-1", "dup"), _resume("t-1", "dup", seconds=99)],
            expected_revision=None,
        )


async def test_idempotency_creation_is_idempotent(tm_store: InMemoryTaskMemoryStore) -> None:
    """Recreating a task with the identical batch is a no-op, not an error."""
    first = await _create(tm_store, SCOPE_A, "t-1")
    again = await _create(tm_store, SCOPE_A, "t-1")

    assert again.was_noop is True
    assert again.state.revision == first.state.revision
    snapshot = await tm_store.load_snapshot(SCOPE_A, "t-1")
    assert snapshot is not None and snapshot.event_count == 1


async def test_idempotency_goal_is_stamped_onto_the_journal(tm_store: InMemoryTaskMemoryStore) -> None:
    """``create_task`` writes the goal into the event, so replay can rebuild it.

    The journal is the source of truth. A ``task_started`` that does not
    carry the goal cannot be replayed into a projection, so a
    reducer-version migration or a restart rebuild would fail.
    """
    await tm_store.create_task(SCOPE_A, goal="quarterly report", events=[_event("t-1", event_id="t-1-e1")])
    page = await tm_store.list_events(SCOPE_A, "t-1")
    assert page.events[0].payload.goal == "quarterly report"

    snapshot = await tm_store.load_snapshot(SCOPE_A, "t-1")
    assert snapshot is not None and snapshot.state.goal == "quarterly report"


async def test_idempotency_goal_disagreement_is_rejected(tm_store: InMemoryTaskMemoryStore) -> None:
    """An event carrying a different goal than the command is a caller bug."""
    with pytest.raises(ReducerError, match="must agree"):
        await tm_store.create_task(
            SCOPE_A, goal="one goal", events=[_event("t-1", event_id="t-1-e1", goal="another goal")]
        )
    assert await tm_store.load_snapshot(SCOPE_A, "t-1") is None


async def test_idempotency() -> None:
    """Required aggregate case: exact retries no-op, rewrites fail."""
    store = InMemoryTaskMemoryStore()
    try:
        await test_idempotency_exact_retry_survives_a_stale_revision(store)
    finally:
        await store.close()

    store = InMemoryTaskMemoryStore()
    try:
        await test_idempotency_same_id_different_payload_fails(store)
    finally:
        await store.close()

    store = InMemoryTaskMemoryStore()
    try:
        await test_idempotency_partial_redelivery_appends_only_the_new(store)
    finally:
        await store.close()


# ─────────────────────────────────────────────────────────────
# test_limits
# ─────────────────────────────────────────────────────────────


async def test_limits_foreign_scope_rejects_before_mutation(
    tm_store: InMemoryTaskMemoryStore,
) -> None:
    """A foreign scope cannot read, count, page or append."""
    await _create(tm_store, SCOPE_A, "t-1")
    before = await tm_store.load_snapshot(SCOPE_A, "t-1")
    assert before is not None

    assert await tm_store.load_snapshot(SCOPE_B, "t-1") is None, "a task id is not authorization"
    assert await tm_store.count_events(SCOPE_B, "t-1") == 0
    with pytest.raises(ScopeViolation):
        await tm_store.list_events(SCOPE_B, "t-1")
    with pytest.raises(ScopeViolation):
        await tm_store.append_events(SCOPE_B, "t-1", [_pause("t-1", "x")], expected_revision=None)
    assert (await tm_store.list_tasks(SCOPE_B)).items == ()

    after = await tm_store.load_snapshot(SCOPE_A, "t-1")
    assert after is not None
    assert after.event_count == before.event_count
    assert after.state.revision == before.state.revision


async def test_limits_open_task_ceiling(tm_config: TaskMemoryConfig) -> None:
    """A scope cannot exceed its open-task ceiling, and rejection is clean."""
    small = TaskMemoryConfig(max_open_tasks_per_scope=3)
    store = InMemoryTaskMemoryStore(small)
    try:
        for n in range(3):
            await _create(store, SCOPE_A, f"t-{n}")

        with pytest.raises(LimitExceeded) as excinfo:
            await _create(store, SCOPE_A, "t-overflow")
        assert excinfo.value.field == "open tasks per scope"
        assert excinfo.value.limit == 3
        assert await store.load_snapshot(SCOPE_A, "t-overflow") is None, "a refused task must not exist"

        # A different scope has its own budget.
        await _create(store, SCOPE_B, "t-other")

        # Terminating a task frees a slot: the ceiling is on OPEN tasks.
        state = await store.load_snapshot(SCOPE_A, "t-0")
        assert state is not None
        await store.append_events(
            SCOPE_A,
            "t-0",
            [
                _event(
                    "t-0",
                    event_id="t-0-cancel",
                    event_type=EventType.TASK_CANCELLED,
                    status=TaskStatus.CANCELLED,
                    seconds=5,
                )
            ],
            expected_revision=state.state.revision,
        )
        await _create(store, SCOPE_A, "t-after-cancel")
    finally:
        await store.close()


async def test_limits_journal_ceiling_reserves_headroom() -> None:
    """Foreground work is refused while reserved recovery events still fit."""
    tiny = TaskMemoryConfig(journal_soft_limit=3, journal_hard_limit=4, journal_reserved_events=2)
    store = InMemoryTaskMemoryStore(tiny)
    try:
        result = await _create(store, SCOPE_A, "t-1")  # 1 event
        for n in range(3):  # -> 4 events, at the hard limit
            result = await store.append_events(SCOPE_A, "t-1", [_pause("t-1", f"t-1-p{n}", reason=str(n))])

        before = await store.load_snapshot(SCOPE_A, "t-1")
        assert before is not None and before.event_count == 4

        # Ordinary work is now refused.
        with pytest.raises(LimitExceeded) as excinfo:
            await store.append_events(SCOPE_A, "t-1", [_pause("t-1", "t-1-overflow")])
        assert excinfo.value.field == "journal events"

        unchanged = await store.load_snapshot(SCOPE_A, "t-1")
        assert unchanged is not None and unchanged.event_count == 4, "a refused append mutated the journal"

        # ...but a reserved event still lands, which is the whole point of
        # the headroom: a task must always be able to record its own end.
        reserved = await store.append_events(
            SCOPE_A,
            "t-1",
            [
                _event(
                    "t-1",
                    event_id="t-1-cancel",
                    event_type=EventType.TASK_CANCELLED,
                    status=TaskStatus.CANCELLED,
                    seconds=8,
                )
            ],
        )
        assert reserved.appended_event_ids == ("t-1-cancel",)
        assert EventType.TASK_CANCELLED.is_reserved is True

        final = await store.load_snapshot(SCOPE_A, "t-1")
        assert final is not None and final.event_count == 5
    finally:
        await store.close()


async def test_limits_mixed_batch_counts_as_foreground() -> None:
    """A batch carrying any ordinary work does not get the reserved headroom."""
    tiny = TaskMemoryConfig(journal_soft_limit=2, journal_hard_limit=2, journal_reserved_events=5)
    store = InMemoryTaskMemoryStore(tiny)
    try:
        await _create(store, SCOPE_A, "t-1")
        await store.append_events(SCOPE_A, "t-1", [_pause("t-1", "t-1-p0")])

        from datetime import timedelta

        from parrot.tools.working_memory.task_memory.models import DegradedPayload

        mixed = [
            _resume("t-1", "t-1-ordinary"),
            JournalEvent(
                event_id="t-1-degraded",
                task_id="t-1",
                event_type=EventType.TRACKING_DEGRADED,
                occurred_at=TM_EPOCH + timedelta(seconds=7),
                payload=DegradedPayload(component="journal", detail="append timed out"),
            ),
        ]
        # The degraded event alone would fit in reserved headroom; paired
        # with ordinary work it must not.
        with pytest.raises(LimitExceeded):
            await store.append_events(SCOPE_A, "t-1", mixed)
    finally:
        await store.close()


async def test_limits_page_sizes_are_bounded(tm_store: InMemoryTaskMemoryStore) -> None:
    """Event and task pages clamp to the hard ceiling and reject bad limits."""
    from parrot.tools.working_memory.task_memory.models import CursorError
    from parrot.tools.working_memory.task_memory.store import MAX_PAGE_LIMIT

    await _create(tm_store, SCOPE_A, "t-1")
    for n in range(5):
        await tm_store.append_events(SCOPE_A, "t-1", [_pause("t-1", f"t-1-p{n}", reason=str(n))])

    page = await tm_store.list_events(SCOPE_A, "t-1", limit=2)
    assert len(page.events) == 2 and page.has_more is True and page.next_seq == 2

    rest = await tm_store.list_events(SCOPE_A, "t-1", after_seq=page.next_seq, limit=MAX_PAGE_LIMIT)
    assert [e.seq for e in rest.events] == [3, 4, 5, 6] and rest.has_more is False

    fenced = await tm_store.list_events(SCOPE_A, "t-1", as_of_seq=3, limit=MAX_PAGE_LIMIT)
    assert [e.seq for e in fenced.events] == [1, 2, 3], "as_of_seq must fence the read"

    with pytest.raises(CursorError):
        await tm_store.list_events(SCOPE_A, "t-1", limit=0)

    huge = await tm_store.list_events(SCOPE_A, "t-1", limit=10_000)
    assert len(huge.events) <= MAX_PAGE_LIMIT


async def test_limits() -> None:
    """Required aggregate case: scope, capacity and reserved headroom."""
    store = InMemoryTaskMemoryStore()
    try:
        await test_limits_foreign_scope_rejects_before_mutation(store)
    finally:
        await store.close()

    await test_limits_open_task_ceiling(TaskMemoryConfig())
    await test_limits_journal_ceiling_reserves_headroom()
    await test_limits_mixed_batch_counts_as_foreground()


# ─────────────────────────────────────────────────────────────
# Projection migration, listing and transactions
# ─────────────────────────────────────────────────────────────


async def test_stale_projection_is_replayed_from_the_journal(
    tm_store: InMemoryTaskMemoryStore,
) -> None:
    """An older reducer's projection is rebuilt from the journal, not trusted.

    White-box on purpose: the only way to simulate a projection written
    by an earlier build is to write one. The journal is left untouched,
    which is the point — it is the source of truth and is always
    sufficient to rebuild from.
    """
    await _create(tm_store, SCOPE_A, "t-1", goal="rebuildable")
    await tm_store.append_events(SCOPE_A, "t-1", [_pause("t-1", "t-1-e2")])

    record = tm_store._tasks["t-1"]
    good = record.state
    # Simulate an older build: a stale version AND a corrupted projection,
    # so a store that merely bumped the version number would still fail.
    record.state = good.model_copy(update={"reducer_version": REDUCER_VERSION - 1, "goal": "corrupted"})

    snapshot = await tm_store.load_snapshot(SCOPE_A, "t-1")
    assert snapshot is not None
    assert snapshot.state.reducer_version == REDUCER_VERSION
    assert snapshot.state.goal == "rebuildable", "the projection was not actually replayed"
    assert snapshot.state.status is TaskStatus.PAUSED
    assert snapshot.state.last_event_seq == 2


async def test_newer_projection_is_rejected_not_guessed(tm_store: InMemoryTaskMemoryStore) -> None:
    """A projection from a newer reducer is refused explicitly."""
    await _create(tm_store, SCOPE_A, "t-1")
    record = tm_store._tasks["t-1"]
    record.state = record.state.model_copy(update={"reducer_version": REDUCER_VERSION + 1})

    with pytest.raises(ReducerError, match="refusing to interpret a newer projection"):
        await tm_store.load_snapshot(SCOPE_A, "t-1")


async def test_list_tasks_filters_orders_and_pages(tm_store: InMemoryTaskMemoryStore) -> None:
    """Listings default to open tasks, order newest-first and page by keyset."""
    for n in range(4):
        await _create(tm_store, SCOPE_A, f"t-{n}")

    # Terminate one: it must drop out of the default listing.
    snap = await tm_store.load_snapshot(SCOPE_A, "t-0")
    assert snap is not None
    await tm_store.append_events(
        SCOPE_A,
        "t-0",
        [
            _event(
                "t-0",
                event_id="t-0-done",
                event_type=EventType.TASK_CANCELLED,
                status=TaskStatus.CANCELLED,
                seconds=6,
            )
        ],
        expected_revision=snap.state.revision,
    )

    default_page = await tm_store.list_tasks(SCOPE_A)
    listed = {i.task_id for i in default_page.items}
    assert "t-0" not in listed, "a terminal task is not open work"
    assert listed == {"t-1", "t-2", "t-3"}
    assert default_page.total_open == 3

    explicit = await tm_store.list_tasks(SCOPE_A, statuses=[TaskStatus.CANCELLED])
    assert {i.task_id for i in explicit.items} == {"t-0"}

    # Keyset pagination covers every row exactly once.
    seen: List[str] = []
    cursor: Optional[str] = None
    while True:
        page = await tm_store.list_tasks(SCOPE_A, limit=1, cursor=cursor)
        seen.extend(i.task_id for i in page.items)
        cursor = page.next_cursor
        if cursor is None:
            break
    assert sorted(seen) == ["t-1", "t-2", "t-3"]
    assert len(seen) == len(set(seen)), "keyset pagination repeated a row"


async def test_transaction_handle_has_a_real_lifecycle(tm_store: InMemoryTaskMemoryStore) -> None:
    """The no-op transaction is honest about its own state."""
    async with tm_store.transaction() as tx:
        assert isinstance(tx, NoOpTransaction)
        assert tx.is_active is True
    assert tx.is_active is False

    with pytest.raises(RuntimeError, match="boom"):
        async with tm_store.transaction() as failing:
            assert failing.is_active is True
            raise RuntimeError("boom")
    assert failing.is_active is False, "an aborted transaction must be rolled back"


async def test_store_is_not_advertised_as_durable() -> None:
    """The module says plainly that it is not durable (D2)."""
    import parrot.tools.working_memory.task_memory.store.memory as module

    doc = (module.__doc__ or "").lower()
    assert "not durable" in doc
    assert "delivery b" in doc


async def test_side_effect_counter_detects_a_second_run(tm_side_effects) -> None:
    """The shared side-effect counter distinguishes one run from two.

    A mock's ``call_count`` cannot tell "ran once, result lost" from "ran
    twice"; this fixture records each invocation so later integration
    tests can assert an uncertain external effect was never retried.
    """
    await tm_side_effects.run(order="a")
    tm_side_effects.assert_ran_once()

    await tm_side_effects.run(order="b")
    assert tm_side_effects.count == 2
    assert [c["order"] for c in tm_side_effects.calls] == ["a", "b"]
    with pytest.raises(AssertionError, match="ran 2 times"):
        tm_side_effects.assert_ran_once()
