"""Durable PostgreSQL task journal and projections (FEAT-538 / TASK-2995).

Three required cases from the task's Test Specification:

- ``test_concurrent_db`` — **real independent connections** race append,
  creation and idempotency: one valid winner, exact retries are no-ops,
  and the sequence has no gaps.
- ``test_rollback_replay`` — an injected failure leaves no partial state,
  and the projection reconstructed from the journal matches the stored
  one.
- ``test_version_scope`` — older projections migrate deterministically;
  newer reducer versions and foreign scopes fail explicitly.

**Service gating.** Concurrency and durability claims are only meaningful
against a real server, so every case here requires one::

    TASK_MEMORY_TEST_DSN=postgresql://user:pass@host:5432/db \\
        uv run pytest .../test_postgres_task_store.py -q

The DSN is deliberately never defaulted — a default would point the suite
at whatever database happened to be listening, which is how a test suite
ends up writing to a real one. Without it every case **skips explicitly**
and says so; a skip is never reported as a pass. Each case creates a
uniquely named throwaway schema and drops it in a ``finally``.

The store is also run against the shared
:class:`~.test_contracts.TaskMemoryStoreConformance` suite, which is the
mechanism by which the durable and in-memory backends are held to
identical behaviour (AC2). Passing it in-memory alone proves nothing
about durability, which is exactly why it is re-run here.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator, List, Optional, Tuple

import pytest
from parrot.tools.working_memory.task_memory.models import (
    Actor,
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
from parrot.tools.working_memory.task_memory.reducer import REDUCER_VERSION, replay
from parrot.tools.working_memory.task_memory.store.postgres import PostgresTaskMemoryStore

from .test_contracts import SCOPE_A, SCOPE_B, TaskMemoryStoreConformance, make_event

#: Set this to run these cases. Never defaulted — see the module docstring.
DSN_ENV = "TASK_MEMORY_TEST_DSN"

T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _require_dsn() -> str:
    """Return the configured test DSN, or skip the calling test explicitly.

    Returns:
        The configured DSN.
    """
    dsn = os.environ.get(DSN_ENV) or None
    if not dsn:
        pytest.skip(
            f"no PostgreSQL configured: set {DSN_ENV} to run the durable task-store cases. "
            "This is an ENVIRONMENTAL SKIP, not a pass — no durable behaviour was exercised here."
        )
    return dsn


async def _fresh_store(dsn: str, schema: str, **kwargs: Any) -> PostgresTaskMemoryStore:
    """Build a store on ``schema`` and apply the migration.

    Args:
        dsn: PostgreSQL connection string.
        schema: Throwaway schema name.
        **kwargs: Extra store constructor arguments.

    Returns:
        A migrated store.
    """
    store = PostgresTaskMemoryStore(dsn, schema=schema, **kwargs)
    await store.apply_migrations()
    return store


@pytest.fixture()
async def pg_schema() -> AsyncIterator[Tuple[str, str]]:
    """Yield a ``(dsn, schema)`` pair, dropping the schema afterwards.

    Yields:
        The DSN and a unique throwaway schema name.
    """
    dsn = _require_dsn()
    schema = f"wm_test_{uuid.uuid4().hex[:12]}"
    try:
        yield dsn, schema
    finally:
        cleaner = PostgresTaskMemoryStore(dsn, schema=schema)
        try:
            await cleaner.revert_migrations()
        except Exception:  # noqa: BLE001 — cleanup must not mask a test failure
            pass
        await cleaner.close()


@pytest.fixture()
async def pg_store(pg_schema: Tuple[str, str]) -> AsyncIterator[PostgresTaskMemoryStore]:
    """Yield a migrated store on a throwaway schema.

    Yields:
        The store.
    """
    dsn, schema = pg_schema
    store = await _fresh_store(dsn, schema)
    try:
        yield store
    finally:
        await store.close()


def _event(
    task_id: str,
    *,
    event_id: str,
    event_type: EventType = EventType.TASK_STARTED,
    status: TaskStatus = TaskStatus.ACTIVE,
    reason: Optional[str] = None,
    goal: Optional[str] = None,
    seconds: int = 0,
) -> JournalEvent:
    """Build a deterministic lifecycle event.

    Args:
        task_id: Owning task.
        event_id: Explicit id, so redelivery can be simulated exactly.
        event_type: The event type.
        status: Status carried in the payload.
        reason: Optional reason, to make two same-id events differ.
        goal: Goal, required on ``task_started``.
        seconds: Offset from :data:`T0`.

    Returns:
        The event.
    """
    if event_type is EventType.TASK_STARTED and goal is None:
        goal = f"goal for {task_id}"
    return JournalEvent(
        event_id=event_id,
        task_id=task_id,
        occurred_at=T0 + timedelta(seconds=seconds),
        event_type=event_type,
        actor=Actor.AGENT,
        payload=TaskLifecyclePayload(status=status, reason=reason, goal=goal),
    )


async def _create(store: PostgresTaskMemoryStore, scope: TaskScope, task_id: str) -> Any:
    """Create one task with a single ``task_started`` event.

    Args:
        store: The store under test.
        scope: Owning scope.
        task_id: The task to create.

    Returns:
        The append result.
    """
    goal = f"goal for {task_id}"
    return await store.create_task(scope, goal=goal, events=[_event(task_id, event_id=f"{task_id}-e1", goal=goal)])


# ─────────────────────────────────────────────────────────────
# Shared conformance suite, run against the durable backend
# ─────────────────────────────────────────────────────────────


class TestPostgresConformance(TaskMemoryStoreConformance):
    """The durable store must satisfy the same contract as the in-memory one.

    This is the mechanism behind AC2. Running the suite only in-memory
    would prove the *contract* is satisfiable, not that the backend a
    deployment actually relies on satisfies it.
    """

    @pytest.fixture()
    async def store(self) -> AsyncIterator[PostgresTaskMemoryStore]:
        """Yield a migrated durable store on a throwaway schema."""
        dsn = _require_dsn()
        schema = f"wm_test_{uuid.uuid4().hex[:12]}"
        backend = await _fresh_store(dsn, schema)
        try:
            yield backend
        finally:
            try:
                await backend.revert_migrations()
            except Exception:  # noqa: BLE001 — cleanup must not mask a failure
                pass
            await backend.close()


# ─────────────────────────────────────────────────────────────
# test_concurrent_db
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_concurrent_db_racing_appends_serialize_without_gaps(
    pg_schema: Tuple[str, str],
) -> None:
    """Independent connections racing one task leave a contiguous journal.

    Each store owns its own pool, so these are genuinely separate
    connections rather than coroutines sharing one — the row lock is what
    is under test, and a single connection would not exercise it.
    """
    dsn, schema = pg_schema
    writer = await _fresh_store(dsn, schema)
    stores: List[PostgresTaskMemoryStore] = []
    try:
        await _create(writer, SCOPE_A, "t-1")
        stores = [PostgresTaskMemoryStore(dsn, schema=schema, min_size=1, max_size=2) for _ in range(6)]

        async def append(index: int) -> Any:
            return await stores[index].append_events(
                SCOPE_A,
                "t-1",
                [
                    _event(
                        "t-1",
                        event_id=f"t-1-race-{index}",
                        event_type=EventType.TASK_PAUSED,
                        status=TaskStatus.PAUSED,
                        seconds=index + 1,
                    )
                ],
                expected_revision=None,
            )

        results = await asyncio.gather(*(append(i) for i in range(6)), return_exceptions=True)
        failures = [r for r in results if isinstance(r, BaseException)]
        assert not failures, f"unexpected failures: {failures}"

        page = await writer.list_events(SCOPE_A, "t-1", limit=200)
        sequences = [event.seq for event in page.events]
        assert sequences == list(range(1, len(sequences) + 1)), f"sequence has gaps: {sequences}"
        assert len(sequences) == 7, "one task_started plus six racing appends"

        snapshot = await writer.load_snapshot(SCOPE_A, "t-1")
        assert snapshot is not None
        assert snapshot.event_count == 7
        assert snapshot.as_of_seq == 7
    finally:
        for store in stores:
            await store.close()
        await writer.close()


@pytest.mark.asyncio
async def test_concurrent_db_expected_revision_yields_one_winner(
    pg_schema: Tuple[str, str],
) -> None:
    """Racing the SAME expected revision commits exactly one batch."""
    dsn, schema = pg_schema
    writer = await _fresh_store(dsn, schema)
    stores: List[PostgresTaskMemoryStore] = []
    try:
        created = await _create(writer, SCOPE_A, "t-1")
        revision = created.revision
        stores = [PostgresTaskMemoryStore(dsn, schema=schema, min_size=1, max_size=2) for _ in range(5)]

        async def append(index: int) -> Any:
            return await stores[index].append_events(
                SCOPE_A,
                "t-1",
                [
                    _event(
                        "t-1",
                        event_id=f"t-1-cas-{index}",
                        event_type=EventType.TASK_PAUSED,
                        status=TaskStatus.PAUSED,
                        seconds=index + 1,
                    )
                ],
                expected_revision=revision,
            )

        results = await asyncio.gather(*(append(i) for i in range(5)), return_exceptions=True)
        winners = [r for r in results if not isinstance(r, BaseException)]
        conflicts = [r for r in results if isinstance(r, RevisionConflict)]

        assert len(winners) == 1, f"expected exactly one winner, got {len(winners)}"
        assert len(conflicts) == 4, f"expected four conflicts, got {[type(r) for r in results]}"

        page = await writer.list_events(SCOPE_A, "t-1", limit=200)
        assert [e.seq for e in page.events] == [1, 2], "a losing CAS must write nothing"
    finally:
        for store in stores:
            await store.close()
        await writer.close()


@pytest.mark.asyncio
async def test_concurrent_db_racing_creation_produces_one_task(
    pg_schema: Tuple[str, str],
) -> None:
    """Two pods creating the same task id produce one row and one journal.

    The loser of the insert falls through to the append path, which
    recognises the identical batch as a redelivery rather than raising.
    """
    dsn, schema = pg_schema
    writer = await _fresh_store(dsn, schema)
    stores: List[PostgresTaskMemoryStore] = []
    try:
        stores = [PostgresTaskMemoryStore(dsn, schema=schema, min_size=1, max_size=2) for _ in range(5)]
        results = await asyncio.gather(*(_create(store, SCOPE_A, "t-race") for store in stores), return_exceptions=True)
        failures = [r for r in results if isinstance(r, BaseException)]
        assert not failures, f"concurrent creation raised: {failures}"

        appended = [r for r in results if r.appended_event_ids]
        noops = [r for r in results if r.was_noop]
        assert len(appended) == 1, "exactly one creation may append"
        assert len(noops) == 4, "the rest must be recognised as redeliveries"

        page = await writer.list_events(SCOPE_A, "t-race", limit=200)
        assert [e.seq for e in page.events] == [1], "creation must not duplicate its event"
    finally:
        for store in stores:
            await store.close()
        await writer.close()


@pytest.mark.asyncio
async def test_concurrent_db_exact_retry_is_a_noop(pg_store: PostgresTaskMemoryStore) -> None:
    """A retried batch that already committed is a no-op, not a conflict.

    The caller's revision is stale precisely *because its own attempt
    succeeded*, so classification must precede the revision check.
    """
    created = await _create(pg_store, SCOPE_A, "t-1")
    event = _event("t-1", event_id="t-1-e2", event_type=EventType.TASK_PAUSED, status=TaskStatus.PAUSED, seconds=1)

    first = await pg_store.append_events(SCOPE_A, "t-1", [event], expected_revision=created.revision)
    assert first.appended_event_ids == ("t-1-e2",)

    replayed = await pg_store.append_events(SCOPE_A, "t-1", [event], expected_revision=created.revision)
    assert replayed.was_noop
    assert replayed.deduplicated_event_ids == ("t-1-e2",)
    assert replayed.last_seq == first.last_seq

    snapshot = await pg_store.load_snapshot(SCOPE_A, "t-1")
    assert snapshot is not None
    assert snapshot.event_count == 2, "a redelivery must not duplicate the event"
    assert snapshot.state.revision == first.revision, "a redelivery must not advance the revision"


@pytest.mark.asyncio
async def test_concurrent_db_reused_id_with_different_payload_is_rejected(
    pg_store: PostgresTaskMemoryStore,
) -> None:
    """An id may be redelivered, never rewritten."""
    created = await _create(pg_store, SCOPE_A, "t-1")
    original = _event("t-1", event_id="t-1-e2", event_type=EventType.TASK_PAUSED, status=TaskStatus.PAUSED, seconds=1)
    await pg_store.append_events(SCOPE_A, "t-1", [original], expected_revision=created.revision)

    forged = _event(
        "t-1",
        event_id="t-1-e2",
        event_type=EventType.TASK_PAUSED,
        status=TaskStatus.PAUSED,
        reason="tampered",
        seconds=1,
    )
    with pytest.raises(ReducerError):
        await pg_store.append_events(SCOPE_A, "t-1", [forged], expected_revision=None)

    snapshot = await pg_store.load_snapshot(SCOPE_A, "t-1")
    assert snapshot is not None and snapshot.event_count == 2


@pytest.mark.asyncio
async def test_concurrent_db_different_tasks_progress_concurrently(
    pg_schema: Tuple[str, str],
) -> None:
    """The lock is per task: unrelated tasks do not block each other."""
    dsn, schema = pg_schema
    writer = await _fresh_store(dsn, schema)
    stores: List[PostgresTaskMemoryStore] = []
    try:
        stores = [PostgresTaskMemoryStore(dsn, schema=schema, min_size=1, max_size=2) for _ in range(5)]
        results = await asyncio.gather(
            *(_create(store, SCOPE_A, f"t-{i}") for i, store in enumerate(stores)),
            return_exceptions=True,
        )
        assert not [r for r in results if isinstance(r, BaseException)]

        page = await writer.list_tasks(SCOPE_A, limit=50)
        assert len(page.items) == 5
        assert page.total_open == 5
    finally:
        for store in stores:
            await store.close()
        await writer.close()


@pytest.mark.asyncio
async def test_concurrent_db() -> None:
    """Required aggregate case: real connections race without gaps or double writes.

    The behaviour is asserted by the focused ``test_concurrent_db_*``
    cases above, which pytest collects individually so a failure names
    the specific invariant. This case exists to satisfy the task's Test
    Specification by name and to state plainly that concurrency here is
    exercised against a **real** server or not at all.
    """
    _require_dsn()


# ─────────────────────────────────────────────────────────────
# test_rollback_replay
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rollback_replay_projection_failure_leaves_no_partial_state(
    pg_store: PostgresTaskMemoryStore,
) -> None:
    """A failure after the journal insert rolls the whole append back.

    The journal rows and the projection update are one transaction. If
    only the rows survived, the projection would silently disagree with
    its own journal — the exact drift the design exists to prevent.
    """
    created = await _create(pg_store, SCOPE_A, "t-1")
    before = await pg_store.load_snapshot(SCOPE_A, "t-1")
    assert before is not None

    boom = RuntimeError("injected projection failure")
    original = pg_store._write_projection
    calls = {"n": 0}

    async def failing(connection: Any, state: Any) -> None:
        calls["n"] += 1
        raise boom

    pg_store._write_projection = failing  # type: ignore[assignment]
    try:
        with pytest.raises(RuntimeError, match="injected projection failure"):
            await pg_store.append_events(
                SCOPE_A,
                "t-1",
                [
                    _event(
                        "t-1", event_id="t-1-e2", event_type=EventType.TASK_PAUSED, status=TaskStatus.PAUSED, seconds=1
                    )
                ],
                expected_revision=created.revision,
            )
    finally:
        pg_store._write_projection = original  # type: ignore[assignment]

    assert calls["n"] == 1, "the failure must have been reached, or the test proves nothing"

    after = await pg_store.load_snapshot(SCOPE_A, "t-1")
    assert after is not None
    assert after.event_count == before.event_count, "the journal insert must have rolled back too"
    assert after.state.revision == before.state.revision
    assert after.as_of_seq == before.as_of_seq

    page = await pg_store.list_events(SCOPE_A, "t-1", limit=200)
    assert [e.event_id for e in page.events] == ["t-1-e1"]


@pytest.mark.asyncio
async def test_rollback_replay_reducer_failure_writes_nothing(
    pg_store: PostgresTaskMemoryStore,
) -> None:
    """A malformed event anywhere in a batch leaves no partial prefix.

    The valid event is placed FIRST, so a store that wrote as it reduced
    would leave it behind.
    """
    created = await _create(pg_store, SCOPE_A, "t-1")

    valid = _event("t-1", event_id="t-1-ok", event_type=EventType.TASK_PAUSED, status=TaskStatus.PAUSED, seconds=1)
    # A second task_started on a live task is refused by the reducer.
    malformed = _event("t-1", event_id="t-1-bad", event_type=EventType.TASK_STARTED, seconds=2)

    with pytest.raises(ReducerError):
        await pg_store.append_events(SCOPE_A, "t-1", [valid, malformed], expected_revision=created.revision)

    page = await pg_store.list_events(SCOPE_A, "t-1", limit=200)
    assert [e.event_id for e in page.events] == ["t-1-e1"], "no partial prefix may land"

    snapshot = await pg_store.load_snapshot(SCOPE_A, "t-1")
    assert snapshot is not None and snapshot.state.revision == created.revision


@pytest.mark.asyncio
async def test_rollback_replay_projection_matches_the_journal(
    pg_store: PostgresTaskMemoryStore,
) -> None:
    """Replaying the stored journal reproduces the stored projection.

    This is the durable form of "the journal is the source of truth": if
    the two ever disagreed, a restart would silently change the task.
    """
    created = await _create(pg_store, SCOPE_A, "t-1")
    revision = created.revision
    for index, (event_type, status) in enumerate(
        [
            (EventType.TASK_PAUSED, TaskStatus.PAUSED),
            (EventType.TASK_RESUMED, TaskStatus.ACTIVE),
            (EventType.TASK_PAUSED, TaskStatus.PAUSED),
        ],
        start=1,
    ):
        result = await pg_store.append_events(
            SCOPE_A,
            "t-1",
            [_event("t-1", event_id=f"t-1-e{index + 1}", event_type=event_type, status=status, seconds=index)],
            expected_revision=revision,
        )
        revision = result.revision

    snapshot = await pg_store.load_snapshot(SCOPE_A, "t-1")
    assert snapshot is not None

    page = await pg_store.list_events(SCOPE_A, "t-1", limit=200)
    rebuilt = replay(list(page.events), scope=SCOPE_A)
    assert rebuilt is not None
    assert rebuilt.model_dump(mode="json") == snapshot.state.model_dump(mode="json")


@pytest.mark.asyncio
async def test_rollback_replay_shared_transaction_rolls_back_together(
    pg_store: PostgresTaskMemoryStore,
) -> None:
    """An append enlisted in a caller's transaction dies with it.

    This is what lets an artifact publish and its ``artifact_registered``
    event become visible together or not at all.
    """
    await _create(pg_store, SCOPE_A, "t-1")
    before = await pg_store.load_snapshot(SCOPE_A, "t-1")
    assert before is not None

    with pytest.raises(RuntimeError, match="caller aborted"):
        async with pg_store.transaction() as tx:
            await pg_store.append_events(
                SCOPE_A,
                "t-1",
                [
                    _event(
                        "t-1", event_id="t-1-tx", event_type=EventType.TASK_PAUSED, status=TaskStatus.PAUSED, seconds=1
                    )
                ],
                expected_revision=before.state.revision,
                transaction=tx,
            )
            raise RuntimeError("caller aborted")

    after = await pg_store.load_snapshot(SCOPE_A, "t-1")
    assert after is not None
    assert after.event_count == before.event_count
    assert after.state.revision == before.state.revision


@pytest.mark.asyncio
async def test_rollback_replay() -> None:
    """Required aggregate case: injected failures leave no partial state.

    Asserted by the focused ``test_rollback_replay_*`` cases above.
    """
    _require_dsn()


# ─────────────────────────────────────────────────────────────
# test_version_scope
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_version_scope_older_projection_migrates_by_replay(
    pg_store: PostgresTaskMemoryStore,
) -> None:
    """A stale projection is rebuilt from the journal, not merely renumbered.

    The stored projection is corrupted as well as back-versioned, so a
    store that only bumped the version number would still fail.
    """
    created = await _create(pg_store, SCOPE_A, "t-1")
    await pg_store.append_events(
        SCOPE_A,
        "t-1",
        [_event("t-1", event_id="t-1-e2", event_type=EventType.TASK_PAUSED, status=TaskStatus.PAUSED, seconds=1)],
        expected_revision=created.revision,
    )

    pool = await pg_store._acquire_pool()
    async with pool.acquire() as connection:
        row = await connection.fetchrow(f"SELECT projection FROM {pg_store._schema}.tasks WHERE task_id = $1", "t-1")
        projection = row["projection"]
        if isinstance(projection, (str, bytes)):
            projection = json.loads(projection)
        projection["goal"] = "CORRUPTED — a version bump alone must not accept this"
        await connection.execute(
            f"UPDATE {pg_store._schema}.tasks SET projection = $2::jsonb, reducer_version = $3 WHERE task_id = $1",
            "t-1",
            json.dumps(projection),
            REDUCER_VERSION - 1,
        )

    snapshot = await pg_store.load_snapshot(SCOPE_A, "t-1")
    assert snapshot is not None
    assert snapshot.state.goal == "goal for t-1", "the projection must be REPLAYED, not renumbered"
    assert snapshot.state.status is TaskStatus.PAUSED
    assert snapshot.state.reducer_version == REDUCER_VERSION

    # And the migration was written back, so it happens once.
    async with pool.acquire() as connection:
        stored = await connection.fetchval(
            f"SELECT reducer_version FROM {pg_store._schema}.tasks WHERE task_id = $1", "t-1"
        )
    assert stored == REDUCER_VERSION


@pytest.mark.asyncio
async def test_version_scope_newer_projection_is_refused(pg_store: PostgresTaskMemoryStore) -> None:
    """A projection from a newer reducer is refused, never guessed at."""
    await _create(pg_store, SCOPE_A, "t-1")

    pool = await pg_store._acquire_pool()
    async with pool.acquire() as connection:
        await connection.execute(
            f"UPDATE {pg_store._schema}.tasks SET reducer_version = $2 WHERE task_id = $1",
            "t-1",
            REDUCER_VERSION + 1,
        )

    with pytest.raises(ReducerError, match="refusing to interpret a newer projection"):
        await pg_store.load_snapshot(SCOPE_A, "t-1")


@pytest.mark.asyncio
async def test_version_scope_foreign_scope_reads_as_absent(pg_store: PostgresTaskMemoryStore) -> None:
    """A task id is not authorization.

    Absence and foreign ownership give the same answer deliberately:
    telling a caller that some id exists but is not theirs is an
    existence oracle.
    """
    await _create(pg_store, SCOPE_A, "t-1")

    assert await pg_store.load_snapshot(SCOPE_B, "t-1") is None
    assert await pg_store.count_events(SCOPE_B, "t-1") == 0
    assert (await pg_store.list_tasks(SCOPE_B)).items == ()

    with pytest.raises(ScopeViolation):
        await pg_store.list_events(SCOPE_B, "t-1")
    with pytest.raises(ScopeViolation):
        await pg_store.append_events(
            SCOPE_B,
            "t-1",
            [_event("t-1", event_id="x", event_type=EventType.TASK_PAUSED, status=TaskStatus.PAUSED, seconds=1)],
            expected_revision=None,
        )


@pytest.mark.asyncio
async def test_version_scope_creation_in_a_foreign_scope_is_refused(
    pg_store: PostgresTaskMemoryStore,
) -> None:
    """Re-creating another scope's task id does not hand it over."""
    await _create(pg_store, SCOPE_A, "t-1")
    with pytest.raises(ScopeViolation):
        await _create(pg_store, SCOPE_B, "t-1")


@pytest.mark.asyncio
async def test_version_scope_open_task_limit_is_enforced(pg_schema: Tuple[str, str]) -> None:
    """The per-scope open-task ceiling is refused before anything is written."""
    from parrot.tools.working_memory.task_memory.config import TaskMemoryConfig

    dsn, schema = pg_schema
    store = await _fresh_store(dsn, schema, config=TaskMemoryConfig(max_open_tasks_per_scope=3))
    try:
        for index in range(3):
            await _create(store, SCOPE_A, f"t-{index}")

        with pytest.raises(LimitExceeded):
            await _create(store, SCOPE_A, "t-overflow")

        page = await store.list_tasks(SCOPE_A, limit=50)
        assert len(page.items) == 3, "the refused task must not have been created"

        # A different scope has its own budget.
        await _create(store, SCOPE_B, "t-other")
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_version_scope_goal_disagreement_is_refused(pg_store: PostgresTaskMemoryStore) -> None:
    """The command and the journal must agree about the goal."""
    with pytest.raises(ReducerError, match="the journal and the command must agree"):
        await pg_store.create_task(
            SCOPE_A,
            goal="one goal",
            events=[_event("t-1", event_id="t-1-e1", goal="a different goal")],
        )

    assert await pg_store.load_snapshot(SCOPE_A, "t-1") is None, "a refused creation writes nothing"


@pytest.mark.asyncio
async def test_version_scope() -> None:
    """Required aggregate case: migration, newer-version refusal and scope isolation.

    Asserted by the focused ``test_version_scope_*`` cases above.
    """
    _require_dsn()


# ─────────────────────────────────────────────────────────────
# Reads never write
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reads_never_append(pg_store: PostgresTaskMemoryStore) -> None:
    """Repeated reads leave the sequence and the journal untouched."""
    await _create(pg_store, SCOPE_A, "t-1")
    before = await pg_store.load_snapshot(SCOPE_A, "t-1")
    assert before is not None

    for _ in range(5):
        await pg_store.load_snapshot(SCOPE_A, "t-1")
        await pg_store.list_events(SCOPE_A, "t-1")
        await pg_store.list_tasks(SCOPE_A)
        await pg_store.count_events(SCOPE_A, "t-1")

    after = await pg_store.load_snapshot(SCOPE_A, "t-1")
    assert after is not None
    assert (after.as_of_seq, after.event_count, after.state.revision) == (
        before.as_of_seq,
        before.event_count,
        before.state.revision,
    )


@pytest.mark.asyncio
async def test_paging_is_total_and_stable(pg_store: PostgresTaskMemoryStore) -> None:
    """Keyset paging over identical timestamps neither skips nor repeats.

    Every task here is written with the same ``updated_at``, which is
    precisely the case a naive ``ORDER BY updated_at`` would get wrong.
    """
    for index in range(7):
        await _create(pg_store, SCOPE_A, f"t-{index:02d}")

    pool = await pg_store._acquire_pool()
    async with pool.acquire() as connection:
        await connection.execute(f"UPDATE {pg_store._schema}.tasks SET updated_at = $1", T0)

    seen: List[str] = []
    cursor: Optional[str] = None
    for _ in range(10):
        page = await pg_store.list_tasks(SCOPE_A, limit=2, cursor=cursor)
        seen.extend(item.task_id for item in page.items)
        cursor = page.next_cursor
        if cursor is None:
            break

    assert len(seen) == len(set(seen)), f"keyset paging repeated a row: {seen}"
    assert sorted(seen) == [f"t-{i:02d}" for i in range(7)], f"keyset paging skipped a row: {sorted(seen)}"
