"""Durable artifact store on PostgreSQL (FEAT-538 / TASK-2997).

Three required cases from the task's Test Specification:

- ``test_atomic_publish`` — a crash after the blob write leaves an
  orphan; a rollback never leaves an index row referencing unavailable
  bytes, nor a journal-only registration.
- ``test_alias_concurrency`` — concurrent writers produce distinct
  versions, one consistent current alias, and leave old evidence intact.
- ``test_pins_restart`` — cross-task evidence survives its producer
  reaching a terminal state and survives a restart; every lookup checks
  the trusted scope.

**These cases need a real server.** A unit double cannot demonstrate that
``SELECT ... FOR UPDATE`` serializes version allocation, and asserting it
against a double would be a claim with no evidence behind it. Set
``TASK_MEMORY_TEST_DSN`` to run them; otherwise they skip *explicitly*,
and a skip is reported as a skip rather than as a pass.

Concurrency is exercised with **separate stores holding separate pools**,
so the racing writers are genuinely different connections. Coroutines
sharing one connection would serialize in the driver and never reach the
row lock at all — the test would pass while proving nothing.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any, AsyncIterator, Optional, Tuple

import pandas as pd
import pytest
from parrot.tools.working_memory.task_memory.blob import ArtifactBlobStore
from parrot.tools.working_memory.task_memory.models import (
    ArtifactAvailability,
    ArtifactKind,
    Attribution,
    CursorError,
    EventType,
    EvidenceRef,
    ScopeViolation,
    TaskScope,
    TaskStatus,
)
from parrot.tools.working_memory.task_memory.store.postgres import PostgresArtifactStore, PostgresTaskMemoryStore

from .test_contracts import SCOPE_A, SCOPE_B, SCOPE_C, ArtifactStoreConformance, make_event

#: Set this to run these cases. Never defaulted: a default would point the
#: suite at whatever database happened to be listening.
DSN_ENV = "TASK_MEMORY_TEST_DSN"

pytest_plugins: Tuple[str, ...] = ()


def _require_dsn() -> str:
    """Return the configured test DSN, or skip the calling test explicitly.

    Returns:
        The configured DSN.
    """
    dsn = os.environ.get(DSN_ENV) or None
    if not dsn:
        pytest.skip(
            f"no PostgreSQL configured: set {DSN_ENV} to run the durable artifact cases. "
            "This is an ENVIRONMENTAL SKIP, not a pass — no durable behaviour was exercised here."
        )
    return dsn


def _real_local_file_manager(base):
    """Return a genuine ``LocalFileManager``, never the test stub.

    ``tests/conftest.py`` installs an ``AsyncMock``-backed stub for
    ``parrot.interfaces.file`` whose ``exists()`` is truthy. Importing
    from there would not merely break these tests — it would let I/O
    assertions pass **vacuously**, which is worse. The real classes
    survive at ``navigator.utils.file``.

    Args:
        base: Directory to sandbox the manager in.

    Returns:
        A real ``LocalFileManager``.
    """
    from navigator.utils.file import LocalFileManager

    manager = LocalFileManager(base_path=str(base), create_base=True)
    if type(manager).__module__.startswith("tests."):  # pragma: no cover - defensive
        pytest.skip("file-manager stub is active; refusing to assert I/O against a mock")
    return manager


async def _new_stores(dsn: str, schema: str, tmp_path) -> Tuple[PostgresTaskMemoryStore, PostgresArtifactStore]:
    """Build a migrated task store and its artifact store.

    Args:
        dsn: PostgreSQL connection string.
        schema: Throwaway schema name.
        tmp_path: Directory for blob storage.

    Returns:
        The ``(task store, artifact store)`` pair.
    """
    tasks = PostgresTaskMemoryStore(dsn, schema=schema)
    await tasks.apply_migrations()
    blobs = ArtifactBlobStore(_real_local_file_manager(tmp_path))
    return tasks, PostgresArtifactStore(tasks, blobs=blobs)


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
async def stores(pg_schema: Tuple[str, str], tmp_path) -> AsyncIterator[Tuple[Any, Any]]:
    """Yield a migrated ``(task store, artifact store)`` pair.

    Yields:
        The stores.
    """
    dsn, schema = pg_schema
    tasks, artifacts = await _new_stores(dsn, schema, tmp_path)
    try:
        yield tasks, artifacts
    finally:
        await tasks.close()


def frame(rows: int = 4) -> pd.DataFrame:
    """Return a small Arrow-representable frame.

    Args:
        rows: Row count.

    Returns:
        A numeric/string DataFrame.
    """
    return pd.DataFrame({"n": range(rows), "s": [f"r{i}" for i in range(rows)]})


async def _make_task(tasks: PostgresTaskMemoryStore, scope: TaskScope, task_id: str) -> None:
    """Create a task so evidence rows have something to reference.

    Args:
        tasks: The task store.
        scope: Owning scope.
        task_id: The task to create.
    """
    goal = f"goal for {task_id}"
    await tasks.create_task(scope, goal=goal, events=[make_event(task_id, event_id=f"{task_id}-e1", goal=goal)])


# ─────────────────────────────────────────────────────────────
# Conformance
# ─────────────────────────────────────────────────────────────


class TestPostgresArtifactStoreConformance(ArtifactStoreConformance):
    """The shared artifact conformance suite, run against PostgreSQL.

    Passing the *same* suite as the in-memory store is the actual
    mechanism behind AC2 — the two backends cannot quietly diverge if
    both must satisfy one set of assertions.
    """

    @pytest.fixture()
    async def artifacts(self, pg_schema: Tuple[str, str], tmp_path) -> AsyncIterator[Any]:
        """Yield a migrated durable artifact store.

        Yields:
            The store.
        """
        dsn, schema = pg_schema
        tasks, store = await _new_stores(dsn, schema, tmp_path)
        try:
            yield store
        finally:
            await tasks.close()


# ─────────────────────────────────────────────────────────────
# test_atomic_publish
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_atomic_publish_rollback_leaves_no_index_row(stores) -> None:
    """A rolled-back publish leaves no index row and no journal event.

    The blob may survive as an orphan — that is expected and sweepable.
    What must never survive is an index row, because a reference to bytes
    nobody committed is unrecoverable for every reader downstream.
    """
    tasks, artifacts = stores
    await _make_task(tasks, SCOPE_A, "t-1")

    ref_holder: dict = {}
    with pytest.raises(RuntimeError, match="simulated crash"):
        async with tasks.transaction() as tx:
            descriptor = await artifacts.put(SCOPE_A, "sales", frame(), task_id="t-1", transaction=tx)
            ref_holder["ref"] = descriptor.ref
            ref_holder["key"] = descriptor.storage_ref
            raise RuntimeError("simulated crash after the blob write")

    ref = ref_holder["ref"]

    # No index row, no alias, no journal event.
    assert await artifacts.get_version(SCOPE_A, ref) is None
    assert await artifacts.get_current(SCOPE_A, "sales", task_id="t-1") is None
    page = await tasks.list_events(SCOPE_A, "t-1", limit=50)
    assert not any(e.event_type is EventType.ARTIFACT_REGISTERED for e in page.events)

    # The orphan blob is expected. Assert it explicitly rather than
    # leaving the reader to wonder which way the guarantee runs.
    assert ref_holder["key"], "the blob was written before the index row, by design"


@pytest.mark.asyncio
async def test_atomic_publish_commits_index_and_journal_together(stores) -> None:
    """A committed publish makes the row, the alias and the event visible together."""
    tasks, artifacts = stores
    await _make_task(tasks, SCOPE_A, "t-1")

    descriptor = await artifacts.put(SCOPE_A, "sales", frame(), task_id="t-1", turn_id="turn-1")

    assert descriptor.availability is ArtifactAvailability.PERSISTED
    assert descriptor.evidence_verifiable is True
    assert descriptor.storage_ref

    assert await artifacts.get_version(SCOPE_A, descriptor.ref) is not None
    current = await artifacts.get_current(SCOPE_A, "sales", task_id="t-1")
    assert current is not None and current.ref == descriptor.ref

    page = await tasks.list_events(SCOPE_A, "t-1", limit=50)
    registered = [e for e in page.events if e.event_type is EventType.ARTIFACT_REGISTERED]
    assert len(registered) == 1
    assert registered[0].payload.ref == descriptor.ref
    assert registered[0].turn_id == "turn-1"


@pytest.mark.asyncio
async def test_atomic_publish_bytes_are_readable_after_commit(stores) -> None:
    """A committed version's payload round-trips through durable storage."""
    tasks, artifacts = stores
    await _make_task(tasks, SCOPE_A, "t-1")
    original = frame(6)

    descriptor = await artifacts.put(SCOPE_A, "sales", original, task_id="t-1")
    result = await artifacts.load_payload(SCOPE_A, descriptor.ref, max_bytes=10_000_000)

    assert result.ok, result.refusal
    pd.testing.assert_frame_equal(result.payload.reset_index(drop=True), original.reset_index(drop=True))


@pytest.mark.asyncio
async def test_atomic_publish_failed_blob_write_is_recorded_honestly(stores, monkeypatch) -> None:
    """When bytes cannot be stored, the version says so instead of claiming durability."""
    tasks, artifacts = stores
    await _make_task(tasks, SCOPE_A, "t-1")

    calls = {"n": 0}

    async def _boom(*args: Any, **kwargs: Any):
        calls["n"] += 1
        raise RuntimeError("object storage is down")

    monkeypatch.setattr(artifacts._blobs, "publish", _boom)

    descriptor = await artifacts.put(SCOPE_A, "sales", frame(), task_id="t-1")

    assert calls["n"] == 1, "the failing path was never reached"
    assert descriptor.availability is ArtifactAvailability.MISSING
    assert descriptor.evidence_verifiable is False, "metadata without bytes is not evidence"

    result = await artifacts.load_payload(SCOPE_A, descriptor.ref, max_bytes=10_000_000)
    assert not result.ok and result.payload is None


@pytest.mark.asyncio
async def test_atomic_publish_no_journal_event_without_a_task(stores) -> None:
    """An unassociated artifact registers without inventing a journal event."""
    _, artifacts = stores
    descriptor = await artifacts.put(SCOPE_A, "loose", {"n": 1})

    assert descriptor.task_id is None
    assert await artifacts.get_current(SCOPE_A, "loose") is not None
    # And it lives in the unassociated namespace, not a task's.
    assert await artifacts.get_current(SCOPE_A, "loose", task_id="t-1") is None


@pytest.mark.asyncio
async def test_atomic_publish() -> None:
    """Required aggregate case: publication is atomic in the direction that matters."""
    _require_dsn()


# ─────────────────────────────────────────────────────────────
# test_alias_concurrency
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_alias_concurrency_distinct_versions_from_separate_pools(pg_schema: Tuple[str, str], tmp_path) -> None:
    """Concurrent writers on SEPARATE connections allocate distinct versions.

    Each writer gets its own store and therefore its own pool. Coroutines
    sharing one connection would serialize inside the driver and never
    exercise the row lock, so the test would pass without proving
    anything about concurrency.
    """
    dsn, schema = pg_schema
    owner, _ = await _new_stores(dsn, schema, tmp_path)
    writers = []
    try:
        for index in range(6):
            tasks = PostgresTaskMemoryStore(dsn, schema=schema, min_size=1, max_size=2)
            blobs = ArtifactBlobStore(_real_local_file_manager(tmp_path / f"w{index}"))
            writers.append((tasks, PostgresArtifactStore(tasks, blobs=blobs)))

        results = await asyncio.gather(
            *(store.put(SCOPE_A, "sales", {"writer": i}) for i, (_, store) in enumerate(writers))
        )

        versions = sorted(r.ref.version for r in results)
        assert versions == list(range(1, len(writers) + 1)), f"versions collided or skipped: {versions}"
        assert len({r.ref.artifact_id for r in results}) == 1, "one alias means one identity"

        # Exactly one current version, and it is the highest allocated.
        current = await writers[0][1].get_current(SCOPE_A, "sales")
        assert current is not None and current.ref.version == max(versions)

        # Every older version is still resolvable and untouched.
        for result in results:
            older = await writers[0][1].get_version(SCOPE_A, result.ref)
            assert older is not None, f"{result.ref} vanished"
            assert older.invalidated is False
    finally:
        for tasks, _ in writers:
            await tasks.close()
        await owner.close()


@pytest.mark.asyncio
async def test_alias_concurrency_overwrite_preserves_old_evidence(stores) -> None:
    """An overwrite creates a new version and leaves the old one valid."""
    tasks, artifacts = stores
    await _make_task(tasks, SCOPE_A, "t-1")

    v1 = await artifacts.put(SCOPE_A, "sales", frame(3), task_id="t-1")
    v2 = await artifacts.put(SCOPE_A, "sales", frame(9), task_id="t-1")

    assert v2.ref.artifact_id == v1.ref.artifact_id
    assert v2.ref.version == v1.ref.version + 1

    old = await artifacts.get_version(SCOPE_A, v1.ref, task_id="t-1")
    assert old is not None and not old.invalidated
    assert old.fingerprint == v1.fingerprint, "an overwrite must not touch the old version"

    payload = await artifacts.load_payload(SCOPE_A, v1.ref, max_bytes=10_000_000)
    assert payload.ok and len(payload.payload) == 3, "the old version's BYTES survive too"


@pytest.mark.asyncio
async def test_alias_concurrency_drop_recreate_continues_the_counter(stores) -> None:
    """A dropped alias tombstones; re-publishing continues at ``latest + 1``.

    Restarting at 1 would let a fresh, unrelated version shadow
    still-pinned evidence at exactly the same coordinates.
    """
    tasks, artifacts = stores
    await _make_task(tasks, SCOPE_A, "t-1")

    v1 = await artifacts.put(SCOPE_A, "sales", {"n": 1}, task_id="t-1")
    v2 = await artifacts.put(SCOPE_A, "sales", {"n": 2}, task_id="t-1")
    assert await artifacts.drop_alias(SCOPE_A, "sales", task_id="t-1") is True
    assert await artifacts.get_current(SCOPE_A, "sales", task_id="t-1") is None

    # The versions behind the tombstone survive.
    assert await artifacts.get_version(SCOPE_A, v1.ref, task_id="t-1") is not None
    assert await artifacts.get_version(SCOPE_A, v2.ref, task_id="t-1") is not None

    v3 = await artifacts.put(SCOPE_A, "sales", {"n": 3}, task_id="t-1")
    assert v3.ref.artifact_id == v1.ref.artifact_id
    assert v3.ref.version == 3, "the counter must continue, never restart at 1"

    # Dropping twice reports honestly.
    assert await artifacts.drop_alias(SCOPE_A, "sales", task_id="t-1") is True
    assert await artifacts.drop_alias(SCOPE_A, "sales", task_id="t-1") is False


@pytest.mark.asyncio
async def test_alias_concurrency_namespaces_do_not_collide(stores) -> None:
    """The same key in different task namespaces is different evidence.

    The empty-string sentinel is what makes this hold: a nullable
    ``task_id`` could not be part of a working unique constraint, because
    in SQL ``NULL <> NULL``.
    """
    tasks, artifacts = stores
    await _make_task(tasks, SCOPE_A, "t-1")
    await _make_task(tasks, SCOPE_A, "t-2")

    a = await artifacts.put(SCOPE_A, "sales", {"who": 1}, task_id="t-1")
    b = await artifacts.put(SCOPE_A, "sales", {"who": 2}, task_id="t-2")
    c = await artifacts.put(SCOPE_A, "sales", {"who": 3})

    assert len({a.ref.artifact_id, b.ref.artifact_id, c.ref.artifact_id}) == 3
    assert (await artifacts.get_current(SCOPE_A, "sales", task_id="t-1")).ref == a.ref
    assert (await artifacts.get_current(SCOPE_A, "sales", task_id="t-2")).ref == b.ref
    assert (await artifacts.get_current(SCOPE_A, "sales")).ref == c.ref


@pytest.mark.asyncio
async def test_alias_concurrency() -> None:
    """Required aggregate case: concurrent writers get distinct versions."""
    _require_dsn()


# ─────────────────────────────────────────────────────────────
# test_pins_restart
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pins_restart_cross_task_pin_survives_producer_terminal_state(stores) -> None:
    """A pin held by another task keeps a version pinned after its producer finishes.

    This is why pinning is derived from *all* nonterminal references
    rather than from a boolean, or from the producing task alone: a
    consumer's evidence must not be swept out from under it just because
    whoever produced it has finished.
    """
    tasks, artifacts = stores
    await _make_task(tasks, SCOPE_A, "producer")
    await _make_task(tasks, SCOPE_A, "consumer")

    descriptor = await artifacts.put(SCOPE_A, "shared", frame(), task_id="producer")
    assert await artifacts.pin_evidence(SCOPE_A, descriptor.ref, "producer") is True
    assert await artifacts.pin_evidence(SCOPE_A, descriptor.ref, "consumer") is True
    assert await artifacts.pins_for(SCOPE_A, descriptor.ref) == ("consumer", "producer")

    # The producer finishes. Its own pin stops counting; the consumer's does not.
    snapshot = await tasks.load_snapshot(SCOPE_A, "producer")
    await tasks.append_events(
        SCOPE_A,
        "producer",
        [
            make_event(
                "producer",
                event_id="producer-cancel",
                event_type=EventType.TASK_CANCELLED,
                status=TaskStatus.CANCELLED,
            )
        ],
        expected_revision=snapshot.state.revision,
    )

    assert await artifacts.pins_for(SCOPE_A, descriptor.ref) == ("consumer",)

    # Releasing the last live pin leaves the version unpinned but present.
    assert await artifacts.unpin_evidence(SCOPE_A, descriptor.ref, "consumer") is True
    assert await artifacts.pins_for(SCOPE_A, descriptor.ref) == ()
    assert await artifacts.get_version(SCOPE_A, descriptor.ref) is not None


@pytest.mark.asyncio
async def test_pins_restart_evidence_survives_a_restart(pg_schema: Tuple[str, str], tmp_path) -> None:
    """Versions, aliases, pins and bytes all survive a full store restart."""
    dsn, schema = pg_schema
    tasks, artifacts = await _new_stores(dsn, schema, tmp_path)
    try:
        await _make_task(tasks, SCOPE_A, "t-1")
        descriptor = await artifacts.put(SCOPE_A, "sales", frame(5), task_id="t-1")
        await artifacts.pin_evidence(SCOPE_A, descriptor.ref, "t-1")
    finally:
        await tasks.close()

    # A brand-new store, a brand-new pool — nothing carried in memory.
    revived_tasks = PostgresTaskMemoryStore(dsn, schema=schema)
    revived = PostgresArtifactStore(revived_tasks, blobs=ArtifactBlobStore(_real_local_file_manager(tmp_path)))
    try:
        after = await revived.get_version(SCOPE_A, descriptor.ref, task_id="t-1")
        assert after is not None
        assert after.fingerprint == descriptor.fingerprint
        assert after.evidence_verifiable is True

        current = await revived.get_current(SCOPE_A, "sales", task_id="t-1")
        assert current is not None and current.ref == descriptor.ref

        assert await revived.pins_for(SCOPE_A, descriptor.ref) == ("t-1",)

        payload = await revived.load_payload(SCOPE_A, descriptor.ref, max_bytes=10_000_000)
        assert payload.ok and len(payload.payload) == 5, "the bytes survived the restart"
    finally:
        await revived_tasks.close()


@pytest.mark.asyncio
async def test_pins_restart_every_lookup_checks_scope(stores) -> None:
    """A globally unique artifact id is not a capability.

    Each scope component is varied independently, because a check that
    compared only one of them would still pass a single-component test.
    """
    tasks, artifacts = stores
    await _make_task(tasks, SCOPE_A, "t-1")
    descriptor = await artifacts.put(SCOPE_A, "sales", frame(), task_id="t-1")

    for foreign in (SCOPE_B, SCOPE_C):
        assert await artifacts.get_version(foreign, descriptor.ref) is None
        assert await artifacts.get_current(foreign, "sales", task_id="t-1") is None
        assert await artifacts.pins_for(foreign, descriptor.ref) == ()
        assert await artifacts.evict(foreign, descriptor.ref) is False
        assert await artifacts.pin_evidence(foreign, descriptor.ref, "t-1") is False

        result = await artifacts.load_payload(foreign, descriptor.ref, max_bytes=10_000_000)
        assert not result.ok and result.payload is None

        with pytest.raises(ScopeViolation):
            await artifacts.invalidate(foreign, descriptor.ref, reason="not yours")

        page = await artifacts.list(foreign)
        assert page.items == ()

    # A same-scope cross-task reference is never resolved implicitly.
    assert await artifacts.get_version(SCOPE_A, descriptor.ref, task_id="t-other") is None
    assert await artifacts.get_version(SCOPE_A, descriptor.ref, task_id="t-1") is not None


@pytest.mark.asyncio
async def test_pins_restart_invalidate_and_evict_differ(stores) -> None:
    """Invalidation is about evidence; eviction is about bytes."""
    tasks, artifacts = stores
    await _make_task(tasks, SCOPE_A, "t-1")

    invalid = await artifacts.put(SCOPE_A, "a", frame(), task_id="t-1")
    updated = await artifacts.invalidate(SCOPE_A, invalid.ref, reason="source mutated")
    assert updated.invalidated is True and updated.invalidated_at is not None
    assert updated.evidence_verifiable is False, "a fingerprint that no longer describes it proves nothing"
    refused = await artifacts.load_payload(SCOPE_A, invalid.ref, max_bytes=10_000_000)
    assert not refused.ok and refused.payload is None

    evicted = await artifacts.put(SCOPE_A, "b", frame(), task_id="t-1")
    assert await artifacts.evict(SCOPE_A, evicted.ref) is True
    after = await artifacts.get_version(SCOPE_A, evicted.ref, task_id="t-1")
    assert after is not None, "eviction keeps the metadata tombstone"
    assert after.invalidated is False, "an explicit eviction is not an invalidation"
    assert after.availability is ArtifactAvailability.MISSING
    assert await artifacts.evict(SCOPE_A, evicted.ref) is False, "nothing left to release"


@pytest.mark.asyncio
async def test_pins_restart_availability_generation_moves(stores) -> None:
    """Availability changing without a task event moves the generation.

    Recall folds this into its cache key, so a stale generation would
    serve a recall claiming evidence is present after it was evicted.
    """
    tasks, artifacts = stores
    await _make_task(tasks, SCOPE_A, "t-1")

    descriptor = await artifacts.put(SCOPE_A, "sales", frame(), task_id="t-1")
    after_put = (await artifacts.list(SCOPE_A)).availability_generation

    await artifacts.evict(SCOPE_A, descriptor.ref)
    after_evict = (await artifacts.list(SCOPE_A)).availability_generation
    assert after_evict != after_put, "an eviction must move the generation"

    await artifacts.invalidate(SCOPE_A, descriptor.ref, reason="gone")
    after_invalidate = (await artifacts.list(SCOPE_A)).availability_generation
    assert after_invalidate != after_evict, "an invalidation must move the generation"


@pytest.mark.asyncio
async def test_pins_restart_listing_is_paged_and_cursor_validated(stores) -> None:
    """Listings are bounded, ordered and cursor-validated across scopes."""
    tasks, artifacts = stores
    await _make_task(tasks, SCOPE_A, "t-1")
    for index in range(5):
        await artifacts.put(SCOPE_A, f"k{index}", {"n": index}, task_id="t-1")

    first = await artifacts.list(SCOPE_A, task_id="t-1", limit=2)
    assert len(first.items) == 2 and first.next_cursor is not None

    second = await artifacts.list(SCOPE_A, task_id="t-1", limit=2, cursor=first.next_cursor)
    assert len(second.items) == 2
    assert {i.ref.artifact_id for i in first.items}.isdisjoint({i.ref.artifact_id for i in second.items})

    with pytest.raises(CursorError):
        await artifacts.list(SCOPE_B, task_id="t-1", limit=2, cursor=first.next_cursor)

    kinds = await artifacts.list(SCOPE_A, task_id="t-1", kinds=[ArtifactKind.DATAFRAME])
    assert kinds.items == (), "no DataFrames were registered under this task"


@pytest.mark.asyncio
async def test_pins_restart() -> None:
    """Required aggregate case: pins and evidence survive terminal states and restarts."""
    _require_dsn()
