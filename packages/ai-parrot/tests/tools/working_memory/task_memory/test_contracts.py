"""Store contract tests and the reusable backend conformance suite (TASK-2972).

This module has two jobs.

1. **Verify the contracts themselves** — the three required cases:
   ``test_leaf_imports``, ``test_scope_required`` and ``test_contracts``.
2. **Publish a reusable conformance suite** that every backend must
   pass, so the in-memory and PostgreSQL stores cannot drift apart
   (AC2). Later tasks subclass it::

       from ..test_contracts import TaskMemoryStoreConformance

       class TestInMemoryStore(TaskMemoryStoreConformance):
           @pytest.fixture()
           async def store(self):
               yield InMemoryTaskMemoryStore()

**Scope of the conformance suite.** It covers the invariants that belong
to *storage*: scope isolation, no-mutation-on-conflict, idempotent
redelivery, contiguous sequences, scoped pagination, and — for artifacts
— alias version monotonicity and byte-bounded reads. It deliberately
does **not** cover reducer semantics (plan validation, readiness,
completion gating): those are pure-function behaviour owned by the
reducer task and are identical by construction once both backends call
the same reducer.

The suite is exercised here against a small **reference double** defined
in this module. The double exists only to prove the suite is executable
and actually discriminating; it is a test fixture, not a shipped
implementation, and it is deliberately incapable of being reused as one
(it holds no reducer and reduces nothing).
"""

from __future__ import annotations

import inspect
from contextlib import asynccontextmanager
from datetime import timezone
from typing import Any, AsyncIterator, Dict, List, Optional, Sequence, Tuple

import pytest
from parrot.interfaces.artifact_store import ArtifactPage, ArtifactStore, PayloadRefusal, PayloadResult
from parrot.interfaces.task_memory import (
    GOAL_PREVIEW_CHARS,
    AppendResult,
    EventPage,
    TaskMemoryStore,
    TaskPage,
    TaskSnapshot,
    TaskSummary,
    Transaction,
    TransactionCoordinator,
)
from parrot.tools.working_memory.task_memory.models import (
    ArtifactDescriptor,
    ArtifactKind,
    CursorError,
    EventType,
    EvidenceRef,
    JournalEvent,
    Limits,
    ReducerError,
    RevisionConflict,
    ScopeViolation,
    TaskLifecyclePayload,
    TaskScope,
    TaskState,
    TaskStatus,
    utc_now,
)
from parrot.tools.working_memory.task_memory.store import (
    MAX_PAGE_LIMIT,
    BaseTaskMemoryStore,
    bounded_limit,
    classify_events,
    decode_cursor,
    encode_cursor,
    ensure_scope,
    goal_preview,
)

# ─────────────────────────────────────────────────────────────
# Deterministic fixtures
# ─────────────────────────────────────────────────────────────

SCOPE_A = TaskScope(chatbot_id="bot-a", user_id="user-1", session_id="sess-1")
SCOPE_B = TaskScope(chatbot_id="bot-a", user_id="user-2", session_id="sess-1")
SCOPE_C = TaskScope(chatbot_id="bot-b", user_id="user-1", session_id="sess-1")


def make_event(
    task_id: str,
    *,
    event_id: str,
    event_type: EventType = EventType.TASK_STARTED,
    status: TaskStatus = TaskStatus.ACTIVE,
    reason: Optional[str] = None,
) -> JournalEvent:
    """Build a deterministic journal event.

    Args:
        task_id: Owning task.
        event_id: Explicit id, so redelivery can be simulated exactly.
        event_type: The event type.
        status: Status carried in the lifecycle payload.
        reason: Optional reason, used to make two events with the same
            id differ.

    Returns:
        The event.
    """
    return JournalEvent(
        event_id=event_id,
        task_id=task_id,
        event_type=event_type,
        occurred_at=utc_now(),
        payload=TaskLifecyclePayload(status=status, reason=reason),
    )


# ─────────────────────────────────────────────────────────────
# Reference double (test fixture only — NOT an implementation)
# ─────────────────────────────────────────────────────────────


class _NoOpTransaction:
    """Minimal :class:`Transaction` for the reference double."""

    def __init__(self) -> None:
        """Initialize an active transaction."""
        self._active = True

    @property
    def is_active(self) -> bool:
        """Whether this transaction is still open."""
        return self._active

    async def rollback(self) -> None:
        """Close the transaction without committing."""
        self._active = False


class _ReferenceTaskMemoryStore(BaseTaskMemoryStore):
    """A storage-only double used to exercise the conformance suite.

    It stores events and tracks revisions. It runs **no reducer** — the
    projection it returns advances ``revision`` and ``last_event_seq``
    and nothing else. That is exactly enough to prove the storage
    invariants the conformance suite asserts, and deliberately not enough
    to be mistaken for a usable backend.
    """

    def __init__(self) -> None:
        """Initialize empty storage."""
        self._tasks: Dict[str, Tuple[TaskScope, TaskState]] = {}
        self._events: Dict[str, List[JournalEvent]] = {}

    async def close(self) -> None:
        """Drop everything held in memory."""
        self._tasks.clear()
        self._events.clear()

    def _lookup(self, scope: TaskScope, task_id: str) -> Optional[Tuple[TaskScope, TaskState]]:
        """Return a task row after enforcing scope, or ``None``.

        Args:
            scope: Caller's trusted scope.
            task_id: The task to find.

        Returns:
            The stored row, or ``None`` when it does not exist in this
            scope.
        """
        row = self._tasks.get(task_id)
        if row is None:
            return None
        stored_scope, _ = row
        if not scope.matches(stored_scope):
            return None
        return row

    async def create_task(
        self,
        scope: TaskScope,
        *,
        goal: str,
        events: Sequence[JournalEvent],
        transaction: Optional[Transaction] = None,
    ) -> AppendResult:
        """Create a task and append its first events atomically."""
        task_id = events[0].task_id
        state = TaskState(task_id=task_id, scope=scope, goal=goal)
        self._tasks[task_id] = (scope, state)
        self._events[task_id] = []
        return await self.append_events(scope, task_id, events, expected_revision=0)

    async def append_events(
        self,
        scope: TaskScope,
        task_id: str,
        events: Sequence[JournalEvent],
        *,
        expected_revision: Optional[int] = None,
        transaction: Optional[Transaction] = None,
    ) -> AppendResult:
        """Append a batch under an optimistic revision check."""
        row = self._tasks.get(task_id)
        if row is None:
            raise ScopeViolation("task does not exist in this scope")
        stored_scope, state = row
        self._ensure_scope(scope, stored_scope, subject="task")

        stored = self._events[task_id]
        existing = {e.event_id: e for e in stored}
        classification = self._classify(events, existing)

        # Redelivery is recognised BEFORE the revision check: a caller
        # retrying a batch that in fact committed has a legitimately
        # stale revision.
        if classification.is_noop:
            return AppendResult(
                state=state,
                appended_event_ids=(),
                deduplicated_event_ids=classification.duplicates,
                first_seq=None,
                last_seq=state.last_event_seq,
            )

        if expected_revision is not None and expected_revision != state.revision:
            raise RevisionConflict(task_id, expected_revision, state.revision)

        sequences = list(self._sequence_range(state.last_event_seq, len(classification.fresh)))
        appended: List[str] = []
        for seq, event in zip(sequences, classification.fresh):
            stored.append(event.model_copy(update={"seq": seq}))
            appended.append(event.event_id)

        new_state = state.model_copy(
            update={
                "revision": state.revision + 1,
                "last_event_seq": sequences[-1],
                "updated_at": utc_now(),
            }
        )
        self._tasks[task_id] = (stored_scope, new_state)
        return AppendResult(
            state=new_state,
            appended_event_ids=tuple(appended),
            deduplicated_event_ids=classification.duplicates,
            first_seq=sequences[0],
            last_seq=sequences[-1],
        )

    async def load_snapshot(self, scope: TaskScope, task_id: str) -> Optional[TaskSnapshot]:
        """Load a task's projection, or ``None`` when out of scope."""
        row = self._lookup(scope, task_id)
        if row is None:
            return None
        _, state = row
        return TaskSnapshot(
            state=state,
            as_of_seq=state.last_event_seq,
            event_count=len(self._events[task_id]),
        )

    async def list_tasks(
        self,
        scope: TaskScope,
        *,
        statuses: Optional[Sequence[TaskStatus]] = None,
        limit: int = 20,
        cursor: Optional[str] = None,
    ) -> TaskPage:
        """List this scope's tasks with an opaque scoped cursor."""
        size = self._bounded(limit, default=self.default_task_page)
        wanted = tuple(s.value for s in statuses) if statuses else None
        query = {"statuses": wanted}

        rows = [(tid, st) for tid, (sc, st) in self._tasks.items() if scope.matches(sc)]
        rows.sort(key=lambda item: item[0])
        if statuses is not None:
            rows = [r for r in rows if r[1].status in statuses]

        start = 0
        if cursor is not None:
            position = self._decode_cursor(cursor, scope, query)
            start = int(position["offset"])
            if start > len(rows):
                raise CursorError("cursor is out of bounds")

        window = rows[start : start + size]
        next_cursor = self._encode_cursor(scope, query, {"offset": start + size}) if start + size < len(rows) else None
        return TaskPage(
            items=tuple(
                TaskSummary(
                    task_id=tid,
                    goal_preview=goal_preview(st.goal, chars=GOAL_PREVIEW_CHARS),
                    status=st.status,
                    updated_at=st.updated_at,
                )
                for tid, st in window
            ),
            next_cursor=next_cursor,
            total_open=sum(1 for _, st in rows if not st.status.is_terminal),
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
        """Page a task's journal without appending anything."""
        row = self._lookup(scope, task_id)
        if row is None:
            raise ScopeViolation("task does not exist in this scope")
        size = self._bounded(limit, default=self.default_event_page)
        events = [e for e in self._events[task_id] if e.seq > after_seq]
        if as_of_seq is not None:
            events = [e for e in events if e.seq <= as_of_seq]
        window = events[:size]
        return EventPage(
            events=tuple(window),
            next_seq=window[-1].seq if window else after_seq,
            has_more=len(events) > size,
        )

    async def count_events(self, scope: TaskScope, task_id: str) -> int:
        """Count a task's journal events, or ``0`` when out of scope."""
        return 0 if self._lookup(scope, task_id) is None else len(self._events[task_id])

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Transaction]:
        """Yield a no-op transaction handle."""
        tx = _NoOpTransaction()
        try:
            yield tx
        except Exception:
            await tx.rollback()
            raise


class _ReferenceArtifactStore:
    """A storage-only artifact double used to exercise the conformance suite.

    It implements alias/version bookkeeping and the byte ceiling, which
    is what the conformance suite asserts. It performs no snapshotting,
    no fingerprinting and no durable I/O.
    """

    def __init__(self) -> None:
        """Initialize empty storage."""
        # (scope_key, task_id, key) -> artifact_id
        self._aliases: Dict[Tuple[str, Optional[str], str], str] = {}
        # (scope_key, artifact_id, version) -> (descriptor, payload)
        self._versions: Dict[Tuple[str, str, int], Tuple[ArtifactDescriptor, Any]] = {}
        self._latest: Dict[Tuple[str, str], int] = {}
        self._counter = 0
        self._generation = 0

    async def close(self) -> None:
        """Drop everything held in memory."""
        self._aliases.clear()
        self._versions.clear()
        self._latest.clear()

    async def put(
        self,
        scope: TaskScope,
        key: str,
        value: Any,
        *,
        task_id: Optional[str] = None,
        kind: Optional[ArtifactKind] = None,
        description: str = "",
        producer_call_id: Optional[str] = None,
        attribution: Any = None,
        turn_id: Optional[str] = None,
        metadata: Optional[dict] = None,
        transaction: Optional[Any] = None,
    ) -> ArtifactDescriptor:
        """Register a value, allocating or incrementing its version."""
        sk = scope.cache_key()
        alias_key = (sk, task_id, key)
        artifact_id = self._aliases.get(alias_key)
        if artifact_id is None:
            self._counter += 1
            artifact_id = f"art-{self._counter}"
            self._aliases[alias_key] = artifact_id
        version = self._latest.get((sk, artifact_id), 0) + 1
        self._latest[(sk, artifact_id)] = version

        descriptor = ArtifactDescriptor(
            ref=EvidenceRef(artifact_id=artifact_id, version=version),
            alias=key,
            scope=scope,
            task_id=task_id,
            producer_call_id=producer_call_id,
            kind=kind or ArtifactKind.JSON,
            byte_size=len(repr(value).encode("utf-8")),
        )
        self._versions[(sk, artifact_id, version)] = (descriptor, value)
        return descriptor

    async def get_current(
        self, scope: TaskScope, key: str, *, task_id: Optional[str] = None
    ) -> Optional[ArtifactDescriptor]:
        """Resolve an alias to its current version within one namespace."""
        sk = scope.cache_key()
        artifact_id = self._aliases.get((sk, task_id, key))
        if artifact_id is None:
            return None
        version = self._latest[(sk, artifact_id)]
        return self._versions[(sk, artifact_id, version)][0]

    async def get_version(
        self, scope: TaskScope, ref: EvidenceRef, *, task_id: Optional[str] = None
    ) -> Optional[ArtifactDescriptor]:
        """Resolve one exact version, checking scope."""
        entry = self._versions.get((scope.cache_key(), ref.artifact_id, ref.version))
        return None if entry is None else entry[0]

    async def load_payload(
        self,
        scope: TaskScope,
        ref: EvidenceRef,
        *,
        max_bytes: int,
        offset: Optional[int] = None,
        limit: Optional[int] = None,
    ) -> PayloadResult:
        """Materialize a payload under a hard byte ceiling."""
        entry = self._versions.get((scope.cache_key(), ref.artifact_id, ref.version))
        if entry is None:
            return PayloadResult(
                ref=ref, kind=ArtifactKind.JSON, refusal=PayloadRefusal.MISSING, guidance="unknown version"
            )
        descriptor, value = entry
        size = descriptor.byte_size or 0
        if max_bytes == 0 or size > max_bytes:
            return PayloadResult(
                ref=ref,
                kind=descriptor.kind,
                refusal=PayloadRefusal.TOO_LARGE,
                byte_size=size,
                guidance="use wm_compute_and_store instead of rehydrating",
            )
        return PayloadResult(ref=ref, kind=descriptor.kind, payload=value, byte_size=size, returned_bytes=size)

    async def invalidate(
        self, scope: TaskScope, ref: EvidenceRef, *, reason: str, transaction: Optional[Any] = None
    ) -> ArtifactDescriptor:
        """Mark a version's content as no longer valid evidence."""
        sk = scope.cache_key()
        entry = self._versions.get((sk, ref.artifact_id, ref.version))
        if entry is None:
            raise ScopeViolation("artifact version does not exist in this scope")
        descriptor, value = entry
        updated = descriptor.model_copy(update={"invalidated": True, "invalidated_at": utc_now()})
        self._versions[(sk, ref.artifact_id, ref.version)] = (updated, value)
        self._generation += 1
        return updated

    async def list(
        self,
        scope: TaskScope,
        *,
        task_id: Optional[str] = None,
        kinds: Optional[Sequence[ArtifactKind]] = None,
        limit: int = 50,
        cursor: Optional[str] = None,
        as_of_seq: Optional[int] = None,
    ) -> ArtifactPage:
        """Page descriptors in a scope with an opaque scoped cursor."""
        sk = scope.cache_key()
        size = bounded_limit(limit, default=50)
        rows = [d for (s, _, _), (d, _) in self._versions.items() if s == sk]
        if task_id is not None:
            rows = [d for d in rows if d.task_id == task_id]
        rows.sort(key=lambda d: (d.ref.artifact_id, d.ref.version))

        query = {"task_id": task_id}
        start = 0
        if cursor is not None:
            start = int(decode_cursor(cursor, scope, query)["offset"])
            if start > len(rows):
                raise CursorError("cursor is out of bounds")
        window = rows[start : start + size]
        next_cursor = encode_cursor(scope, query, {"offset": start + size}) if start + size < len(rows) else None
        return ArtifactPage(items=tuple(window), next_cursor=next_cursor, availability_generation=self._generation)

    async def evict(self, scope: TaskScope, ref: EvidenceRef) -> bool:
        """Release retained bytes, keeping the metadata tombstone."""
        sk = scope.cache_key()
        entry = self._versions.get((sk, ref.artifact_id, ref.version))
        if entry is None:
            return False
        descriptor, _ = entry
        self._versions[(sk, ref.artifact_id, ref.version)] = (descriptor, None)
        self._generation += 1
        return True

    async def drop_alias(self, scope: TaskScope, key: str, *, task_id: Optional[str] = None) -> bool:
        """Remove a live alias without deleting the versions behind it."""
        return self._aliases.pop((scope.cache_key(), task_id, key), None) is not None

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[Transaction]:
        """Yield a no-op transaction handle."""
        yield _NoOpTransaction()


# ─────────────────────────────────────────────────────────────
# Reusable conformance suites
# ─────────────────────────────────────────────────────────────


class TaskMemoryStoreConformance:
    """Storage invariants every :class:`TaskMemoryStore` backend must satisfy.

    Subclass it and provide a ``store`` fixture. Reducer semantics are
    intentionally out of scope (see the module docstring).
    """

    @pytest.fixture()
    async def store(self) -> AsyncIterator[TaskMemoryStore]:  # pragma: no cover - overridden
        """Yield a fresh, empty backend under test."""
        raise NotImplementedError("conformance subclasses must provide a `store` fixture")

    async def _create(self, store: TaskMemoryStore, scope: TaskScope, task_id: str) -> AppendResult:
        """Create one task with a single ``task_started`` event.

        Args:
            store: The backend under test.
            scope: Owning scope.
            task_id: The task id to create.

        Returns:
            The append result.
        """
        return await store.create_task(
            scope, goal=f"goal for {task_id}", events=[make_event(task_id, event_id=f"{task_id}-e1")]
        )

    @pytest.mark.asyncio
    async def test_conformance_scope_isolation(self, store: TaskMemoryStore) -> None:
        """A task never resolves from another scope, and reads as absent."""
        await self._create(store, SCOPE_A, "t-1")

        for foreign in (SCOPE_B, SCOPE_C):
            assert await store.load_snapshot(foreign, "t-1") is None, "a task id is not authorization"
            assert await store.count_events(foreign, "t-1") == 0
            with pytest.raises(ScopeViolation):
                await store.list_events(foreign, "t-1")
            with pytest.raises(ScopeViolation):
                await store.append_events(foreign, "t-1", [make_event("t-1", event_id="x")], expected_revision=1)

        page = await store.list_tasks(SCOPE_B)
        assert page.items == (), "another scope's tasks must not be listed"

    @pytest.mark.asyncio
    async def test_conformance_conflict_mutates_nothing(self, store: TaskMemoryStore) -> None:
        """A stale expected revision raises and leaves the task untouched."""
        created = await self._create(store, SCOPE_A, "t-1")
        before = await store.load_snapshot(SCOPE_A, "t-1")
        assert before is not None

        with pytest.raises(RevisionConflict) as excinfo:
            await store.append_events(
                SCOPE_A,
                "t-1",
                [make_event("t-1", event_id="t-1-e2", event_type=EventType.TASK_PAUSED, status=TaskStatus.PAUSED)],
                expected_revision=created.revision + 99,
            )
        assert excinfo.value.current == created.revision

        after = await store.load_snapshot(SCOPE_A, "t-1")
        assert after is not None
        assert after.state.revision == before.state.revision
        assert after.as_of_seq == before.as_of_seq
        assert after.event_count == before.event_count

    @pytest.mark.asyncio
    async def test_conformance_exact_replay_is_a_noop(self, store: TaskMemoryStore) -> None:
        """Redelivering a committed batch is a no-op, not a conflict."""
        created = await self._create(store, SCOPE_A, "t-1")
        event = make_event("t-1", event_id="t-1-e2", event_type=EventType.TASK_PAUSED, status=TaskStatus.PAUSED)

        first = await store.append_events(SCOPE_A, "t-1", [event], expected_revision=created.revision)
        assert first.appended_event_ids == ("t-1-e2",)

        # The caller's revision is now stale *because its own attempt
        # succeeded*. Redelivery must still be recognised first.
        replay = await store.append_events(SCOPE_A, "t-1", [event], expected_revision=created.revision)
        assert replay.was_noop
        assert replay.deduplicated_event_ids == ("t-1-e2",)
        assert replay.appended_event_ids == ()
        assert replay.last_seq == first.last_seq

        snapshot = await store.load_snapshot(SCOPE_A, "t-1")
        assert snapshot is not None
        assert snapshot.event_count == 2, "a redelivery must not duplicate the event"
        assert snapshot.state.revision == first.revision, "a redelivery must not advance the revision"

    @pytest.mark.asyncio
    async def test_conformance_reused_id_with_different_payload_is_rejected(self, store: TaskMemoryStore) -> None:
        """An id may be redelivered, never rewritten."""
        created = await self._create(store, SCOPE_A, "t-1")
        original = make_event("t-1", event_id="t-1-e2", event_type=EventType.TASK_PAUSED, status=TaskStatus.PAUSED)
        await store.append_events(SCOPE_A, "t-1", [original], expected_revision=created.revision)

        forged = make_event(
            "t-1",
            event_id="t-1-e2",
            event_type=EventType.TASK_PAUSED,
            status=TaskStatus.PAUSED,
            reason="different payload",
        )
        with pytest.raises(ReducerError):
            await store.append_events(SCOPE_A, "t-1", [forged], expected_revision=None)

    @pytest.mark.asyncio
    async def test_conformance_sequences_are_contiguous(self, store: TaskMemoryStore) -> None:
        """Deduplication leaves no gaps: a skipped event consumes no sequence."""
        result = await self._create(store, SCOPE_A, "t-1")
        events = [
            make_event("t-1", event_id=f"t-1-e{n}", event_type=EventType.TASK_PAUSED, status=TaskStatus.PAUSED)
            for n in range(2, 5)
        ]
        result = await store.append_events(SCOPE_A, "t-1", events, expected_revision=result.revision)

        # Redeliver the middle event alongside a genuinely new one.
        mixed = [events[1], make_event("t-1", event_id="t-1-e9", status=TaskStatus.ACTIVE)]
        result = await store.append_events(SCOPE_A, "t-1", mixed, expected_revision=result.revision)
        assert result.deduplicated_event_ids == ("t-1-e3",)
        assert result.appended_event_ids == ("t-1-e9",)

        page = await store.list_events(SCOPE_A, "t-1", limit=MAX_PAGE_LIMIT)
        sequences = [e.seq for e in page.events]
        assert sequences == list(range(1, len(sequences) + 1)), f"sequences must be contiguous: {sequences}"

    @pytest.mark.asyncio
    async def test_conformance_reads_never_append(self, store: TaskMemoryStore) -> None:
        """Repeated reads must not change the task's sequence or fill the journal."""
        await self._create(store, SCOPE_A, "t-1")
        before = await store.load_snapshot(SCOPE_A, "t-1")
        assert before is not None

        for _ in range(5):
            await store.load_snapshot(SCOPE_A, "t-1")
            await store.list_events(SCOPE_A, "t-1")
            await store.list_tasks(SCOPE_A)
            await store.count_events(SCOPE_A, "t-1")

        after = await store.load_snapshot(SCOPE_A, "t-1")
        assert after is not None
        assert (after.as_of_seq, after.event_count, after.state.revision) == (
            before.as_of_seq,
            before.event_count,
            before.state.revision,
        )

    @pytest.mark.asyncio
    async def test_conformance_pagination_is_scoped_and_bounded(self, store: TaskMemoryStore) -> None:
        """Cursors are opaque, bounded, and rejected outside their scope."""
        for n in range(5):
            await self._create(store, SCOPE_A, f"t-{n}")
        await self._create(store, SCOPE_B, "t-other")

        first = await store.list_tasks(SCOPE_A, limit=2)
        assert len(first.items) == 2
        assert first.next_cursor is not None

        second = await store.list_tasks(SCOPE_A, limit=2, cursor=first.next_cursor)
        assert len(second.items) == 2
        assert {i.task_id for i in first.items} & {i.task_id for i in second.items} == set()

        # A cursor issued in one scope is not usable in another.
        with pytest.raises(CursorError):
            await store.list_tasks(SCOPE_B, limit=2, cursor=first.next_cursor)

        with pytest.raises(CursorError):
            await store.list_tasks(SCOPE_A, limit=2, cursor="not-a-cursor")

        with pytest.raises(CursorError):
            await store.list_tasks(SCOPE_A, limit=0)

        # A caller cannot page past the hard ceiling.
        huge = await store.list_tasks(SCOPE_A, limit=10_000)
        assert len(huge.items) <= MAX_PAGE_LIMIT

    @pytest.mark.asyncio
    async def test_conformance_goal_preview_is_bounded(self, store: TaskMemoryStore) -> None:
        """A listing shows a bounded goal preview, never the whole goal."""
        long_goal = "G" * (GOAL_PREVIEW_CHARS * 3)
        await store.create_task(SCOPE_A, goal=long_goal, events=[make_event("t-long", event_id="t-long-e1")])
        page = await store.list_tasks(SCOPE_A)
        summary = next(i for i in page.items if i.task_id == "t-long")
        assert len(summary.goal_preview) <= GOAL_PREVIEW_CHARS


class ArtifactStoreConformance:
    """Storage invariants every :class:`ArtifactStore` backend must satisfy.

    Subclass it and provide an ``artifacts`` fixture.
    """

    @pytest.fixture()
    async def artifacts(self) -> AsyncIterator[ArtifactStore]:  # pragma: no cover - overridden
        """Yield a fresh, empty artifact backend under test."""
        raise NotImplementedError("conformance subclasses must provide an `artifacts` fixture")

    @pytest.mark.asyncio
    async def test_conformance_alias_versions_are_monotonic(self, artifacts: ArtifactStore) -> None:
        """Overwriting an alias increments the same identity's version."""
        first = await artifacts.put(SCOPE_A, "sales", {"n": 1}, task_id="t-1")
        second = await artifacts.put(SCOPE_A, "sales", {"n": 2}, task_id="t-1")

        assert second.ref.artifact_id == first.ref.artifact_id, "an overwrite keeps the same identity"
        assert second.ref.version == first.ref.version + 1

        current = await artifacts.get_current(SCOPE_A, "sales", task_id="t-1")
        assert current is not None and current.ref == second.ref

    @pytest.mark.asyncio
    async def test_conformance_overwrite_preserves_older_evidence(self, artifacts: ArtifactStore) -> None:
        """An overwrite is not a mutation: the old version stays resolvable."""
        first = await artifacts.put(SCOPE_A, "sales", {"n": 1}, task_id="t-1")
        await artifacts.put(SCOPE_A, "sales", {"n": 2}, task_id="t-1")

        old = await artifacts.get_version(SCOPE_A, first.ref, task_id="t-1")
        assert old is not None
        assert old.ref == first.ref
        assert old.invalidated is False

        payload = await artifacts.load_payload(SCOPE_A, first.ref, max_bytes=10_000)
        assert payload.ok and payload.payload == {"n": 1}

    @pytest.mark.asyncio
    async def test_conformance_alias_namespace_is_task_scoped(self, artifacts: ArtifactStore) -> None:
        """A plain key never searches another task's namespace."""
        await artifacts.put(SCOPE_A, "sales", {"task": 1}, task_id="t-1")
        assert await artifacts.get_current(SCOPE_A, "sales", task_id="t-2") is None

        other = await artifacts.put(SCOPE_A, "sales", {"task": 2}, task_id="t-2")
        mine = await artifacts.get_current(SCOPE_A, "sales", task_id="t-1")
        assert mine is not None
        assert mine.ref.artifact_id != other.ref.artifact_id

    @pytest.mark.asyncio
    async def test_conformance_version_lookup_requires_scope(self, artifacts: ArtifactStore) -> None:
        """A globally unique artifact id is not a capability."""
        descriptor = await artifacts.put(SCOPE_A, "sales", {"n": 1}, task_id="t-1")

        for foreign in (SCOPE_B, SCOPE_C):
            assert await artifacts.get_version(foreign, descriptor.ref) is None
            assert await artifacts.get_current(foreign, "sales", task_id="t-1") is None
            result = await artifacts.load_payload(foreign, descriptor.ref, max_bytes=10_000)
            assert not result.ok and result.payload is None

    @pytest.mark.asyncio
    async def test_conformance_byte_ceiling_refusal_carries_no_payload(self, artifacts: ArtifactStore) -> None:
        """An over-limit read refuses; it does not load and then truncate."""
        descriptor = await artifacts.put(SCOPE_A, "big", {"blob": "x" * 5_000}, task_id="t-1")

        refused = await artifacts.load_payload(SCOPE_A, descriptor.ref, max_bytes=10)
        assert not refused.ok
        assert refused.payload is None, "a refusal must carry no payload"
        assert refused.refusal == PayloadRefusal.TOO_LARGE
        assert refused.guidance, "a refusal must point the caller somewhere useful"

        never = await artifacts.load_payload(SCOPE_A, descriptor.ref, max_bytes=0)
        assert not never.ok and never.payload is None, "0 means never rehydrate"

    @pytest.mark.asyncio
    async def test_conformance_drop_alias_keeps_versions(self, artifacts: ArtifactStore) -> None:
        """Dropping a live alias does not delete the pinned snapshots."""
        descriptor = await artifacts.put(SCOPE_A, "sales", {"n": 1}, task_id="t-1")
        assert await artifacts.drop_alias(SCOPE_A, "sales", task_id="t-1") is True
        assert await artifacts.get_current(SCOPE_A, "sales", task_id="t-1") is None

        survived = await artifacts.get_version(SCOPE_A, descriptor.ref, task_id="t-1")
        assert survived is not None, "drop_stored removes the alias, not the evidence"

    @pytest.mark.asyncio
    async def test_conformance_invalidate_is_not_deletion(self, artifacts: ArtifactStore) -> None:
        """Invalidation is a statement about evidence, not about bytes."""
        descriptor = await artifacts.put(SCOPE_A, "sales", {"n": 1}, task_id="t-1")
        updated = await artifacts.invalidate(SCOPE_A, descriptor.ref, reason="source mutated")
        assert updated.invalidated is True
        assert updated.invalidated_at is not None

        still_there = await artifacts.get_version(SCOPE_A, descriptor.ref)
        assert still_there is not None and still_there.invalidated is True

    @pytest.mark.asyncio
    async def test_conformance_eviction_changes_availability_generation(self, artifacts: ArtifactStore) -> None:
        """Availability can change without a task event; the generation must move."""
        descriptor = await artifacts.put(SCOPE_A, "sales", {"n": 1}, task_id="t-1")
        before = (await artifacts.list(SCOPE_A, task_id="t-1")).availability_generation

        assert await artifacts.evict(SCOPE_A, descriptor.ref) is True
        after = (await artifacts.list(SCOPE_A, task_id="t-1")).availability_generation
        assert after != before, "recall's cache key depends on this changing"

        # The metadata tombstone remains.
        assert await artifacts.get_version(SCOPE_A, descriptor.ref) is not None

    @pytest.mark.asyncio
    async def test_conformance_listing_is_scoped_and_paged(self, artifacts: ArtifactStore) -> None:
        """Artifact listings are scoped, bounded and cursor-validated."""
        for n in range(5):
            await artifacts.put(SCOPE_A, f"k{n}", {"n": n}, task_id="t-1")
        await artifacts.put(SCOPE_B, "k0", {"n": 99}, task_id="t-1")

        first = await artifacts.list(SCOPE_A, task_id="t-1", limit=2)
        assert len(first.items) == 2 and first.next_cursor is not None
        assert all(d.scope.matches(SCOPE_A) for d in first.items)

        with pytest.raises(CursorError):
            await artifacts.list(SCOPE_B, task_id="t-1", limit=2, cursor=first.next_cursor)


# ─────────────────────────────────────────────────────────────
# The suites, run against the reference double
# ─────────────────────────────────────────────────────────────


class TestReferenceTaskMemoryStore(TaskMemoryStoreConformance):
    """Proves the task-store conformance suite is executable and discriminating."""

    @pytest.fixture()
    async def store(self) -> AsyncIterator[TaskMemoryStore]:
        """Yield a fresh reference double."""
        backend = _ReferenceTaskMemoryStore()
        try:
            yield backend
        finally:
            await backend.close()


class TestReferenceArtifactStore(ArtifactStoreConformance):
    """Proves the artifact-store conformance suite is executable and discriminating."""

    @pytest.fixture()
    async def artifacts(self) -> AsyncIterator[ArtifactStore]:
        """Yield a fresh reference double."""
        backend = _ReferenceArtifactStore()
        try:
            yield backend
        finally:
            await backend.close()


# ─────────────────────────────────────────────────────────────
# Required case: leaf imports
# ─────────────────────────────────────────────────────────────

#: Modules a contract must never drag in. ``parrot.storage.artifacts`` is
#: on the list to prove the name collision is only a name.
_FORBIDDEN_MODULES = (
    "pandas",
    "numpy",
    "asyncpg",
    "redis",
    "pyarrow",
    "parrot.tools.repl_worker",
    "parrot.storage.artifacts",
    "parrot.tools.working_memory.tool",
)


#: Contract and shared-machinery modules this task owns.
_CONTRACT_MODULES = (
    "parrot.interfaces.task_memory",
    "parrot.interfaces.artifact_store",
    "parrot.tools.working_memory.task_memory.store._base",
    "parrot.tools.working_memory.task_memory.store",
)

#: Baseline every contract module unavoidably pays for, because the
#: domain models live under ``parrot.tools.working_memory`` and that
#: package's ``__init__`` eagerly imports the toolkit (and therefore
#: pandas). See ``test_leaf_imports_records_the_package_baseline`` — this
#: is a pre-existing property of the package layout, NOT something these
#: contracts introduce, and the delta probe below is what actually holds
#: them to account.
_BASELINE_MODULE = "parrot.tools.working_memory.task_memory.models"


def _loaded_forbidden(*modules: str) -> set:
    """Import ``modules`` in a fresh interpreter; report forbidden arrivals.

    Args:
        *modules: Dotted module paths to import, in order.

    Returns:
        The set of forbidden modules present in ``sys.modules``
        afterwards.
    """
    import subprocess
    import sys

    code = (
        "import sys, importlib;"
        f"[importlib.import_module(m) for m in {list(modules)!r}];"
        f"forbidden = {_FORBIDDEN_MODULES!r};"
        "print('LOADED=' + ','.join(n for n in forbidden if n in sys.modules))"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, f"importing {modules} failed:\n{result.stderr}"
    line = next(ln for ln in result.stdout.splitlines() if ln.startswith("LOADED="))
    payload = line.removeprefix("LOADED=")
    return set(payload.split(",")) if payload else set()


def _direct_imports(module: str) -> set:
    """Return the module names a source file imports directly.

    Parsing the AST rather than executing the module is the point: it
    answers "what does *this file* ask for", independent of what its
    package's ``__init__`` happens to drag in.

    Args:
        module: Dotted module path.

    Returns:
        Set of top-level dotted names appearing in ``import`` /
        ``from ... import`` statements.
    """
    import ast
    import importlib
    from pathlib import Path

    source = Path(importlib.import_module(module).__file__).read_text(encoding="utf-8")
    names: set = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module)
    return names


def test_leaf_imports() -> None:
    """Required case: contracts add no heavy backend, database or worker import.

    Two independent probes, because either alone would be weak:

    1. **Structural** — no contract module *asks for* a forbidden module.
       An AST scan, so a package ``__init__``'s behaviour cannot mask a
       real dependency.
    2. **Behavioural (delta)** — importing the contract pulls in nothing
       forbidden *beyond* what the domain models already cost. This is
       what proves the contract itself is not the thing dragging in
       ``asyncpg``.
    """
    # 1. Structural.
    for module in _CONTRACT_MODULES:
        for imported in _direct_imports(module):
            root = imported.split(".")[0]
            assert root not in {"pandas", "numpy", "asyncpg", "redis", "pyarrow"}, (
                f"{module} directly imports {imported!r}: a contract that pulls in a "
                "driver or a dataframe library is a dependency, not a contract"
            )
            assert not imported.startswith("parrot.tools.repl_worker"), f"{module} directly imports {imported!r}"
            assert imported != "parrot.storage.artifacts", (
                f"{module} imports the unrelated conversation ArtifactStore; "
                "the name collision must stay a name collision"
            )

    # 2. Behavioural delta.
    baseline = _loaded_forbidden(_BASELINE_MODULE)
    for module in _CONTRACT_MODULES:
        added = _loaded_forbidden(_BASELINE_MODULE, module) - baseline
        assert added == set(), f"{module} pulled in forbidden modules beyond the baseline: {sorted(added)}"


def test_leaf_imports_records_the_package_baseline() -> None:
    """Document the pre-existing cost of the package layout, honestly.

    ``parrot/tools/working_memory/__init__.py`` line 2 eagerly does
    ``from .tool import WorkingMemoryToolkit``, so importing *any*
    submodule under it — including the leaf-safe domain models — loads
    pandas. The contract modules are therefore leaf-safe in what they
    require but not in what the import system charges them.

    This test asserts the situation rather than pretending it away, and
    will fail (prompting this note's removal) if the M5 task that owns
    that ``__init__`` makes the toolkit import lazy.
    """
    baseline = _loaded_forbidden(_BASELINE_MODULE)
    assert "pandas" in baseline, (
        "the working_memory package __init__ no longer eagerly imports the toolkit — "
        "tighten test_leaf_imports to an absolute check and delete this test"
    )
    # The models themselves ask for none of it.
    assert not {i.split(".")[0] for i in _direct_imports(_BASELINE_MODULE)} & {
        "pandas",
        "numpy",
        "asyncpg",
        "redis",
        "pyarrow",
    }


def test_leaf_imports_artifact_store_is_not_the_conversation_one() -> None:
    """The D1 ``ArtifactStore`` is a different class from the storage one."""
    from parrot.interfaces.artifact_store import ArtifactStore as TaskArtifactStore
    from parrot.storage.artifacts import ArtifactStore as ConversationArtifactStore

    assert TaskArtifactStore is not ConversationArtifactStore
    assert TaskArtifactStore.__module__ == "parrot.interfaces.artifact_store"
    assert ConversationArtifactStore.__module__ == "parrot.storage.artifacts"


# ─────────────────────────────────────────────────────────────
# Required case: scope is mandatory
# ─────────────────────────────────────────────────────────────


def _first_parameter_names(protocol: type) -> Dict[str, List[str]]:
    """Return each public method's parameter names, excluding ``self``.

    Args:
        protocol: The protocol class to inspect.

    Returns:
        A mapping of method name to ordered parameter names.
    """
    names: Dict[str, List[str]] = {}
    for name, member in vars(protocol).items():
        if name.startswith("_") or not callable(member):
            continue
        signature = inspect.signature(member)
        names[name] = [p for p in signature.parameters if p != "self"]
    return names


def test_scope_required() -> None:
    """Required case: every lookup/load/invalidation signature takes a trusted scope.

    A missing scope parameter is not a style problem: it is a
    cross-user read primitive. The check is structural so a future
    method cannot be added without one.
    """
    exempt = {"transaction", "close"}

    for protocol in (TaskMemoryStore, ArtifactStore):
        for method, params in _first_parameter_names(protocol).items():
            if method in exempt:
                continue
            assert params, f"{protocol.__name__}.{method} takes no parameters at all"
            assert params[0] == "scope", (
                f"{protocol.__name__}.{method} must take `scope` as its first parameter; " f"got {params[0]!r}"
            )


def test_scope_required_scope_types_are_the_trusted_model() -> None:
    """The ``scope`` parameter is typed as :class:`TaskScope`, not a bare string."""
    for protocol in (TaskMemoryStore, ArtifactStore):
        for name, member in vars(protocol).items():
            if name.startswith("_") or not callable(member) or name in {"transaction", "close"}:
                continue
            annotation = inspect.signature(member).parameters["scope"].annotation
            assert annotation in (TaskScope, "TaskScope"), f"{protocol.__name__}.{name} scope annotation={annotation!r}"


def test_scope_required_helper_rejects_every_mismatched_component() -> None:
    """``ensure_scope`` rejects a difference in any one component."""
    ensure_scope(SCOPE_A, SCOPE_A, subject="task")

    for foreign in (
        SCOPE_A.model_copy(update={"chatbot_id": "other"}),
        SCOPE_A.model_copy(update={"user_id": "other"}),
        SCOPE_A.model_copy(update={"session_id": "other"}),
    ):
        with pytest.raises(ScopeViolation):
            ensure_scope(SCOPE_A, foreign, subject="task")


def test_scope_required_cache_keys_cannot_be_forged() -> None:
    """Percent-encoding stops a component value from forging another scope's key."""
    sneaky = TaskScope(chatbot_id="bot-a:user-1", user_id="sess-1", session_id="x")
    plain = TaskScope(chatbot_id="bot-a", user_id="user-1", session_id="sess-1")
    assert sneaky.cache_key() != plain.cache_key()
    assert ":" in plain.cache_key()


# ─────────────────────────────────────────────────────────────
# Required case: the contract helpers themselves
# ─────────────────────────────────────────────────────────────


def test_contracts_protocols_are_runtime_checkable() -> None:
    """The reference doubles satisfy the protocols at runtime."""
    assert isinstance(_ReferenceTaskMemoryStore(), TaskMemoryStore)
    assert isinstance(_ReferenceArtifactStore(), ArtifactStore)
    assert isinstance(_NoOpTransaction(), Transaction)


def test_contracts_transaction_coordinator_shape() -> None:
    """A coordinator exposes ``begin``; the store exposes ``transaction``."""

    class _Coordinator:
        @asynccontextmanager
        async def begin(self) -> AsyncIterator[Transaction]:
            yield _NoOpTransaction()

    assert isinstance(_Coordinator(), TransactionCoordinator)


def test_contracts_classify_events_separates_replay_from_rewrite() -> None:
    """Redelivery is a no-op; the same id with a different payload is rejected."""
    original = make_event("t-1", event_id="e1")
    committed = {original.event_id: original.model_copy(update={"seq": 1})}

    # Exact redelivery, including one that has not been sequenced yet.
    replay = classify_events([original], committed)
    assert replay.is_noop and replay.duplicates == ("e1",)

    # Genuinely new.
    fresh = make_event("t-1", event_id="e2")
    mixed = classify_events([original, fresh], committed)
    assert mixed.duplicates == ("e1",)
    assert [e.event_id for e in mixed.fresh] == ["e2"]

    # Same id, different payload — rejected against committed history.
    forged = make_event("t-1", event_id="e1", reason="tampered")
    with pytest.raises(ReducerError, match="never rewritten"):
        classify_events([forged], committed)

    # Same id, different payload — rejected within one batch.
    with pytest.raises(ReducerError, match="within one batch"):
        classify_events([fresh, make_event("t-1", event_id="e2", reason="tampered")], {})

    assert repr(mixed).startswith("EventClassification(")


def test_contracts_cursors_are_opaque_and_bound() -> None:
    """A cursor is bound to its scope and its query, and is not a raw offset."""
    query = {"statuses": None}
    cursor = encode_cursor(SCOPE_A, query, {"offset": 2})

    assert "offset" not in cursor and "2" not in cursor.strip("=")[:4]
    assert decode_cursor(cursor, SCOPE_A, query) == {"offset": 2}

    with pytest.raises(CursorError, match="not valid for this scope"):
        decode_cursor(cursor, SCOPE_B, query)
    with pytest.raises(CursorError, match="not valid for this scope"):
        decode_cursor(cursor, SCOPE_A, {"statuses": ["active"]})
    with pytest.raises(CursorError, match="malformed"):
        decode_cursor("!!!not-base64!!!", SCOPE_A, query)
    with pytest.raises(CursorError, match="too large"):
        decode_cursor("x" * (Limits.MAX_CURSOR + 1), SCOPE_A, query)

    with pytest.raises(CursorError, match="too large"):
        encode_cursor(SCOPE_A, query, {"blob": "y" * Limits.MAX_CURSOR})


def test_contracts_page_limits_are_bounded() -> None:
    """Page sizes clamp to the hard ceiling and reject non-positive requests."""
    assert bounded_limit(None, default=20) == 20
    assert bounded_limit(5, default=20) == 5
    assert bounded_limit(10_000, default=20) == MAX_PAGE_LIMIT
    assert bounded_limit(None, default=10_000) == MAX_PAGE_LIMIT
    with pytest.raises(CursorError):
        bounded_limit(0, default=20)
    with pytest.raises(CursorError):
        bounded_limit(-1, default=20)


def test_contracts_goal_preview_is_character_truncation() -> None:
    """Preview truncation is on characters — it is display text, not a payload."""
    assert goal_preview("abcdef", chars=3) == "abc"
    assert goal_preview("ab", chars=80) == "ab"


def test_contracts_append_result_reports_noop_and_revision() -> None:
    """``AppendResult`` derives its convenience views from the projection."""
    state = TaskState(task_id="t-1", scope=SCOPE_A, goal="g", revision=4, last_event_seq=9)
    noop = AppendResult(state=state, deduplicated_event_ids=("e1",), last_seq=9)
    assert noop.was_noop and noop.revision == 4 and noop.task_id == "t-1"

    applied = AppendResult(state=state, appended_event_ids=("e2",), first_seq=10, last_seq=10)
    assert not applied.was_noop


def test_contracts_payload_result_never_carries_both() -> None:
    """A payload result is either data or a refusal, never both."""
    ref = EvidenceRef(artifact_id="a", version=1)
    ok = PayloadResult(ref=ref, kind=ArtifactKind.JSON, payload={"n": 1}, returned_bytes=8)
    assert ok.ok and ok.refusal is None

    refused = PayloadResult(ref=ref, kind=ArtifactKind.JSON, refusal=PayloadRefusal.TOO_LARGE, byte_size=999)
    assert not refused.ok and refused.payload is None
    assert refused.byte_size == 999, "a refusal still reports how far over the ceiling it was"


def test_contracts_result_models_are_frozen_and_strict() -> None:
    """Contract return models reject unknown fields and cannot be mutated."""
    from pydantic import ValidationError

    state = TaskState(task_id="t-1", scope=SCOPE_A, goal="g")
    snapshot = TaskSnapshot(state=state, as_of_seq=3, event_count=3)
    with pytest.raises(ValidationError):
        snapshot.as_of_seq = 4  # type: ignore[misc]
    with pytest.raises(ValidationError):
        TaskSnapshot(state=state, as_of_seq=3, surprise=1)  # type: ignore[call-arg]


def test_contracts_task_summary_timestamps_are_utc() -> None:
    """Listing timestamps stay timezone-aware."""
    summary = TaskSummary(task_id="t-1", goal_preview="g", status=TaskStatus.ACTIVE, updated_at=utc_now())
    assert summary.updated_at.tzinfo is not None
    assert summary.updated_at.astimezone(timezone.utc) == summary.updated_at


def test_contracts() -> None:
    """Required aggregate case: conformance fixtures express the storage invariants.

    The behavioural invariants themselves are asserted by the
    :class:`TaskMemoryStoreConformance` and
    :class:`ArtifactStoreConformance` suites, which pytest collects via
    :class:`TestReferenceTaskMemoryStore` and
    :class:`TestReferenceArtifactStore`. This case verifies that the
    published suites actually contain those cases, so a later backend
    cannot "pass conformance" against an empty suite.
    """
    task_cases = {name for name in dir(TaskMemoryStoreConformance) if name.startswith("test_")}
    artifact_cases = {name for name in dir(ArtifactStoreConformance) if name.startswith("test_")}

    assert {
        "test_conformance_scope_isolation",
        "test_conformance_conflict_mutates_nothing",
        "test_conformance_exact_replay_is_a_noop",
        "test_conformance_reused_id_with_different_payload_is_rejected",
        "test_conformance_sequences_are_contiguous",
        "test_conformance_reads_never_append",
        "test_conformance_pagination_is_scoped_and_bounded",
    } <= task_cases

    assert {
        "test_conformance_alias_versions_are_monotonic",
        "test_conformance_overwrite_preserves_older_evidence",
        "test_conformance_alias_namespace_is_task_scoped",
        "test_conformance_version_lookup_requires_scope",
        "test_conformance_byte_ceiling_refusal_carries_no_payload",
        "test_conformance_drop_alias_keeps_versions",
        "test_conformance_invalidate_is_not_deletion",
    } <= artifact_cases

    # And the helpers those cases lean on behave as documented.
    test_contracts_classify_events_separates_replay_from_rewrite()
    test_contracts_cursors_are_opaque_and_bound()
    test_contracts_page_limits_are_bounded()
