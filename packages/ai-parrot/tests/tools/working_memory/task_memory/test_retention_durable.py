"""TASK-3000 — verified archive and crash-safe durable cleanup.

This is Delivery B, so the destructive paths run against **real
PostgreSQL** and a real file manager on a real filesystem. That is not
ceremony. Every claim here is about what survives a partial failure, and
a double that never actually deletes anything cannot falsify a claim
about deletion. Configure it with::

    TASK_MEMORY_TEST_DSN=postgresql://user:pass@host:5432/db \\
        pytest packages/ai-parrot/tests/tools/working_memory/task_memory/test_retention_durable.py

Without it the durable cases **skip explicitly** and say so; a skip is
never reported as a pass. Each case gets a throwaway PostgreSQL schema
and its own temporary directory, both removed afterwards.

The three properties under test, and why each is a real hazard:

``test_archive_failure``
    An archive that fails, or that writes but does not verify, must
    leave the journal, the projection and the payloads exactly as they
    were. An unverified archive plus a deleted journal is
    indistinguishable from data loss, and the only moment we can still
    tell the difference is *before* the delete.

``test_orphan_race``
    A blob whose publish is still in flight, or which is an archived
    copy, has no live index row pointing at it — by design. A sweeper
    that treated "no index row" as "orphan" would delete both. The rule
    needs all three references absent, not just one.

``test_delete_retry``
    A crash between any two cleanup steps must converge on re-run:
    exactly one archive, no duplicate copies, and no loss of evidence
    that some other, still-live task pins.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator, List, Optional

import pytest

from parrot.tools.working_memory.task_memory.blob import ArtifactBlobStore, DurableBlobSweeper
from parrot.tools.working_memory.task_memory.config import TaskMemoryConfig
from parrot.tools.working_memory.task_memory.models import (
    Actor,
    ArtifactKind,
    EventType,
    EvidenceRef,
    JournalEvent,
    TaskLifecyclePayload,
    TaskScope,
    TaskStatus,
    new_id,
)
from parrot.tools.working_memory.task_memory.retention import (
    ARCHIVE_VERIFY_FAILED,
    BlobRetentionView,
    JsonlArchiveWriter,
    RetentionSweeper,
    select_due_blobs,
)
from parrot.tools.working_memory.task_memory.store.postgres import (
    PostgresArtifactStore,
    PostgresTaskMemoryStore,
)

pytestmark = pytest.mark.asyncio

#: Set this to run the durable cases. Never defaulted — see the docstring.
DSN_ENV = "TASK_MEMORY_TEST_DSN"

SCOPE = TaskScope(chatbot_id="bot-retention", user_id="user-1", session_id="sess-1")
OTHER_SCOPE = TaskScope(chatbot_id="bot-retention", user_id="user-2", session_id="sess-1")

_PG_SKIP = (
    f"no PostgreSQL configured: set {DSN_ENV} to run the durable retention cases. "
    "This is an ENVIRONMENTAL SKIP, not a pass — no durable behaviour was exercised here."
)

#: A fixed instant, so every age comparison is exact rather than racy.
NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


def _require_dsn() -> str:
    """Return the configured PostgreSQL DSN, or skip explicitly.

    Returns:
        The DSN.
    """
    dsn = os.environ.get(DSN_ENV) or None
    if not dsn:
        pytest.skip(_PG_SKIP)
    return dsn


@pytest.fixture()
async def pg_store() -> AsyncIterator[PostgresTaskMemoryStore]:
    """Yield a migrated store on a throwaway schema.

    Yields:
        The store.
    """
    dsn = _require_dsn()
    schema = f"wm_ret_{uuid.uuid4().hex[:12]}"
    store = PostgresTaskMemoryStore(dsn, schema=schema)
    await store.apply_migrations()
    try:
        yield store
    finally:
        try:
            await store.revert_migrations()
        except Exception:  # noqa: BLE001 — cleanup must not mask a failure
            pass
        await store.close()


@pytest.fixture()
def blob_root() -> AsyncIterator[str]:
    """Yield a private directory for blob storage.

    Yields:
        The directory path.
    """
    path = tempfile.mkdtemp(prefix="tm_retention_")
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


@pytest.fixture()
def blobs(blob_root: str) -> ArtifactBlobStore:
    """Yield a blob store over a REAL local file manager.

    Imported from ``navigator.utils.file.local`` rather than from
    ``parrot.interfaces.file``, because the repository's root
    ``tests/conftest.py`` replaces the latter with a bare stub whose
    ``LocalFileManager`` has no working methods. Through that stub
    ``exists()`` returns a truthy object for *any* key, which makes the
    blob store treat every fresh version as an immutability violation —
    and, worse, would let a "deletion" test pass without deleting
    anything. Every claim in this module is about real bytes, so it uses
    the real implementation.

    Args:
        blob_root: Its base directory.

    Returns:
        The store.
    """
    try:
        from navigator.utils.file.local import LocalFileManager
    except ImportError:  # pragma: no cover - navigator is a hard dependency here
        pytest.skip(
            "navigator's real LocalFileManager is unavailable — the durable blob cases "
            "did not run. This is an ENVIRONMENTAL SKIP, not a pass."
        )

    return ArtifactBlobStore(LocalFileManager(base_path=blob_root))


async def _terminal_task(
    store: PostgresTaskMemoryStore,
    *,
    scope: TaskScope = SCOPE,
    goal: str = "archive me",
    status: TaskStatus = TaskStatus.CANCELLED,
    terminal_at: Optional[datetime] = None,
) -> str:
    """Create a task and drive it to a terminal status.

    Args:
        store: The durable store.
        scope: Owning scope.
        goal: The task's goal.
        status: Terminal status to reach.
        terminal_at: Backdated terminal time, when the case needs the
            task to look old.

    Note:
        Cancellation is the default terminal status because the reducer
        refuses ``completed`` while a plan is incomplete, and these cases
        are about retention rather than about plan completion. Retention
        treats every terminal status alike.

    Returns:
        The task id.
    """
    task_id = new_id()
    await store.create_task(
        scope,
        goal=goal,
        events=[
            JournalEvent(
                task_id=task_id,
                event_type=EventType.TASK_STARTED,
                actor=Actor.AGENT,
                payload=TaskLifecyclePayload(status=TaskStatus.ACTIVE, goal=goal),
            )
        ],
    )
    await store.append_events(
        scope,
        task_id,
        [
            JournalEvent(
                task_id=task_id,
                event_type=EventType.TASK_COMPLETED
                if status is TaskStatus.COMPLETED
                else EventType.TASK_CANCELLED,
                actor=Actor.AGENT,
                payload=TaskLifecyclePayload(status=status),
            )
        ],
    )
    if terminal_at is not None:
        await _backdate_terminal(store, task_id, terminal_at)
    return task_id


async def _backdate_terminal(store: PostgresTaskMemoryStore, task_id: str, when: datetime) -> None:
    """Move a task's ``terminal_at`` into the past.

    Retention is age-based, and sleeping for 90 days is not an option.
    The clock is injected everywhere else; this is the one value that
    lives in a column rather than in the sweeper.

    Args:
        store: The durable store.
        task_id: The task to backdate.
        when: The new terminal time.
    """
    pool = await store._acquire_pool()
    async with pool.acquire() as connection:
        # BOTH must move. `_row_to_state` documents the projection column
        # as "the whole authority for the returned state", so updating
        # only the scalar column would leave the sweeper reading the
        # original timestamp and selecting nothing.
        await connection.execute(
            f"""
            UPDATE {store._t('tasks')}
               SET terminal_at = $2,
                   projection = jsonb_set(projection, '{{terminal_at}}', to_jsonb($3::text))
             WHERE task_id = $1
            """,
            task_id,
            when,
            when.isoformat(),
        )


async def _journal_len(store: PostgresTaskMemoryStore, task_id: str, scope: TaskScope = SCOPE) -> int:
    """Return how many events a task's journal holds.

    Args:
        store: The durable store.
        task_id: The task.
        scope: Owning scope.

    Returns:
        The event count.
    """
    return await store.count_events(scope, task_id)


class _Clock:
    """A clock the test advances by hand."""

    def __init__(self, now: datetime = NOW) -> None:
        """Initialize at a fixed instant."""
        self.now = now

    def __call__(self) -> datetime:
        """Return the current instant."""
        return self.now


class _FlakyArchive:
    """An archive writer that fails in a chosen way.

    Args:
        inner: The real writer to delegate to.
        mode: ``"raise"`` to fail the write, ``"unverified"`` to write
            successfully but fail verification, ``"ok"`` to behave.
    """

    def __init__(self, inner: JsonlArchiveWriter, mode: str) -> None:
        """Initialize the wrapper."""
        self.inner = inner
        self.mode = mode
        self.writes: List[str] = []

    async def write(self, uri: str, task_id: str, events: Any) -> str:
        """Write, or fail, depending on the mode."""
        if self.mode == "raise":
            raise RuntimeError("archive backend unavailable")
        reference = await self.inner.write(uri, task_id, events)
        self.writes.append(reference)
        return reference

    async def verify(self, reference: str, expected_events: int) -> bool:
        """Verify, or refuse to, depending on the mode."""
        if self.mode == "unverified":
            return False
        return await self.inner.verify(reference, expected_events)


# ─────────────────────────────────────────────────────────────
# test_archive_failure
# ─────────────────────────────────────────────────────────────


async def test_archive_failure(pg_store: PostgresTaskMemoryStore, blobs: ArtifactBlobStore) -> None:
    """A failed or unverified archive deletes nothing."""
    clock = _Clock()
    config = TaskMemoryConfig(archive_uri="file://archive")
    task_id = await _terminal_task(pg_store, terminal_at=NOW - timedelta(days=120))
    before = await _journal_len(pg_store, task_id)
    assert before >= 2

    writer = JsonlArchiveWriter(blobs, SCOPE)

    # ── the write itself fails ───────────────────────────────────────
    raising = _FlakyArchive(writer, "raise")
    sweeper = RetentionSweeper(
        pg_store, config=config, clock=clock, archive=raising, purge=pg_store
    )
    report = await sweeper.run_once([SCOPE])

    assert report.deleted == []
    assert report.archived == []
    assert any("archive failed" in reason for _, reason in report.deferred), report.deferred
    # The journal, its projection and the task itself all survive.
    assert await pg_store.load_snapshot(SCOPE, task_id) is not None
    assert await _journal_len(pg_store, task_id) >= before
    # Nothing was destroyed, so nothing is claimed to have been.
    assert report.audit_destroyed == []

    # ── the write succeeds but does not verify ───────────────────────
    unverified = _FlakyArchive(writer, "unverified")
    sweeper = RetentionSweeper(
        pg_store, config=config, clock=clock, archive=unverified, purge=pg_store
    )
    report = await sweeper.run_once([SCOPE])

    assert report.deleted == []
    assert (task_id, ARCHIVE_VERIFY_FAILED) in report.deferred
    assert await pg_store.load_snapshot(SCOPE, task_id) is not None
    assert report.audit_destroyed == []

    # ── and once it verifies, the delete proceeds ────────────────────
    good = _FlakyArchive(writer, "ok")
    sweeper = RetentionSweeper(pg_store, config=config, clock=clock, archive=good, purge=pg_store)
    report = await sweeper.run_once([SCOPE])

    assert report.archived == [task_id]
    assert report.deleted == [task_id]
    assert await pg_store.load_snapshot(SCOPE, task_id) is None
    # The audit trail moved rather than vanished, and the report says so.
    assert len(report.audit_destroyed) == 1
    destroyed_task, reference = report.audit_destroyed[0]
    assert destroyed_task == task_id
    assert reference is not None

    # The archive contains the retention intent event that announced
    # this very deletion — the one record the deleted journal held.
    payload = await blobs._download(reference)
    lines = [line for line in payload.split(b"\n") if line.strip()]
    assert any(b'"retention_scheduled"' in line for line in lines)


async def test_archive_failure_without_purge_capability(
    pg_store: PostgresTaskMemoryStore, blobs: ArtifactBlobStore
) -> None:
    """With no purge wired, expiry is deferred rather than silently skipped."""
    clock = _Clock()
    config = TaskMemoryConfig(archive_uri="file://archive")
    task_id = await _terminal_task(pg_store, terminal_at=NOW - timedelta(days=120))

    sweeper = RetentionSweeper(
        pg_store, config=config, clock=clock, archive=JsonlArchiveWriter(blobs, SCOPE), purge=None
    )
    report = await sweeper.run_once([SCOPE])

    assert report.deleted == []
    assert any("purge" in reason for _, reason in report.deferred), report.deferred
    assert await pg_store.load_snapshot(SCOPE, task_id) is not None


async def test_purge_refuses_a_live_task(pg_store: PostgresTaskMemoryStore) -> None:
    """A task that is not terminal is never purged, even if asked."""
    task_id = new_id()
    await pg_store.create_task(
        SCOPE,
        goal="still working",
        events=[
            JournalEvent(
                task_id=task_id,
                event_type=EventType.TASK_STARTED,
                actor=Actor.AGENT,
                payload=TaskLifecyclePayload(status=TaskStatus.ACTIVE, goal="still working"),
            )
        ],
    )
    # The last line of defence: retention only selects terminal tasks,
    # but a stale view must not be able to delete live work.
    assert await pg_store.purge_task(SCOPE, task_id) is False
    assert await pg_store.load_snapshot(SCOPE, task_id) is not None

    # Nor may another scope reach it.
    assert await pg_store.purge_task(OTHER_SCOPE, task_id) is False
    assert await pg_store.load_snapshot(SCOPE, task_id) is not None


# ─────────────────────────────────────────────────────────────
# test_orphan_race
# ─────────────────────────────────────────────────────────────


async def test_orphan_race(pg_store: PostgresTaskMemoryStore, blobs: ArtifactBlobStore) -> None:
    """A publishing or archived blob is not swept by an unrelated scan."""
    import pandas as pd

    # A genuinely live blob, referenced by an index row.
    live_ref = EvidenceRef(artifact_id=new_id(), version=1)
    live_blob = await blobs.publish(
        SCOPE, live_ref, pd.DataFrame({"a": [1, 2, 3]}), kind=ArtifactKind.DATAFRAME
    )

    # A blob mid-publish: its bytes exist, its index row does not yet.
    publishing_ref = EvidenceRef(artifact_id=new_id(), version=1)
    publishing = await blobs.publish(
        SCOPE, publishing_ref, pd.DataFrame({"b": [4]}), kind=ArtifactKind.DATAFRAME
    )

    # An archived copy: a reference with deliberately no index row.
    archive_key = f"{blobs.archive_prefix(SCOPE)}/old-task.jsonl"
    await blobs._fm.create_from_bytes(archive_key, b'{"event":1}\n')

    # A true orphan: bytes with nothing at all pointing at them.
    orphan_ref = EvidenceRef(artifact_id=new_id(), version=1)
    orphan = await blobs.publish(
        SCOPE, orphan_ref, pd.DataFrame({"c": [9]}), kind=ArtifactKind.DATAFRAME
    )

    async def live_refs(scope: TaskScope) -> Any:
        """Only the live blob is in the index."""
        return {live_blob.key}

    async def publish_lease(scope: TaskScope, key: str) -> bool:
        """The mid-publish blob holds a lease."""
        return key == publishing.key

    sweeper = DurableBlobSweeper(blobs, live_refs=live_refs, publish_lease=publish_lease)
    views = await sweeper.list_orphans(SCOPE)
    by_key = {v.storage_ref: v for v in views}

    assert by_key[live_blob.key].has_live_index is True
    assert by_key[publishing.key].has_publish_lease is True
    assert by_key[archive_key].has_archive_reference is True
    assert by_key[orphan.key].is_orphan is True

    # Only the true orphan is even a candidate...
    assert by_key[live_blob.key].is_orphan is False
    assert by_key[publishing.key].is_orphan is False
    assert by_key[archive_key].is_orphan is False

    # ...and only after its grace period.
    config = TaskMemoryConfig()
    fresh = select_due_blobs(NOW, views, config)
    assert fresh == (), "a blob inside its grace period is not due"

    aged = [
        BlobRetentionView(
            scope=v.scope,
            storage_ref=v.storage_ref,
            written_at=NOW - timedelta(hours=config.orphan_blob_grace_hours + 1),
            has_live_index=v.has_live_index,
            has_publish_lease=v.has_publish_lease,
            has_archive_reference=v.has_archive_reference,
        )
        for v in views
    ]
    due = select_due_blobs(NOW, aged, config)
    assert [a.storage_ref for a in due] == [orphan.key]

    # Sweeping removes exactly that one; everything else still reads.
    assert await sweeper.sweep(SCOPE, orphan.key) is True
    assert await blobs.exists(orphan) is False
    assert await blobs.exists(live_blob) is True
    assert await blobs.exists(publishing) is True
    assert await blobs._fm.exists(archive_key) is True


async def test_orphan_race_unreadable_index_sweeps_nothing(blobs: ArtifactBlobStore) -> None:
    """An index that cannot be read is not an empty index."""
    import pandas as pd

    ref = EvidenceRef(artifact_id=new_id(), version=1)
    await blobs.publish(SCOPE, ref, pd.DataFrame({"a": [1]}), kind=ArtifactKind.DATAFRAME)

    async def broken(scope: TaskScope) -> Any:
        """The index is unavailable."""
        raise RuntimeError("index unavailable")

    sweeper = DurableBlobSweeper(blobs, live_refs=broken)
    # Reporting "no live references" here would mark every blob an
    # orphan and delete the lot on the next pass.
    assert await sweeper.list_orphans(SCOPE) == ()


async def test_orphan_race_lease_probe_failure_protects(blobs: ArtifactBlobStore) -> None:
    """An unanswerable publish-lease probe counts as leased."""
    import pandas as pd

    ref = EvidenceRef(artifact_id=new_id(), version=1)
    blob = await blobs.publish(SCOPE, ref, pd.DataFrame({"a": [1]}), kind=ArtifactKind.DATAFRAME)

    async def live_refs(scope: TaskScope) -> Any:
        """Nothing is in the index."""
        return set()

    async def broken_lease(scope: TaskScope, key: str) -> bool:
        """The lease store is unreachable."""
        raise RuntimeError("redis down")

    sweeper = DurableBlobSweeper(blobs, live_refs=live_refs, publish_lease=broken_lease)
    views = await sweeper.list_orphans(SCOPE)
    assert len(views) == 1
    assert views[0].has_publish_lease is True
    assert views[0].is_orphan is False
    assert await blobs.exists(blob) is True


async def test_sweep_refuses_a_key_outside_the_scope(blobs: ArtifactBlobStore) -> None:
    """A key from another scope's sub-tree is never deleted."""
    import pandas as pd

    ref = EvidenceRef(artifact_id=new_id(), version=1)
    other = await blobs.publish(OTHER_SCOPE, ref, pd.DataFrame({"a": [1]}), kind=ArtifactKind.DATAFRAME)

    async def live_refs(scope: TaskScope) -> Any:
        """Nothing live."""
        return set()

    sweeper = DurableBlobSweeper(blobs, live_refs=live_refs)
    assert await sweeper.sweep(SCOPE, other.key) is False
    assert await blobs.exists(other) is True


# ─────────────────────────────────────────────────────────────
# test_delete_retry
# ─────────────────────────────────────────────────────────────


async def test_delete_retry(pg_store: PostgresTaskMemoryStore, blobs: ArtifactBlobStore) -> None:
    """Crashing between steps converges: one archive, pinned evidence kept."""
    import pandas as pd

    clock = _Clock()
    config = TaskMemoryConfig(archive_uri="file://archive")
    artifacts = PostgresArtifactStore(pg_store, blobs=blobs)

    # A task that produces evidence while it is still live...
    expired = new_id()
    await pg_store.create_task(
        SCOPE,
        goal="expired",
        events=[
            JournalEvent(
                task_id=expired,
                event_type=EventType.TASK_STARTED,
                actor=Actor.AGENT,
                payload=TaskLifecyclePayload(status=TaskStatus.ACTIVE, goal="expired"),
            )
        ],
    )
    # ...and a still-live task that will pin that evidence.
    live_task = new_id()
    await pg_store.create_task(
        SCOPE,
        goal="still running",
        events=[
            JournalEvent(
                task_id=live_task,
                event_type=EventType.TASK_STARTED,
                actor=Actor.AGENT,
                payload=TaskLifecyclePayload(status=TaskStatus.ACTIVE, goal="still running"),
            )
        ],
    )

    shared = await artifacts.put(
        SCOPE,
        "shared_frame",
        pd.DataFrame({"x": [1, 2]}),
        task_id=expired,
        kind=ArtifactKind.DATAFRAME,
    )
    await artifacts.pin_evidence(SCOPE, shared.ref, live_task, step_id="step-1")
    assert live_task in await artifacts.pins_for(SCOPE, shared.ref)

    # Only now does the producer go terminal and age past its retention.
    # Registering evidence against an already-cancelled task is refused by
    # the reducer, which is why the order matters here.
    await pg_store.append_events(
        SCOPE,
        expired,
        [
            JournalEvent(
                task_id=expired,
                event_type=EventType.TASK_CANCELLED,
                actor=Actor.AGENT,
                payload=TaskLifecyclePayload(status=TaskStatus.CANCELLED),
            )
        ],
    )
    await _backdate_terminal(pg_store, expired, NOW - timedelta(days=200))

    writer = JsonlArchiveWriter(blobs, SCOPE)

    # ── crash after archiving, before deleting ───────────────────────
    crashed = _FlakyArchive(writer, "ok")

    class _CrashingPurge:
        """Fails the purge, simulating a crash after the archive."""

        async def purge_task(self, scope: TaskScope, task_id: str) -> bool:
            """Always fail."""
            raise RuntimeError("crashed before delete committed")

    sweeper = RetentionSweeper(
        pg_store, config=config, clock=clock, archive=crashed, purge=_CrashingPurge()
    )
    report = await sweeper.run_once([SCOPE])
    assert report.archived == [expired]
    assert report.deleted == []
    assert any("purge failed" in reason for _, reason in report.errors), report.errors
    # The task is still there, so the retry has something to converge on.
    assert await pg_store.load_snapshot(SCOPE, expired) is not None
    first_archive = crashed.writes[-1]
    first_bytes = await blobs._download(first_archive)

    # ── retry: same archive key, no duplicate, delete completes ──────
    retried = _FlakyArchive(writer, "ok")
    sweeper = RetentionSweeper(
        pg_store, config=config, clock=clock, archive=retried, purge=pg_store
    )
    report = await sweeper.run_once([SCOPE])

    assert report.deleted == [expired]
    assert retried.writes[-1] == first_archive, "a retry must reuse the archive key, not duplicate it"
    assert await blobs._download(first_archive) == first_bytes

    # Exactly one archive object exists for this task.
    archived = [
        b for b in await blobs.list_stored(SCOPE) if b.key.startswith(blobs.archive_prefix(SCOPE) + "/")
    ]
    assert len(archived) == 1, [b.key for b in archived]

    # ── the still-live task's evidence survived the purge ────────────
    assert await pg_store.load_snapshot(SCOPE, expired) is None
    assert await pg_store.load_snapshot(SCOPE, live_task) is not None
    surviving = await artifacts.get_version(SCOPE, shared.ref)
    assert surviving is not None, "evidence pinned by a live task was deleted"
    assert live_task in await artifacts.pins_for(SCOPE, shared.ref)
    assert await blobs.exists(await _blob_of(artifacts, shared.ref)) is True

    # ── a third run is a no-op: nothing left to do ───────────────────
    again = _FlakyArchive(writer, "ok")
    sweeper = RetentionSweeper(pg_store, config=config, clock=clock, archive=again, purge=pg_store)
    report = await sweeper.run_once([SCOPE])
    assert report.deleted == []
    assert report.archived == []
    assert again.writes == []


async def test_delete_retry_is_idempotent_at_the_store(pg_store: PostgresTaskMemoryStore) -> None:
    """Purging an already-purged task returns False rather than failing."""
    task_id = await _terminal_task(pg_store, terminal_at=NOW - timedelta(days=200))
    assert await pg_store.purge_task(SCOPE, task_id) is True
    # The retry after a crash between "deleted" and "recorded as deleted".
    assert await pg_store.purge_task(SCOPE, task_id) is False
    assert await pg_store.load_snapshot(SCOPE, task_id) is None


async def _blob_of(artifacts: PostgresArtifactStore, ref: EvidenceRef) -> Any:
    """Return the stored blob reference for a version.

    Args:
        artifacts: The durable artifact store.
        ref: The version.

    Returns:
        Its :class:`~...blob.BlobRef`.
    """
    async with artifacts._reader() as connection:
        row = await artifacts._version_row(connection, SCOPE, ref)
    return artifacts._stored_blob(row)
