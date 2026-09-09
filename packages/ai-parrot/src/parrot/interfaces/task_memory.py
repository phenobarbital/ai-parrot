"""Task-memory store contract (FEAT-538).

The journal is the source of truth and ``TaskState`` is a pure reducer
projection of it (D6). This module defines the **contract** every backend
must honour — the in-memory one used for tests and single-process
compatibility, and the PostgreSQL one that provides durable multi-pod
continuity in Delivery B. Both must pass the same conformance suite:
identical reducer, idempotence, revision, plan-validation and
scope-isolation semantics (AC2).

Nothing here is an implementation. This is a **leaf contract module**: it
imports stdlib, ``pydantic`` and the task-memory domain models only. It
must not import ``pandas``, ``asyncpg``, ``redis``, a REPL worker, or any
concrete backend — a contract that drags in a database driver is not a
contract, it is a dependency.

Invariants the contract encodes, each of which the conformance suite
checks rather than trusting:

- **Every operation carries a trusted scope.** A task id is not
  authorization: a globally unique id supplied by a caller in a different
  scope must not resolve. Scope comes from the runtime, never from a tool
  argument.
- **A rejected command mutates nothing.** An expected-revision mismatch
  raises :class:`RevisionConflict` and leaves the task exactly as it was.
- **Idempotent redelivery is a no-op.** The store deduplicates on
  ``event_id`` *before* allocating a sequence number. The same id with a
  different payload is rejected rather than silently overwriting.
- **Sequences are contiguous per task.** Deduplication leaves no gaps,
  because a deduplicated event never consumes a sequence number.
- **Pages are bounded, scoped and cursor-validated.** Cursors are opaque
  and bound to their scope; a cursor from another scope is rejected.
"""

from __future__ import annotations

from datetime import datetime
from typing import AsyncContextManager, Optional, Protocol, Sequence, Tuple, runtime_checkable

from parrot.tools.working_memory.task_memory.models import JournalEvent, Limits, TaskScope, TaskState, TaskStatus
from pydantic import BaseModel, ConfigDict, Field

__all__ = (
    "GOAL_PREVIEW_CHARS",
    "AppendResult",
    "TaskSnapshot",
    "TaskSummary",
    "TaskPage",
    "EventPage",
    "Transaction",
    "TransactionCoordinator",
    "TaskMemoryStore",
)

#: How much of a goal a task listing may show. Deliberately short: a
#: listing exists to let a caller pick a task, not to leak its content.
GOAL_PREVIEW_CHARS: int = 80


class _Result(BaseModel):
    """Shared configuration for contract return models."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class AppendResult(_Result):
    """Outcome of one accepted append (or creation).

    Returned only after the append/reduction transaction has committed.
    A rejected command raises instead of returning a result with a
    "failed" flag — there is no partially-applied outcome to describe.

    Attributes:
        state: The reduced projection after the batch was applied.
        appended_event_ids: Ids that consumed a new sequence number, in
            order.
        deduplicated_event_ids: Ids recognised as exact redeliveries.
            These consumed no sequence number, which is what keeps the
            sequence contiguous.
        first_seq: Sequence of the first newly appended event, or
            ``None`` when every event was a redelivery.
        last_seq: Highest sequence in the task after this call.
    """

    state: TaskState
    appended_event_ids: Tuple[str, ...] = ()
    deduplicated_event_ids: Tuple[str, ...] = ()
    first_seq: Optional[int] = Field(default=None, ge=1)
    last_seq: int = Field(ge=0)

    @property
    def revision(self) -> int:
        """The task's revision after this append."""
        return self.state.revision

    @property
    def task_id(self) -> str:
        """The task this append targeted."""
        return self.state.task_id

    @property
    def was_noop(self) -> bool:
        """Whether every event in the batch was an exact redelivery."""
        return not self.appended_event_ids


class TaskSnapshot(_Result):
    """A consistent read of one task's projection.

    ``as_of_seq`` is the fence for any follow-up page read: event and
    artifact pages taken at the same fence describe the same instant,
    which is what makes recall deterministic for captured inputs.

    Attributes:
        state: The reduced projection.
        as_of_seq: Journal sequence this snapshot reflects.
        event_count: Total events in the task's journal, for the
            retention/capacity checks.
    """

    state: TaskState
    as_of_seq: int = Field(ge=0)
    event_count: int = Field(default=0, ge=0)


class TaskSummary(_Result):
    """One row of a task listing.

    Deliberately minimal: this is what a caller sees when recall reports
    ``needs_task_selection``, so it carries enough to choose between open
    tasks and nothing more.

    Attributes:
        task_id: Runtime identity.
        goal_preview: First :data:`GOAL_PREVIEW_CHARS` characters of the
            goal.
        status: Task lifecycle state.
        updated_at: When the task last changed.
    """

    task_id: str = Field(max_length=Limits.MAX_IDENTIFIER)
    goal_preview: str = Field(max_length=GOAL_PREVIEW_CHARS)
    status: TaskStatus
    updated_at: datetime


class TaskPage(_Result):
    """A bounded page of task summaries.

    Attributes:
        items: The summaries, in stable order.
        next_cursor: Opaque scoped cursor for the following page, or
            ``None`` at the end. A cursor is never a raw offset and is
            never valid in another scope.
        total_open: Count of non-terminal tasks in the scope, used to
            enforce the open-task limit.
    """

    items: Tuple[TaskSummary, ...] = ()
    next_cursor: Optional[str] = Field(default=None, max_length=Limits.MAX_CURSOR)
    total_open: int = Field(default=0, ge=0)


class EventPage(_Result):
    """A bounded page of journal events.

    Attributes:
        events: The events, in ascending sequence order.
        next_seq: Sequence to pass as ``after_seq`` for the next page.
        has_more: Whether more events exist after this page.
    """

    events: Tuple[JournalEvent, ...] = ()
    next_seq: int = Field(default=0, ge=0)
    has_more: bool = False


@runtime_checkable
class Transaction(Protocol):
    """An in-flight unit of work shared by the task and artifact stores.

    Durable artifact publication commits the alias/version index, the
    evidence metadata and the ``artifact_registered`` event **on the same
    connection** (spec §2 Persistence). Two unrelated pool transactions
    are not sufficient, so both stores accept the same handle.

    In-memory backends may implement this as a no-op guard; the contract
    is about atomicity, not about SQL.
    """

    @property
    def is_active(self) -> bool:
        """Whether this transaction is still open."""
        ...

    async def rollback(self) -> None:
        """Abandon the unit of work, discarding every change made in it."""
        ...


@runtime_checkable
class TransactionCoordinator(Protocol):
    """Hands out transactions the task and artifact stores can share."""

    def begin(self) -> AsyncContextManager[Transaction]:
        """Open a transaction, committing on clean exit and rolling back on error.

        Returns:
            An async context manager yielding the :class:`Transaction`.
        """
        ...


@runtime_checkable
class TaskMemoryStore(Protocol):
    """Scoped, atomic persistence for task journals and their projections.

    Implementations must be safe under concurrent callers: appends to the
    *same* task serialize, while different tasks progress independently.

    Every method takes ``scope`` first and must check it. A task id alone
    never authorizes access — this is the mechanism behind AC11.
    """

    async def create_task(
        self,
        scope: TaskScope,
        *,
        goal: str,
        events: Sequence[JournalEvent],
        transaction: Optional[Transaction] = None,
    ) -> AppendResult:
        """Create a task and append its first batch of events atomically.

        The task and its ``task_started`` event are committed together:
        there is no window in which a task exists with an empty journal.

        Args:
            scope: Trusted runtime scope the task belongs to.
            goal: The task's goal.
            events: Initial events, beginning with ``task_started``.
            transaction: Optional shared transaction to enlist in.

        Returns:
            The append result, including the reduced projection.

        Raises:
            LimitExceeded: If the scope already holds the maximum number
                of open tasks.
            ReducerError: If an event is malformed or out of order.
            PlanValidationError: If the initial plan is invalid.
        """
        ...

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

        The implementation must, in one transaction: lock the task row,
        verify scope, deduplicate by ``event_id``, check
        ``expected_revision``, allocate only new contiguous sequences,
        reduce, insert, update the projection, and commit.

        **Exact redelivery is recognised before stale-revision
        rejection.** A retried batch that was already committed must
        return a no-op result rather than a :class:`RevisionConflict`,
        because the caller's revision is legitimately stale precisely
        *because* its own earlier attempt succeeded.

        Args:
            scope: Trusted runtime scope.
            task_id: The task to append to.
            events: The batch, in order.
            expected_revision: Revision the caller believes is current.
                ``None`` skips the check — reserved for runtime-authored
                events (recovery, retention) that cannot conflict.
            transaction: Optional shared transaction to enlist in.

        Returns:
            The append result.

        Raises:
            ScopeViolation: If the task belongs to a different scope.
            RevisionConflict: If ``expected_revision`` does not match and
                the batch is not an exact redelivery. Nothing is mutated.
            ReducerError: If an ``event_id`` is reused with a different
                payload, or an event is malformed.
            LimitExceeded: If the journal's hard cap is exhausted.
        """
        ...

    async def load_snapshot(self, scope: TaskScope, task_id: str) -> Optional[TaskSnapshot]:
        """Load one task's projection consistently.

        Args:
            scope: Trusted runtime scope.
            task_id: The task to load.

        Returns:
            The snapshot, or ``None`` when no such task exists **in this
            scope**. A task that exists in another scope is reported as
            absent, not as forbidden — an existence oracle is a leak.
        """
        ...

    async def list_tasks(
        self,
        scope: TaskScope,
        *,
        statuses: Optional[Sequence[TaskStatus]] = None,
        limit: int = 20,
        cursor: Optional[str] = None,
    ) -> TaskPage:
        """List tasks in a scope, newest activity first.

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
                was issued for a different scope.
        """
        ...

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

        Reads never append. Repeated reads must not change the task's
        sequence or fill the journal — this is what lets recall be
        deterministic and side-effect free (AC10).

        Args:
            scope: Trusted runtime scope.
            task_id: The task to read.
            after_seq: Return events strictly after this sequence.
            limit: Bounded page size.
            as_of_seq: Fence the read at this sequence, so several pages
                taken together describe one instant.

        Returns:
            A bounded page of events.

        Raises:
            ScopeViolation: If the task belongs to a different scope.
        """
        ...

    async def count_events(self, scope: TaskScope, task_id: str) -> int:
        """Return how many events a task's journal holds.

        Used by the retention and capacity rules, which refuse new
        foreground work before the reserved headroom is consumed.

        Args:
            scope: Trusted runtime scope.
            task_id: The task to measure.

        Returns:
            The event count, or ``0`` when the task does not exist in
            this scope.
        """
        ...

    def transaction(self) -> AsyncContextManager[Transaction]:
        """Open a transaction this store and an artifact store can share.

        Returns:
            An async context manager yielding a :class:`Transaction`.
        """
        ...

    async def close(self) -> None:
        """Release any resources the store holds."""
        ...
