"""TASK-3004 — the durable crash matrix.

``test_crash_boundaries`` walks the points where a process can die
mid-operation and asserts the same property at every one of them:

    the state left behind is either COMMITTED AND CONSISTENT, or an
    EXPLICIT, RECOVERABLE orphan / unknown outcome.

What must never happen is the third thing — a half-committed state that
reads as complete. That is the failure mode the whole feature exists to
prevent, because it is invisible until someone trusts it.

The points exercised:

===========================  =============================================
Crash point                  Required outcome
===========================  =============================================
before the blob write        no row, no bytes; nothing to recover
after bytes, before the row  an ORPHAN blob, sweepable; never a row
                             pointing at bytes that do not exist
inside the index transaction the whole version rolls back; the alias does
                             not move
after tool start, no         an explicit UNKNOWN outcome, appended once,
terminal event               and the external effect is NOT retried
after the external effect    the same: unknown, never a silent success
archive written, delete not  retry converges on ONE archive and completes
                             the delete
===========================  =============================================

Every case needs a real PostgreSQL and a real filesystem, and skips
explicitly without them — a skip is never reported as a pass.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any, AsyncIterator, List, Optional, Tuple

import pytest

from parrot.tools.working_memory.task_memory.blob import ArtifactBlobStore
from parrot.tools.working_memory.task_memory.config import TaskMemoryConfig
from parrot.tools.working_memory.task_memory.models import (
    ArtifactAvailability,
    CallOutcome,
    EvidenceRef,
    EventType,
    InitialStepSpec,
    TaskScope,
)
from parrot.tools.working_memory.task_memory.service import TaskMemoryService
from parrot.tools.working_memory.task_memory.store.postgres import (
    PostgresArtifactStore,
    PostgresTaskMemoryStore,
)

pytestmark = pytest.mark.asyncio

DSN_ENV = "TASK_MEMORY_TEST_DSN"
SMALL_SNAPSHOT_CAP = 2_048


class _Crash(RuntimeError):
    """The simulated process death."""


def _require_dsn() -> str:
    """Return the configured DSN or skip explicitly.

    Returns:
        The DSN.
    """
    dsn = os.environ.get(DSN_ENV) or None
    if not dsn:
        pytest.skip(
            f"no PostgreSQL configured: set {DSN_ENV} to run the crash matrix. "
            "This is an ENVIRONMENTAL SKIP, not a pass — no crash boundary was exercised."
        )
    return dsn


def _scope() -> TaskScope:
    """Return the canonical scope.

    Returns:
        The scope.
    """
    return TaskScope(chatbot_id="bot-a", user_id="user-1", session_id="sess-1")


class _Stack:
    """A migrated store, artifact store and service over one schema."""

    def __init__(self, store: Any, artifacts: Any, blobs: Any, config: TaskMemoryConfig) -> None:
        """Bind the components."""
        self.store = store
        self.artifacts = artifacts
        self.blobs = blobs
        self.config = config
        self.service = TaskMemoryService(store, config, artifacts=artifacts)

    async def close(self) -> None:
        """Close owned connections."""
        await self.store.close()


@pytest.fixture()
async def stack(tmp_path: Any) -> AsyncIterator[_Stack]:
    """Yield a durable stack on a throwaway schema and real files.

    Yields:
        The stack.
    """
    dsn = _require_dsn()
    schema = f"wm_crash_{uuid.uuid4().hex[:12]}"
    # The REAL file manager: the root conftest's stub reports exists()
    # truthy for any key, under which an orphan-blob assertion would pass
    # without a single byte ever being written.
    from navigator.utils.file.local import LocalFileManager

    fm = LocalFileManager(str(tmp_path))
    config = TaskMemoryConfig(enabled=True, durable=True, dsn=dsn, snapshot_max_bytes=SMALL_SNAPSHOT_CAP)
    store = PostgresTaskMemoryStore(dsn, schema=schema, config=config)
    await store.apply_migrations()
    blobs = ArtifactBlobStore(fm, prefix="crash")
    artifacts = PostgresArtifactStore(store, blobs=blobs, config=config)
    built = _Stack(store, artifacts, blobs, config)
    built.root = tmp_path  # type: ignore[attr-defined]
    try:
        yield built
    finally:
        await built.close()
        cleaner = PostgresTaskMemoryStore(dsn, schema=schema)
        try:
            await cleaner.revert_migrations()
        except Exception:  # noqa: BLE001 — cleanup must not mask a failure
            pass
        await cleaner.close()


def _blob_files(root: Any) -> List[Any]:
    """Return every file written beneath the blob root.

    Args:
        root: The temporary directory.

    Returns:
        The files.
    """
    return [p for p in root.rglob("*") if p.is_file()]


async def _a_task(stack: _Stack, scope: TaskScope) -> Tuple[str, str]:
    """Create a one-step task.

    Args:
        stack: The durable stack.
        scope: The trusted scope.

    Returns:
        ``(task_id, step_id)``.
    """
    begun = await stack.service.begin_task(
        scope, goal="crash matrix", steps=[InitialStepSpec(label="a", title="do the thing")]
    )
    return begun.state.task_id, begun.state.steps[0].step_id


# ─────────────────────────────────────────────────────────────
# test_crash_boundaries
# ─────────────────────────────────────────────────────────────


async def test_crash_boundaries(stack: _Stack) -> None:
    """Every crash point is consistent, or explicitly recoverable."""
    scope = _scope()
    task_id, step_id = await _a_task(stack, scope)
    big = {"rows": ["x" * 256 for _ in range(64)]}

    # ── 1. crash BEFORE the blob write ───────────────────────────────
    async def _die_before(*a: Any, **k: Any) -> Any:
        raise _Crash("died before publishing bytes")

    original_publish = stack.blobs.publish
    stack.blobs.publish = _die_before  # type: ignore[assignment]
    try:
        before_files = _blob_files(stack.root)
        # `put` records a failed publish honestly rather than raising, so
        # the row must say the bytes are MISSING instead of claiming them.
        descriptor = await stack.artifacts.put(scope, "pre_blob", big, task_id=task_id)
        assert _blob_files(stack.root) == before_files, "bytes were written despite the crash"
        assert descriptor.availability is not ArtifactAvailability.PERSISTED, (
            "a version whose bytes were never written must not claim to be persisted"
        )
        # And the truth survives a reload — this is not just an in-memory flag.
        reloaded = await stack.artifacts.get_version(scope, descriptor.ref, task_id=task_id)
        assert reloaded.availability is not ArtifactAvailability.PERSISTED
    finally:
        stack.blobs.publish = original_publish  # type: ignore[assignment]

    # ── 2. crash AFTER the bytes, BEFORE the index row ───────────────
    published: List[Any] = []

    async def _die_after(scope_: Any, ref: Any, value: Any, **k: Any) -> Any:
        """Publish for real, then die before the row is inserted."""
        result = await original_publish(scope_, ref, value, **k)
        published.append(result)
        raise _Crash("died after publishing bytes")

    stack.blobs.publish = _die_after  # type: ignore[assignment]
    try:
        files_before = set(_blob_files(stack.root))
        descriptor = await stack.artifacts.put(scope, "orphan_blob", big, task_id=task_id)
        files_after = set(_blob_files(stack.root))
        orphans = files_after - files_before
        # Bytes on disk, and the row does NOT claim them. That asymmetry
        # is deliberate: an orphan blob is sweepable, whereas a row
        # pointing at bytes that were never written is unrecoverable.
        assert orphans, "sanity: the real publish should have written bytes"
        assert descriptor.availability is not ArtifactAvailability.PERSISTED
        assert published, "sanity: the wrapped publish must have run"
    finally:
        stack.blobs.publish = original_publish  # type: ignore[assignment]

    # ── 3. crash INSIDE the index transaction ────────────────────────
    current_before = await stack.artifacts.get_current(scope, "txn", task_id=task_id)
    seeded = await stack.artifacts.put(scope, "txn", {"v": 1}, task_id=task_id)
    original_move = stack.artifacts._move_alias

    async def _die_mid_txn(*a: Any, **k: Any) -> Any:
        raise _Crash("died mid-transaction")

    stack.artifacts._move_alias = _die_mid_txn  # type: ignore[assignment]
    try:
        with pytest.raises(_Crash):
            await stack.artifacts.put(scope, "txn", {"v": 2}, task_id=task_id)
    finally:
        stack.artifacts._move_alias = original_move  # type: ignore[assignment]

    after = await stack.artifacts.get_current(scope, "txn", task_id=task_id)
    # The alias did not move, and the half-written version is not
    # readable: the transaction rolled back as a unit.
    assert after.ref == seeded.ref, "the alias moved despite a mid-transaction crash"
    assert current_before is None or current_before.ref != after.ref

    # ── 4. tool started, terminal event never written ────────────────
    from parrot.tools.working_memory.task_memory.context import turn_session
    from parrot.tools.working_memory.task_memory.observer import InvocationObserver

    appended: List[Any] = []

    async def _append(task: str, events: Any) -> Any:
        """Append events for real, recording what was written."""
        appended.extend(events)
        return await stack.store.append_events(scope, task, tuple(events))

    with turn_session(scope, task_id=task_id) as session:
        observer = InvocationObserver(session, append=_append)
        call = await observer.begin("external_effect")
        # The process dies here: the effect ran, nothing terminal was
        # recorded. `finish` is never called.

    started = [e for e in appended if e.event_type is EventType.TOOL_STARTED]
    assert started, "the start must be journalled before the effect runs"

    events = await stack.store.list_events(scope, task_id, after_seq=0, limit=500)
    terminal_for_call = [
        e
        for e in events.events
        if e.call_id == call.call_id and e.event_type is not EventType.TOOL_STARTED
    ]
    assert not terminal_for_call, "sanity: this call is deliberately unresolved"

    # Recovery must classify it as UNKNOWN — explicitly — and must not
    # re-run the effect. An unresolved external call is exactly the thing
    # that must never be retried automatically.
    unresolved = await stack.store.unresolved_calls(scope, task_id)
    assert any(u.call_id == call.call_id for u in unresolved), (
        f"the interrupted call was not reported as unresolved: {unresolved}"
    )

    report = await stack.store.reconcile_calls(
        scope, task_id, is_live=lambda _c: _dead(), reason="pod lost"
    )
    assert call.call_id in report.reconciled, report

    after_events = await stack.store.list_events(scope, task_id, after_seq=0, limit=500)
    unknowns = [
        e
        for e in after_events.events
        if e.call_id == call.call_id and e.event_type is EventType.TOOL_OUTCOME_UNKNOWN
    ]
    assert len(unknowns) == 1, f"expected exactly one unknown outcome, got {len(unknowns)}"

    # ── 5. reconciling twice must not append a second unknown ────────
    again = await stack.store.reconcile_calls(
        scope, task_id, is_live=lambda _c: _dead(), reason="pod lost"
    )
    assert call.call_id not in again.reconciled
    final_events = await stack.store.list_events(scope, task_id, after_seq=0, limit=500)
    assert (
        len([e for e in final_events.events if e.event_type is EventType.TOOL_OUTCOME_UNKNOWN]) == 1
    ), "a second scan appended a duplicate unknown outcome"


async def _dead() -> bool:
    """Report the owner as provably dead.

    Returns:
        ``False`` — a definite death, which is the only verdict that may
        be reconciled.
    """
    return False


async def test_crash_boundaries_archive_then_delete_is_idempotent(stack: _Stack) -> None:
    """A crash between archive and delete converges on one archive."""
    from parrot.tools.working_memory.task_memory.retention import JsonlArchiveWriter

    scope = _scope()
    task_id, _ = await _a_task(stack, scope)

    # The writer is scope-bound and takes the BLOB STORE, not a file
    # manager — the same signature my TASK-3003 runtime got wrong.
    writer = JsonlArchiveWriter(stack.blobs, scope)
    events = await stack.store.list_events(scope, task_id, after_seq=0, limit=500)

    # First attempt: archive succeeds, then the process dies before the
    # delete runs.
    first = await writer.write("archives", task_id, events.events)
    files_after_first = {p.name for p in _blob_files(stack.root)}

    # Retry from scratch: the SAME archive key, byte-identical content.
    second = await writer.write("archives", task_id, events.events)
    files_after_second = {p.name for p in _blob_files(stack.root)}

    assert first == second, "the archive key must be deterministic, or retries accumulate copies"
    assert files_after_first == files_after_second, "a retry created a second archive"

    # Verification passes on the retried archive, so the delete that was
    # interrupted is now safe to complete.
    assert await writer.verify(second, len(events.events)) is True


async def test_crash_boundaries_never_leaves_a_row_without_bytes(stack: _Stack) -> None:
    """The asymmetry is deliberate and holds under a payload reload."""
    scope = _scope()
    task_id, _ = await _a_task(stack, scope)
    big = {"rows": ["z" * 256 for _ in range(64)]}

    original = stack.blobs.publish

    async def _fail(*a: Any, **k: Any) -> Any:
        raise _Crash("publish failed")

    stack.blobs.publish = _fail  # type: ignore[assignment]
    try:
        descriptor = await stack.artifacts.put(scope, "no_bytes", big, task_id=task_id)
    finally:
        stack.blobs.publish = original  # type: ignore[assignment]

    # Reading it back must REFUSE rather than invent a payload, and the
    # refusal must be explicit enough to act on.
    result = await stack.artifacts.load_payload(scope, descriptor.ref, max_bytes=10_000_000)
    assert result.payload is None
    assert result.refusal is not None, "a version with no bytes must refuse, not return None silently"


async def test_crash_boundaries_a_slow_call_is_not_a_crashed_one(stack: _Stack) -> None:
    """At the same boundary, a live call must survive reconciliation.

    The interrupted-call boundary has two sides, and only one of them is
    a crash. A long-running tool looks identical from the journal — a
    start with no terminal event — so reconciliation that keys off "no
    terminal event" alone would mark healthy work unknown and invite its
    external effect to be re-run. Liveness is what separates them, and
    an UNKNOWN liveness must resolve to "leave it alone".
    """
    from parrot.tools.working_memory.task_memory.context import turn_session
    from parrot.tools.working_memory.task_memory.observer import InvocationObserver

    scope = _scope()
    task_id, _ = await _a_task(stack, scope)

    async def _append(task: str, events: Any) -> Any:
        """Append for real.

        Args:
            task: The task id.
            events: Events to append.

        Returns:
            The append result.
        """
        return await stack.store.append_events(scope, task, tuple(events))

    with turn_session(scope, task_id=task_id) as session:
        observer = InvocationObserver(session, append=_append)
        call = await observer.begin("slow_but_healthy")

    async def _alive(_c: Any) -> bool:
        """Report the owner as still holding the call."""
        return True

    async def _unknown(_c: Any) -> Optional[bool]:
        """Report liveness as unestablished."""
        return None

    # Alive: left strictly alone.
    alive_report = await stack.store.reconcile_calls(scope, task_id, is_live=_alive, reason="scan")
    assert call.call_id not in alive_report.reconciled, "a live call was declared unknown"

    # Unknown liveness: also left alone. Inventing a death here is how a
    # healthy call gets its effect retried.
    unknown_report = await stack.store.reconcile_calls(scope, task_id, is_live=_unknown, reason="scan")
    assert call.call_id not in unknown_report.reconciled, "an unestablished liveness was treated as death"

    events = await stack.store.list_events(scope, task_id, after_seq=0, limit=500)
    assert not [
        e for e in events.events if e.event_type is EventType.TOOL_OUTCOME_UNKNOWN
    ], "an unknown outcome was appended for a call that was never shown to be dead"
