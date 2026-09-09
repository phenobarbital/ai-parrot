"""TASK-3003 — durable backend lifecycle and retention scheduling.

Three properties, one per required case:

``test_configured_graph``
    The toolkit, the observer and the plan factory all hold the SAME task
    store and the SAME artifact store. A sibling artifact store is the
    specific defect this guards: writes land in one, evidence is
    validated against the other, and every completion is refused for
    reasons that make no sense from outside.

``test_startup_failure``
    A durable deployment missing its DSN, its migration, its database or
    its blob backend fails at STARTUP, clearly, naming what is absent.
    There is no silent fall back to the in-memory store — that is the
    failure this whole feature exists to prevent, because it looks
    healthy right up until the restart that was supposed to be survived.
    Disabled mode is unaffected.

``test_shutdown``
    Shutdown closes only what the runtime owns, releases owned leases,
    and leaves no periodic task behind — including when it is reached by
    cancellation, which is how shutdown usually arrives.

The migration/database cases run against a real PostgreSQL when
``TASK_MEMORY_TEST_DSN`` is set and skip explicitly otherwise; a skip is
never reported as a pass.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, List, Optional

import pytest

from parrot.tools.working_memory import WorkingMemoryToolkit
from parrot.tools.working_memory.task_memory.config import (
    DurableStartupError,
    TaskMemoryConfig,
    TaskMemoryRuntime,
)
from parrot.tools.working_memory.task_memory.models import TaskScope

pytestmark = pytest.mark.asyncio

DSN_ENV = "TASK_MEMORY_TEST_DSN"
_PG_SKIP = (
    f"{DSN_ENV} is not set. Durable startup checks require a real PostgreSQL; " "this case is SKIPPED, not passed."
)


def _scope() -> TaskScope:
    """Return the canonical test scope.

    Returns:
        The scope.
    """
    return TaskScope(chatbot_id="bot-a", user_id="user-1", session_id="sess-1")


def _dsn_or_skip() -> str:
    """Return the configured DSN or skip explicitly.

    Returns:
        The DSN.
    """
    dsn = os.environ.get(DSN_ENV) or None
    if not dsn:
        pytest.skip(_PG_SKIP)
    return dsn


async def _apply_migration(dsn: str) -> None:
    """Apply the packaged migration so a durable startup can succeed.

    Args:
        dsn: The database to migrate.
    """
    from parrot.tools.working_memory.task_memory.store.postgres import PostgresTaskMemoryStore

    store = PostgresTaskMemoryStore(dsn)
    try:
        await store.apply_migrations()
    finally:
        await store.close()


class _FileManager:
    """A blob backend stand-in; only identity matters for wiring."""

    def __init__(self) -> None:
        """Initialize."""
        self.closed = False

    async def close(self) -> None:
        """Record a close."""
        self.closed = True


# ─────────────────────────────────────────────────────────────
# test_configured_graph
# ─────────────────────────────────────────────────────────────


async def test_configured_graph() -> None:
    """Every consumer shares one task store and one artifact store."""
    runtime = TaskMemoryRuntime(TaskMemoryConfig(enabled=True))
    await runtime.start(start_scheduler=False)
    try:
        scope = _scope()
        toolkit = WorkingMemoryToolkit.from_runtime(runtime, scope)
        tm = toolkit._task_memory

        # The toolkit's composition root points at the runtime's stores,
        # not at copies of them.
        assert tm.store is runtime.store
        assert tm.artifacts is runtime.artifacts

        # The toolkit's own catalog backend is that SAME artifact store —
        # this is the sibling-store check: an `==`-equal but distinct
        # object would still be a second store, so identity is asserted.
        assert toolkit._catalog.backend is runtime.artifacts

        # Recall reads through the same pair.
        assert tm.reader._store is runtime.store
        assert tm.reader._artifacts is runtime.artifacts

        # A second toolkit over the same runtime shares them too, rather
        # than each session quietly getting its own backend.
        other = WorkingMemoryToolkit.from_runtime(runtime, scope)
        assert other._task_memory.store is tm.store
        assert other._task_memory.artifacts is tm.artifacts

        # The service commands the same store it reads from.
        assert tm.service._store is runtime.store

        # Exactly one artifact store exists across everything wired here.
        stores = {id(x) for x in (tm.artifacts, other._task_memory.artifacts, toolkit._catalog.backend)}
        assert len(stores) == 1, "a sibling artifact store appeared"
    finally:
        await runtime.stop()


async def test_configured_graph_durable_shares_one_pool() -> None:
    """The durable artifact store is built over the same task store."""
    dsn = _dsn_or_skip()
    await _apply_migration(dsn)
    fm = _FileManager()
    runtime = TaskMemoryRuntime(TaskMemoryConfig(enabled=True, durable=True, dsn=dsn), file_manager=fm)
    await runtime.start(start_scheduler=False)
    try:
        # PostgresArtifactStore takes the task store itself, so sharing a
        # pool and a transaction coordinator is structural rather than a
        # convention someone has to remember.
        assert runtime.artifacts._tasks is runtime.store
        assert runtime.artifacts._blobs is runtime.blobs
        tm = runtime.task_memory(_scope())
        assert tm.store is runtime.store and tm.artifacts is runtime.artifacts
    finally:
        await runtime.stop()


# ─────────────────────────────────────────────────────────────
# test_startup_failure
# ─────────────────────────────────────────────────────────────


async def test_startup_failure() -> None:
    """Durable prerequisites fail loudly; disabled mode is unaffected."""
    # ── no DSN: refused at configuration time, before anything connects
    with pytest.raises(ValueError) as no_dsn:
        TaskMemoryConfig(enabled=True, durable=True)
    assert "dsn" in str(no_dsn.value).lower()
    # And it explains WHY, rather than just naming the field.
    assert "fall back" in str(no_dsn.value)

    # ── no blob backend: durable storage has nowhere to put payloads
    runtime = TaskMemoryRuntime(TaskMemoryConfig(enabled=True, durable=True, dsn="postgresql://x/y"), file_manager=None)
    with pytest.raises(DurableStartupError) as no_blob:
        await runtime.start()
    assert "file_manager" in str(no_blob.value)
    assert not runtime.is_running
    # Crucially it did NOT quietly build the in-memory graph instead.
    assert runtime.store is None and runtime.artifacts is None

    # ── unreachable database: a startup error, not a first-append error
    unreachable = TaskMemoryRuntime(
        TaskMemoryConfig(enabled=True, durable=True, dsn="postgresql://nobody:nobody@127.0.0.1:1/nonexistent"),
        file_manager=_FileManager(),
    )
    with pytest.raises(DurableStartupError) as unreachable_err:
        await unreachable.start()
    assert "database" in str(unreachable_err.value) or "prerequisites" in str(unreachable_err.value)
    assert unreachable.store is None

    # ── disabled mode is completely unaffected
    disabled = TaskMemoryRuntime(TaskMemoryConfig())
    await disabled.start()
    assert disabled.is_running
    assert disabled.store is None and disabled.artifacts is None and disabled.periodic is None
    await disabled.stop()


async def test_startup_failure_missing_migration_names_the_migration() -> None:
    """An un-migrated schema is reported as such, against a real database."""
    dsn = _dsn_or_skip()
    from parrot.tools.working_memory.task_memory.store.postgres import PostgresTaskMemoryStore

    # A schema that certainly has no migration applied.
    store = PostgresTaskMemoryStore(dsn, schema="tm_3003_unmigrated")
    try:
        pool = await store._acquire_pool()
        async with pool.acquire() as connection:
            await connection.execute("CREATE SCHEMA IF NOT EXISTS tm_3003_unmigrated")
    finally:
        await store.close()

    runtime = TaskMemoryRuntime(TaskMemoryConfig(enabled=True, durable=True, dsn=dsn), file_manager=_FileManager())
    runtime.config = runtime.config.model_copy(update={})
    # Point the runtime's store at the un-migrated schema by building it
    # the same way start() does, then verifying.
    probe = PostgresTaskMemoryStore(dsn, schema="tm_3003_unmigrated", config=runtime.config)
    try:
        from parrot.tools.working_memory.task_memory.models import TaskMemoryUnavailable

        with pytest.raises(TaskMemoryUnavailable) as exc:
            await probe.verify_schema()
        message = str(exc.value)
        # The operator learns what to DO, not merely that something broke.
        assert "migration" in message
        assert "apply_migrations" in message or "run" in message
    finally:
        await probe.close()


# ─────────────────────────────────────────────────────────────
# test_shutdown
# ─────────────────────────────────────────────────────────────


class _Association:
    """Records whether owned leases were released."""

    def __init__(self) -> None:
        """Initialize."""
        self.released = False

    async def release_call(self, *a: Any, **k: Any) -> bool:  # pragma: no cover - shape only
        """Present so the runtime recognises this as a lease holder."""
        return True

    async def release_owned(self) -> None:
        """Record the release."""
        self.released = True


def _task_names() -> List[str]:
    """Return the names of live asyncio tasks.

    Returns:
        Task names.
    """
    return [t.get_name() for t in asyncio.all_tasks() if not t.done()]


async def test_shutdown() -> None:
    """Shutdown closes owned resources, releases leases, leaks no task."""
    association = _Association()
    runtime = TaskMemoryRuntime(
        TaskMemoryConfig(enabled=True, retention_interval_seconds=0.05), association=association
    )
    await runtime.start()

    # The periodic loop is a real, named asyncio task while running.
    assert runtime.periodic is not None and runtime.periodic.is_running
    assert any("task-memory-retention" in n for n in _task_names())

    await runtime.stop()

    # No periodic task survives, and the loop handle is cleared.
    assert runtime.periodic is None
    await asyncio.sleep(0)
    assert not any("task-memory-retention" in n for n in _task_names()), "retention loop leaked"
    # Owned leases were released.
    assert association.released
    assert not runtime.is_running

    # Idempotent: a second stop is a no-op, not an error.
    await runtime.stop()


async def test_shutdown_leaves_borrowed_resources_open() -> None:
    """A borrowed pool survives the borrower's shutdown, and still works.

    Exercised on the DURABLE path deliberately. An earlier version of this
    test borrowed a pool while building the in-memory graph, where no pool
    is used at all — so it asserted "the pool was not closed" about a pool
    nothing could have closed, and passed no matter what the code did.
    """
    dsn = _dsn_or_skip()
    await _apply_migration(dsn)

    import asyncpg

    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    assert pool is not None
    try:
        runtime = TaskMemoryRuntime(
            TaskMemoryConfig(enabled=True, durable=True, dsn=dsn),
            file_manager=_FileManager(),
            pool=pool,
        )
        assert runtime._owns_pool is False
        await runtime.start(start_scheduler=False)
        assert runtime.store._owns_pool is False, "the store must know the pool is borrowed"
        await runtime.stop()

        # The real assertion: the pool is not merely un-flagged, it still
        # WORKS. Tearing down one bot must not disconnect a pool the rest
        # of the application is still using.
        async with pool.acquire() as connection:
            assert await connection.fetchval("SELECT 1") == 1
    finally:
        await pool.close()


async def test_shutdown_closes_a_pool_it_created() -> None:
    """A pool the runtime created IS closed on shutdown."""
    dsn = _dsn_or_skip()
    await _apply_migration(dsn)

    runtime = TaskMemoryRuntime(TaskMemoryConfig(enabled=True, durable=True, dsn=dsn), file_manager=_FileManager())
    await runtime.start(start_scheduler=False)
    store = runtime.store
    assert store._owns_pool is True
    pool = await store._acquire_pool()
    await runtime.stop()

    # The counterpart to the borrowed case: what the runtime created, it
    # cleans up, so a restarted host does not accumulate pools.
    assert pool.is_closing() or pool._closed


async def test_shutdown_survives_cancellation() -> None:
    """A cancelled shutdown still stops the loop rather than leaking it."""
    runtime = TaskMemoryRuntime(TaskMemoryConfig(enabled=True, retention_interval_seconds=0.05))
    await runtime.start()
    assert runtime.periodic is not None and runtime.periodic.is_running

    async def _cancelled_shutdown() -> None:
        """Stop the runtime from inside a task that is then cancelled."""
        await asyncio.shield(runtime.stop())

    task = asyncio.create_task(_cancelled_shutdown())
    await asyncio.sleep(0)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    # The shield is what makes this hold: without it the stop would be
    # abandoned mid-way and the retention loop would outlive the bot.
    await asyncio.sleep(0.05)
    assert not any("task-memory-retention" in n for n in _task_names()), "retention loop survived cancellation"


async def test_shutdown_reports_a_failing_close_without_raising() -> None:
    """One resource failing to close does not skip the others."""

    class _BadStore:
        """A store whose close always fails."""

        async def close(self) -> None:
            raise RuntimeError("connection reset")

    association = _Association()
    runtime = TaskMemoryRuntime(TaskMemoryConfig(enabled=True), association=association)
    await runtime.start(start_scheduler=False)
    runtime.store = _BadStore()

    # Must not raise: shutdown runs from a finally, where an exception
    # would mask whatever actually failed.
    await runtime.stop()
    # And the rest of shutdown still happened.
    assert association.released
    assert not runtime.is_running


# ─────────────────────────────────────────────────────────────
# run_once — the host-scheduler entry point
# ─────────────────────────────────────────────────────────────


async def test_run_once_is_available_without_the_periodic_loop() -> None:
    """A host with its own scheduler can sweep without this loop running."""
    runtime = TaskMemoryRuntime(TaskMemoryConfig(enabled=True))
    await runtime.start(start_scheduler=False)
    try:
        # No in-process loop, and no queue dependency was taken on.
        assert runtime.periodic is None
        runtime.track_scope(_scope())
        report = await runtime.run_once()
        assert report is not None
        # Tracked scopes are swept without being passed again each time.
        assert await runtime.run_once([_scope()]) is not None
    finally:
        await runtime.stop()
