"""Process-local task-memory store (FEAT-538, Delivery A).

.. warning::

   **This backend is not durable** (D2). It holds journals and
   projections in Python dictionaries: nothing survives a process
   restart, a crash, or a second pod. It exists for tests and for
   single-process compatibility deployments. Durable multi-pod
   continuity is Delivery B's PostgreSQL store, and only that store may
   be described as recoverable.

What this module *is* responsible for is being **behaviourally
identical** to the durable backend (AC2). It achieves that by owning as
little judgement as possible:

- Scope checks, opaque cursors, redelivery classification and page
  bounding come from :mod:`.._base`.
- The projection comes from :func:`..reducer.reduce`. This store never
  computes task state itself; if it did, the two backends could disagree
  about what a journal means.

The one thing it genuinely owns is **atomicity**, and the shape of that
is worth stating plainly:

1. Take the task's own lock. Appends to the *same* task serialize;
   different tasks proceed concurrently, because the lock is per task and
   not global.
2. Classify the batch against committed events — *before* any sequence is
   allocated and *before* the revision is checked, so an exact redelivery
   is a no-op rather than a conflict.
3. Check ``expected_revision``.
4. Check capacity.
5. Reduce every event into a **local** variable, allocating contiguous
   sequences as it goes.
6. Only once the whole batch has reduced successfully, publish it to the
   record.

Steps 2–5 mutate nothing. That is what makes "a rejected command changes
nothing" true by construction rather than by careful cleanup: there is
no partially-applied intermediate to roll back.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import AsyncIterator, Dict, List, Optional, Sequence, Tuple

from parrot.interfaces.task_memory import (
    GOAL_PREVIEW_CHARS,
    AppendResult,
    EventPage,
    TaskPage,
    TaskSnapshot,
    TaskSummary,
    Transaction,
)

from ..config import TaskMemoryConfig
from ..models import (
    EventType,
    JournalEvent,
    LimitExceeded,
    ReducerError,
    RevisionConflict,
    ScopeViolation,
    TaskLifecyclePayload,
    TaskScope,
    TaskState,
    TaskStatus,
)
from ..reducer import REDUCER_VERSION, reduce, replay
from ._base import BaseTaskMemoryStore, goal_preview

__all__ = ("InMemoryTaskMemoryStore", "NoOpTransaction")

logger = logging.getLogger(__name__)


class NoOpTransaction:
    """A :class:`~parrot.interfaces.task_memory.Transaction` for a store with no database.

    The contract is about *atomicity*, not about SQL. This backend gets
    its atomicity from the per-task lock plus the stage-then-publish
    discipline in :meth:`InMemoryTaskMemoryStore.append_events`, so a
    transaction handle here is a real object with a real lifecycle but no
    work to do.

    It is not a lie: ``rollback()`` genuinely closes it, and an
    already-closed transaction reports ``is_active is False``.
    """

    def __init__(self) -> None:
        """Open the transaction."""
        self._active = True

    @property
    def is_active(self) -> bool:
        """Whether this transaction is still open."""
        return self._active

    async def rollback(self) -> None:
        """Close the transaction without committing anything."""
        self._active = False

    async def commit(self) -> None:
        """Close the transaction, accepting whatever was already published."""
        self._active = False


class _TaskRecord:
    """One task's journal, projection and lock.

    Attributes:
        scope: The trusted scope that owns this task.
        state: The current reducer projection.
        events: The journal, in ascending sequence order.
        by_id: The same events indexed by ``event_id``, for deduplication.
        lock: Serializes appends to *this* task only.
    """

    __slots__ = ("scope", "state", "events", "by_id", "lock")

    def __init__(self, scope: TaskScope, state: TaskState, events: Sequence[JournalEvent]) -> None:
        """Initialize a record.

        Args:
            scope: Owning scope.
            state: Initial projection.
            events: Initial journal.
        """
        self.scope = scope
        self.state = state
        self.events: List[JournalEvent] = list(events)
        self.by_id: Dict[str, JournalEvent] = {e.event_id: e for e in self.events}
        self.lock = asyncio.Lock()


class InMemoryTaskMemoryStore(BaseTaskMemoryStore):
    """Process-local implementation of the task-memory store contract.

    Not durable — see the module docstring.

    Args:
        config: Capacity and retention configuration. Defaults to
            :class:`~..config.TaskMemoryConfig`'s own defaults.
    """

    def __init__(self, config: Optional[TaskMemoryConfig] = None) -> None:
        """Initialize an empty store.

        Args:
            config: Capacity configuration.
        """
        self._config = config or TaskMemoryConfig()
        self._tasks: Dict[str, _TaskRecord] = {}
        #: Guards the task registry itself (creation and lookup). Held
        #: only for dictionary operations, never across a reduction, so
        #: it cannot become the global lock this design is avoiding.
        self._registry_lock = asyncio.Lock()
        self.logger = logger

    # ── internals ────────────────────────────────────────────────────

    def _resolve(self, scope: TaskScope, task_id: str) -> Optional[_TaskRecord]:
        """Return a record if it exists **in this scope**.

        A task owned by another scope is reported as absent rather than
        as forbidden: telling a caller that some id exists but is not
        theirs is an existence oracle.

        Args:
            scope: The caller's trusted scope.
            task_id: The task to find.

        Returns:
            The record, or ``None``.
        """
        record = self._tasks.get(task_id)
        if record is None or not scope.matches(record.scope):
            return None
        return record

    def _require(self, scope: TaskScope, task_id: str) -> _TaskRecord:
        """Return a record for writing, or raise.

        Args:
            scope: The caller's trusted scope.
            task_id: The task to find.

        Returns:
            The record.

        Raises:
            ScopeViolation: If the task does not exist in this scope.
                Absence and foreign ownership give the same answer for
                the same reason as :meth:`_resolve`.
        """
        record = self._resolve(scope, task_id)
        if record is None:
            raise ScopeViolation(f"task {task_id!r} does not exist in this scope")
        return record

    def _migrated_state(self, record: _TaskRecord) -> TaskState:
        """Return the record's projection under **this** build's reducer.

        A projection written by an older reducer is rebuilt by replaying
        the journal, which is the source of truth and therefore always
        sufficient. A projection written by a *newer* reducer is rejected
        explicitly — this build cannot know what its fields meant, and
        best-effort interpretation of an unknown schema is how a
        projection silently starts disagreeing with its journal.

        Callers must already hold the task lock.

        Args:
            record: The task record.

        Returns:
            The projection, migrated in place when it was stale.

        Raises:
            ReducerError: If the stored projection came from a newer
                reducer than this build implements.
        """
        version = record.state.reducer_version
        if version == REDUCER_VERSION:
            return record.state
        if version > REDUCER_VERSION:
            raise ReducerError(
                f"task {record.state.task_id} carries reducer version {version}, "
                f"but this build implements {REDUCER_VERSION}; refusing to interpret a newer projection"
            )

        self.logger.info(
            "[TaskMemory] replaying task %s from reducer version %s to %s",
            record.state.task_id,
            version,
            REDUCER_VERSION,
        )
        rebuilt = replay(record.events, scope=record.scope)
        if rebuilt is None:  # pragma: no cover - a record always has its task_started
            raise ReducerError(f"task {record.state.task_id} has an empty journal and cannot be replayed")
        record.state = rebuilt
        return rebuilt

    def _check_capacity(self, record: _TaskRecord, fresh: Sequence[JournalEvent]) -> None:
        """Refuse a batch that would exhaust the journal.

        Foreground work is refused while reserved headroom remains, so a
        task can always still record its own termination, a recovery
        outcome or a retention intent. A batch counts as reserved only
        when *every* event in it is a reserved type — a batch carrying
        any ordinary work is ordinary work.

        Args:
            record: The task record.
            fresh: The genuinely new events about to be appended.

        Raises:
            LimitExceeded: If appending the batch would pass the ceiling.
                Raised before anything is mutated.
        """
        if not fresh:
            return
        reserved = all(event.event_type.is_reserved for event in fresh)
        final_index = len(record.events) + len(fresh) - 1
        if self._config.is_journal_exhausted(final_index, reserved=reserved):
            ceiling = self._config.journal_hard_limit + (self._config.journal_reserved_events if reserved else 0)
            raise LimitExceeded(
                "journal events",
                ceiling,
                len(record.events) + len(fresh),
                "reserved headroom is kept for terminal, recovery and retention events",
            )

    def _apply(
        self,
        record: _TaskRecord,
        events: Sequence[JournalEvent],
        expected_revision: Optional[int],
    ) -> AppendResult:
        """Run the atomic append against a locked record.

        The ordering here is the contract, not an implementation detail:
        classify, then check the revision, then check capacity, then
        reduce into a local variable, and only then publish.

        Args:
            record: The locked task record.
            events: The batch, in order.
            expected_revision: Revision the caller believes is current,
                or ``None`` to skip the check.

        Returns:
            The append result.

        Raises:
            RevisionConflict: If the revision is stale and the batch is
                not a pure redelivery.
            ReducerError: If an event is malformed or an id is reused
                with a different payload.
            LimitExceeded: If capacity is exhausted.
        """
        state = self._migrated_state(record)

        # 1. Redelivery first. A caller retrying a batch that in fact
        #    committed has a legitimately stale revision *because of its
        #    own success*, so classification must precede the revision
        #    check or a correct retry would be rejected as a conflict.
        classification = self._classify(events, record.by_id)

        if classification.is_noop:
            return AppendResult(
                state=state,
                appended_event_ids=(),
                deduplicated_event_ids=classification.duplicates,
                first_seq=None,
                last_seq=state.last_event_seq,
            )

        # 2. Optimistic concurrency. `None` is reserved for
        #    runtime-authored events (recovery, retention) that cannot
        #    meaningfully conflict with an agent's optimistic view.
        if expected_revision is not None and expected_revision != state.revision:
            raise RevisionConflict(state.task_id, expected_revision, state.revision)

        # 3. Capacity, still before any mutation.
        self._check_capacity(record, classification.fresh)

        # 4. Reduce into a LOCAL variable. If any event in the batch is
        #    malformed, the exception leaves the record untouched — there
        #    is no half-applied batch to undo.
        sequences = list(self._sequence_range(state.last_event_seq, len(classification.fresh)))
        staged: List[JournalEvent] = []
        working = state
        for seq, event in zip(sequences, classification.fresh):
            sequenced = event.model_copy(update={"seq": seq})
            working = reduce(working, sequenced, scope=record.scope)
            staged.append(sequenced)

        # 5. Publish. Everything above succeeded, so this cannot fail
        #    part-way.
        record.events.extend(staged)
        for event in staged:
            record.by_id[event.event_id] = event
        record.state = working

        return AppendResult(
            state=working,
            appended_event_ids=tuple(e.event_id for e in staged),
            deduplicated_event_ids=classification.duplicates,
            first_seq=sequences[0],
            last_seq=sequences[-1],
        )

    @staticmethod
    def _normalize_creation(events: Sequence[JournalEvent], goal: str) -> Tuple[JournalEvent, ...]:
        """Stamp the task's goal onto its ``task_started`` event.

        ``create_task`` receives the goal as an argument, but the journal
        is the source of truth: a ``task_started`` event that does not
        carry the goal cannot be replayed into a projection, so a
        rebuild after a restart (or a reducer-version migration) would
        fail. Normalizing here keeps the journal self-sufficient.

        Normalization is deterministic and total, so a redelivered
        creation batch normalizes to exactly the same bytes and still
        deduplicates.

        Args:
            events: The creation batch, in order.
            goal: The goal supplied to ``create_task``.

        Returns:
            The batch with the goal stamped on its first event.

        Raises:
            ReducerError: If the batch is empty, its first event is not a
                ``task_started``, events disagree about the task id, or
                the event already carries a *different* goal.
        """
        if not events:
            raise ReducerError("create_task requires at least a task_started event")

        first = events[0]
        if first.event_type is not EventType.TASK_STARTED:
            raise ReducerError(f"a task's first event must be task_started, got {first.event_type.value!r}")

        task_id = first.task_id
        for event in events:
            if event.task_id != task_id:
                raise ReducerError(f"creation batch mixes tasks: {event.task_id!r} alongside {task_id!r}")

        payload = first.payload
        if not isinstance(payload, TaskLifecyclePayload):  # pragma: no cover - JournalEvent enforces this
            raise ReducerError("task_started requires a task_lifecycle payload")

        if payload.goal is None:
            first = first.model_copy(update={"payload": payload.model_copy(update={"goal": goal})})
        elif payload.goal != goal:
            raise ReducerError(
                f"task_started carries goal {payload.goal!r} but create_task was given {goal!r}; "
                "the journal and the command must agree"
            )

        return (first, *events[1:])

    def _open_task_count(self, scope: TaskScope) -> int:
        """Count non-terminal tasks in a scope.

        Args:
            scope: The scope to measure.

        Returns:
            The number of open tasks.
        """
        return sum(
            1 for record in self._tasks.values() if scope.matches(record.scope) and not record.state.status.is_terminal
        )

    # ── contract ─────────────────────────────────────────────────────

    async def create_task(
        self,
        scope: TaskScope,
        *,
        goal: str,
        events: Sequence[JournalEvent],
        transaction: Optional[Transaction] = None,
    ) -> AppendResult:
        """Create a task and append its first batch of events atomically.

        There is no window in which a task exists with an empty journal:
        the record is only published once its whole creation batch has
        reduced successfully.

        Creation is idempotent. Redelivering an identical creation batch
        for an existing task returns a no-op result rather than raising,
        for the same reason redelivering an append does.

        Args:
            scope: Trusted runtime scope the task belongs to.
            goal: The task's goal. Stamped onto the ``task_started``
                event when that event does not already carry it.
            events: Initial events, beginning with ``task_started``.
            transaction: Accepted for contract parity. This backend has
                no database to enlist in; its atomicity comes from the
                per-task lock and stage-then-publish.

        Returns:
            The append result, including the reduced projection.

        Raises:
            LimitExceeded: If the scope already holds the maximum number
                of open tasks.
            ScopeViolation: If the task id already exists in a different
                scope.
            ReducerError: If the batch is malformed.
            PlanValidationError: If the initial plan is invalid.
        """
        normalized = self._normalize_creation(events, goal)
        task_id = normalized[0].task_id

        async with self._registry_lock:
            existing = self._tasks.get(task_id)
            if existing is not None:
                if not scope.matches(existing.scope):
                    raise ScopeViolation(f"task {task_id!r} does not exist in this scope")
                record = existing
            else:
                limit = self._config.max_open_tasks_per_scope
                open_tasks = self._open_task_count(scope)
                if open_tasks >= limit:
                    raise LimitExceeded("open tasks per scope", limit, open_tasks + 1)

                # Reduce the creation batch BEFORE the record exists, so a
                # malformed batch leaves no empty task behind.
                working: Optional[TaskState] = None
                staged: List[JournalEvent] = []
                for index, event in enumerate(normalized, start=1):
                    sequenced = event.model_copy(update={"seq": index})
                    working = reduce(working, sequenced, scope=scope)
                    staged.append(sequenced)
                assert working is not None  # normalized is non-empty

                record = _TaskRecord(scope, working, staged)
                self._tasks[task_id] = record
                return AppendResult(
                    state=working,
                    appended_event_ids=tuple(e.event_id for e in staged),
                    deduplicated_event_ids=(),
                    first_seq=1,
                    last_seq=len(staged),
                )

        # The task already existed: fall through to the ordinary append
        # path, which recognises an identical redelivery as a no-op.
        async with record.lock:
            return self._apply(record, normalized, expected_revision=None)

    async def append_events(
        self,
        scope: TaskScope,
        task_id: str,
        events: Sequence[JournalEvent],
        *,
        expected_revision: Optional[int] = None,
        transaction: Optional[Transaction] = None,
    ) -> AppendResult:
        """Append a batch of events under an optimistic revision check.

        Args:
            scope: Trusted runtime scope.
            task_id: The task to append to.
            events: The batch, in order.
            expected_revision: Revision the caller believes is current.
                ``None`` skips the check.
            transaction: Accepted for contract parity; unused here.

        Returns:
            The append result.

        Raises:
            ScopeViolation: If the task does not exist in this scope.
            RevisionConflict: If the revision is stale and the batch is
                not a pure redelivery. Nothing is mutated.
            ReducerError: If an id is reused with a different payload, or
                an event is malformed.
            LimitExceeded: If the journal's capacity is exhausted.
        """
        async with self._registry_lock:
            record = self._require(scope, task_id)

        async with record.lock:
            # Re-check under the task lock: the registry lock was
            # released, so nothing above is load-bearing for correctness.
            self._ensure_scope(scope, record.scope, subject="task")
            return self._apply(record, events, expected_revision)

    async def load_snapshot(self, scope: TaskScope, task_id: str) -> Optional[TaskSnapshot]:
        """Load one task's projection consistently.

        Args:
            scope: Trusted runtime scope.
            task_id: The task to load.

        Returns:
            The snapshot, or ``None`` when no such task exists in this
            scope.
        """
        async with self._registry_lock:
            record = self._resolve(scope, task_id)
        if record is None:
            return None

        async with record.lock:
            state = self._migrated_state(record)
            return TaskSnapshot(
                state=state,
                as_of_seq=state.last_event_seq,
                event_count=len(record.events),
            )

    async def list_tasks(
        self,
        scope: TaskScope,
        *,
        statuses: Optional[Sequence[TaskStatus]] = None,
        limit: int = 20,
        cursor: Optional[str] = None,
    ) -> TaskPage:
        """List tasks in a scope, newest activity first.

        Ordering is ``(updated_at desc, task_id asc)``. The task id
        tiebreak is what makes the order a *total* one, so keyset
        pagination cannot skip or repeat a row when two tasks share a
        timestamp.

        Args:
            scope: Trusted runtime scope.
            statuses: Restrict to these statuses; ``None`` means open
                (non-terminal) tasks only.
            limit: Bounded page size.
            cursor: Opaque cursor from a previous page.

        Returns:
            A bounded page of summaries.

        Raises:
            CursorError: If the cursor is malformed, out of bounds, or
                was issued for a different scope or query.
        """
        size = self._bounded(limit, default=self.default_task_page)
        wanted = tuple(status.value for status in statuses) if statuses is not None else None
        query = {"statuses": wanted}

        async with self._registry_lock:
            mine = [record for record in self._tasks.values() if scope.matches(record.scope)]

        if statuses is None:
            selected = [r for r in mine if not r.state.status.is_terminal]
        else:
            allowed = set(statuses)
            selected = [r for r in mine if r.state.status in allowed]

        # Descending by (updated_at, task_id): newest activity first, with
        # the id as a tiebreak so the order is TOTAL. Without that
        # tiebreak two tasks sharing a timestamp could swap places between
        # pages, and keyset pagination would skip or repeat one.
        rows = sorted(selected, key=lambda r: (r.state.updated_at, r.state.task_id), reverse=True)

        start = 0
        if cursor is not None:
            position = self._decode_cursor(cursor, scope, query)
            after = (datetime.fromisoformat(str(position["ts"])), str(position["id"]))
            start = len(rows)
            for index, record in enumerate(rows):
                if (record.state.updated_at, record.state.task_id) < after:
                    start = index
                    break

        window = rows[start : start + size]
        next_cursor: Optional[str] = None
        if window and start + size < len(rows):
            last = window[-1].state
            next_cursor = self._encode_cursor(scope, query, {"ts": last.updated_at.isoformat(), "id": last.task_id})

        total_open = sum(1 for record in mine if not record.state.status.is_terminal)
        return TaskPage(
            items=tuple(
                TaskSummary(
                    task_id=record.state.task_id,
                    goal_preview=goal_preview(record.state.goal, chars=GOAL_PREVIEW_CHARS),
                    status=record.state.status,
                    updated_at=record.state.updated_at,
                )
                for record in window
            ),
            next_cursor=next_cursor,
            total_open=total_open,
        )

    async def list_events(
        self,
        scope: TaskScope,
        task_id: str,
        *,
        after_seq: int = 0,
        limit: int = 50,
        as_of_seq: Optional[int] = None,
    ) -> EventPage:
        """Page a task's journal in ascending sequence order.

        Reads never append.

        Args:
            scope: Trusted runtime scope.
            task_id: The task to read.
            after_seq: Return events strictly after this sequence.
            limit: Bounded page size.
            as_of_seq: Fence the read at this sequence.

        Returns:
            A bounded page of events.

        Raises:
            ScopeViolation: If the task does not exist in this scope.
        """
        size = self._bounded(limit, default=self.default_event_page)
        async with self._registry_lock:
            record = self._require(scope, task_id)

        async with record.lock:
            selected = [
                event
                for event in record.events
                if event.seq > after_seq and (as_of_seq is None or event.seq <= as_of_seq)
            ]

        window = selected[:size]
        return EventPage(
            events=tuple(window),
            next_seq=window[-1].seq if window else after_seq,
            has_more=len(selected) > size,
        )

    async def count_events(self, scope: TaskScope, task_id: str) -> int:
        """Return how many events a task's journal holds.

        Args:
            scope: Trusted runtime scope.
            task_id: The task to measure.

        Returns:
            The event count, or ``0`` when the task does not exist in
            this scope.
        """
        async with self._registry_lock:
            record = self._resolve(scope, task_id)
        return 0 if record is None else len(record.events)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Transaction]:
        """Open a transaction this store and an artifact store can share.

        Yields:
            A :class:`NoOpTransaction`. This backend's atomicity comes
            from its per-task lock, not from a database.
        """
        tx = NoOpTransaction()
        try:
            yield tx
        except BaseException:
            await tx.rollback()
            raise
        else:
            await tx.commit()

    async def close(self) -> None:
        """Drop every journal and projection held in memory."""
        async with self._registry_lock:
            self._tasks.clear()
