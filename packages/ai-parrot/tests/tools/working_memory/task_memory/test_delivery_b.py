"""TASK-3004 — Delivery B: durable restart and multi-pod concurrency.

Two of the three required cases live here; the crash matrix is in
``test_crash_matrix.py``.

``test_restart_primary``
    The primary continuity scenario survives a real process-level
    restart: every object is torn down and rebuilt against the same
    PostgreSQL, and the task, its plan, its constraints and its exact
    evidence versions are all still there. Artifacts both BELOW and ABOVE
    the RAM snapshot cap reload, and evidence bound to an old version
    still resolves to that version after a newer one exists.

``test_multi_pod``
    Two runtimes over one database, behaving as two pods: concurrent
    appends produce no sequence gaps and no double terminalization,
    concurrent alias writes allocate distinct versions, a lease has
    exactly one holder, and neither pod can see the other scope's task.

Every case here requires a REAL PostgreSQL and skips explicitly without
one. A skip is never reported as a pass — the task is unambiguous that
durable acceptance cannot be claimed from mocked runs.
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
    EvidenceRef,
    InitialStepSpec,
    StepStatus,
    TaskScope,
    TaskStatus,
)
from parrot.tools.working_memory.task_memory.service import TaskMemoryService
from parrot.tools.working_memory.task_memory.store.postgres import (
    PostgresArtifactStore,
    PostgresTaskMemoryStore,
)

pytestmark = pytest.mark.asyncio

DSN_ENV = "TASK_MEMORY_TEST_DSN"

#: Small enough that a modest payload lands in a blob instead of inline,
#: so "above the RAM cap" is exercised without allocating 64 MiB.
SMALL_SNAPSHOT_CAP = 2_048


def _require_dsn() -> str:
    """Return the configured DSN or skip explicitly.

    Returns:
        The DSN.
    """
    dsn = os.environ.get(DSN_ENV) or None
    if not dsn:
        pytest.skip(
            f"no PostgreSQL configured: set {DSN_ENV} to run the Delivery B cases. "
            "This is an ENVIRONMENTAL SKIP, not a pass — no durable behaviour was exercised."
        )
    return dsn


def _scope(session: str = "sess-1", user: str = "user-1") -> TaskScope:
    """Build a trusted scope.

    Args:
        session: Session id.
        user: User id.

    Returns:
        The scope.
    """
    return TaskScope(chatbot_id="bot-a", user_id=user, session_id=session)


@pytest.fixture()
async def pg(tmp_path: Any) -> AsyncIterator[Tuple[str, str, Any]]:
    """Yield ``(dsn, schema, file_manager)`` on a throwaway schema.

    Yields:
        The DSN, a unique schema, and a real local file manager rooted in
        a temporary directory.
    """
    dsn = _require_dsn()
    schema = f"wm_b_{uuid.uuid4().hex[:12]}"
    # The REAL navigator manager, deliberately. The root conftest installs
    # a stub `parrot.interfaces.file` whose exists() is truthy for any key,
    # under which a blob test would pass without ever writing a byte.
    from navigator.utils.file.local import LocalFileManager

    fm = LocalFileManager(str(tmp_path))
    try:
        yield dsn, schema, fm
    finally:
        cleaner = PostgresTaskMemoryStore(dsn, schema=schema)
        try:
            await cleaner.revert_migrations()
        except Exception:  # noqa: BLE001 — cleanup must not mask a failure
            pass
        await cleaner.close()


class _Pod:
    """One process's view of the shared database.

    Named for what it models: tearing this down and building another is
    the restart, and holding two at once is the two-pod case.
    """

    def __init__(self, store: Any, artifacts: Any, config: TaskMemoryConfig) -> None:
        """Bind the stores for this pod."""
        self.store = store
        self.artifacts = artifacts
        self.config = config
        self.service = TaskMemoryService(store, config, artifacts=artifacts)

    async def close(self) -> None:
        """Close this pod's own connections."""
        await self.store.close()


async def _boot(dsn: str, schema: str, fm: Any, *, migrate: bool = False) -> _Pod:
    """Start a pod against the shared schema.

    Args:
        dsn: Connection string.
        schema: The shared schema.
        fm: File manager for blobs.
        migrate: Whether to apply the migration first.

    Returns:
        The pod.
    """
    config = TaskMemoryConfig(enabled=True, durable=True, dsn=dsn, snapshot_max_bytes=SMALL_SNAPSHOT_CAP)
    store = PostgresTaskMemoryStore(dsn, schema=schema, config=config)
    if migrate:
        await store.apply_migrations()
    blobs = ArtifactBlobStore(fm, prefix="tm_3004")
    artifacts = PostgresArtifactStore(store, blobs=blobs, config=config)
    return _Pod(store, artifacts, config)


# ─────────────────────────────────────────────────────────────
# test_restart_primary
# ─────────────────────────────────────────────────────────────


async def test_restart_primary(pg: Tuple[str, str, Any]) -> None:
    """Continuity survives a full restart, with version-correct evidence."""
    dsn, schema, fm = pg
    scope = _scope()

    # ── pod 1: do the work ───────────────────────────────────────────
    pod = await _boot(dsn, schema, fm, migrate=True)
    try:
        begun = await pod.service.begin_task(
            scope,
            goal="reconcile the ledger",
            constraints=("never write to production", "use the nightly extract"),
            steps=[
                InitialStepSpec(label="load", title="load rows"),
                InitialStepSpec(label="verify", title="verify totals", depends_on_labels=("load",)),
            ],
        )
        task_id = begun.state.task_id
        step_load = begun.state.steps[0].step_id
        step_verify = begun.state.steps[1].step_id

        # A payload comfortably BELOW the cap: stays inline.
        small_ref = (await pod.artifacts.put(scope, "small_table", {"rows": [1, 2, 3]}, task_id=task_id)).ref
        # A payload ABOVE the cap: must be published to a blob.
        big_value = {"rows": ["x" * 256 for _ in range(64)]}
        big_ref = (await pod.artifacts.put(scope, "big_table", big_value, task_id=task_id)).ref

        small_before = await pod.artifacts.get_version(scope, small_ref, task_id=task_id)
        big_before = await pod.artifacts.get_version(scope, big_ref, task_id=task_id)
        assert big_before.availability is ArtifactAvailability.PERSISTED, (
            "sanity: a payload above the snapshot cap must be persisted to a blob, " f"got {big_before.availability}"
        )

        # Bind the BIG version as evidence, then overwrite the alias. The
        # bound version must stay valid: an overwrite is a new version,
        # not a mutation of the old one.
        await pod.artifacts.pin_evidence(scope, big_ref, task_id, step_id=step_load)
        completed = await pod.service.complete_step(
            pod_scope := scope,
            task_id,
            step_load,
            expected_revision=begun.state.revision,
            evidence_refs=(big_ref,),
            note="rows loaded and checked",
        )
        overwritten = (await pod.artifacts.put(scope, "big_table", {"rows": ["y"]}, task_id=task_id)).ref
        assert overwritten.version == big_ref.version + 1, "an overwrite must allocate the next version"

        revision_before = completed.state.revision
        fingerprint_before = big_before.fingerprint
    finally:
        await pod.close()

    # ── restart: every object rebuilt, nothing shared but the database ─
    restarted = await _boot(dsn, schema, fm)
    try:
        snapshot = await restarted.service.get_task(pod_scope, task_id)
        state = snapshot.state

        # The task and its plan survived.
        assert state.goal == "reconcile the ledger"
        assert state.revision == revision_before
        assert [s.title for s in state.steps] == ["load rows", "verify totals"]
        assert {c.text for c in state.active_constraints} == {
            "never write to production",
            "use the nightly extract",
        }
        # The completed step is still completed, with its evidence.
        by_id = state.steps_by_id
        assert by_id[step_load].status is StepStatus.COMPLETED
        assert big_ref in by_id[step_load].evidence_refs
        # And the next ready step is the one that was waiting on it.
        assert step_verify in state.ready_step_ids

        # Evidence is VERSION-CORRECT: the bound version still resolves to
        # the bytes it was bound to, even though a newer version exists.
        rebound = await restarted.artifacts.get_version(pod_scope, big_ref, task_id=task_id)
        assert rebound is not None
        assert rebound.fingerprint == fingerprint_before
        assert not rebound.invalidated

        current = await restarted.artifacts.get_current(pod_scope, "big_table", task_id=task_id)
        assert current.ref.version == big_ref.version + 1, "the alias moved on, as an overwrite should"

        # Both payloads reload — below the cap from the row, above it from
        # the blob written by a process that no longer exists.
        small_payload = await restarted.artifacts.load_payload(pod_scope, small_ref, max_bytes=1_000_000)
        assert small_payload.payload == {"rows": [1, 2, 3]}, small_payload.refusal
        big_payload = await restarted.artifacts.load_payload(pod_scope, big_ref, max_bytes=10_000_000)
        assert big_payload.refusal is None, big_payload.refusal
        assert big_payload.payload == {"rows": ["x" * 256 for _ in range(64)]}
    finally:
        await restarted.close()


async def test_restart_primary_completes_without_repeating_work(pg: Tuple[str, str, Any]) -> None:
    """After a restart the finished step is not offered again."""
    dsn, schema, fm = pg
    scope = _scope()
    pod = await _boot(dsn, schema, fm, migrate=True)
    try:
        begun = await pod.service.begin_task(
            scope,
            goal="two-step job",
            steps=[
                InitialStepSpec(label="a", title="first"),
                InitialStepSpec(label="b", title="second", depends_on_labels=("a",)),
            ],
            plan_complete=True,
        )
        task_id = begun.state.task_id
        first, second = (s.step_id for s in begun.state.steps)
        ref = (await pod.artifacts.put(scope, "out", {"ok": True}, task_id=task_id)).ref
        await pod.artifacts.pin_evidence(scope, ref, task_id, step_id=first)
        await pod.service.complete_step(
            scope,
            task_id,
            first,
            expected_revision=begun.state.revision,
            evidence_refs=(ref,),
            note="first step done",
        )
    finally:
        await pod.close()

    restarted = await _boot(dsn, schema, fm)
    try:
        state = (await restarted.service.get_task(scope, task_id)).state
        # The whole point of durability: the work already done is not
        # queued up again for the agent to redo.
        assert first not in state.ready_step_ids
        assert state.ready_step_ids == (second,)
        assert not state.can_complete, "one required step is still outstanding"
    finally:
        await restarted.close()


# ─────────────────────────────────────────────────────────────
# test_multi_pod
# ─────────────────────────────────────────────────────────────


async def test_multi_pod(pg: Tuple[str, str, Any]) -> None:
    """Two pods on one database: no gaps, no doubles, no scope crossing."""
    dsn, schema, fm = pg
    scope = _scope()
    other = _scope(session="sess-2")

    pod_a = await _boot(dsn, schema, fm, migrate=True)
    pod_b = await _boot(dsn, schema, fm)
    try:
        begun = await pod_a.service.begin_task(scope, goal="shared task", plan_complete=True)
        task_id = begun.state.task_id

        # ── concurrent appends: contiguous sequence, no gaps ──────────
        async def _decide(pod: _Pod, n: int) -> None:
            """Record a decision from one pod.

            Args:
                pod: The pod writing.
                n: Ordinal, to make the text distinct.
            """
            await pod.service.record_decision(scope, task_id, text=f"decision {n}")

        await asyncio.gather(*(_decide(pod_a if i % 2 == 0 else pod_b, i) for i in range(12)))

        page = await pod_a.store.list_events(scope, task_id, after_seq=0, limit=500)
        seqs = [e.seq for e in page.events]
        # Contiguity is the real assertion: an optimistic-append bug shows
        # up as a hole or a duplicate, not as a missing row.
        assert seqs == list(range(1, len(seqs) + 1)), f"sequence is not contiguous: {seqs}"
        assert len(set(seqs)) == len(seqs), "duplicate sequence numbers"
        state = (await pod_b.service.get_task(scope, task_id)).state
        assert len(state.active_decisions) == 12, "an append was lost"

        # ── concurrent alias writes: distinct versions, one winner ────
        refs = await asyncio.gather(
            *(
                (pod_a if i % 2 == 0 else pod_b).artifacts.put(scope, "contended", {"i": i}, task_id=task_id)
                for i in range(8)
            )
        )
        versions = sorted(d.ref.version for d in refs)
        assert versions == list(range(1, 9)), f"versions collided or skipped: {versions}"
        current = await pod_a.artifacts.get_current(scope, "contended", task_id=task_id)
        assert current.ref.version == 8, "the alias must point at the highest version"

        # ── no double terminalization ─────────────────────────────────
        revision = (await pod_a.service.get_task(scope, task_id)).state.revision
        outcomes = await asyncio.gather(
            pod_a.service.update_task(scope, task_id, expected_revision=revision, status=TaskStatus.CANCELLED),
            pod_b.service.update_task(scope, task_id, expected_revision=revision, status=TaskStatus.CANCELLED),
            return_exceptions=True,
        )
        succeeded = [o for o in outcomes if not isinstance(o, BaseException)]
        assert len(succeeded) == 1, f"both pods terminalized the same task: {outcomes}"
        final = (await pod_b.service.get_task(scope, task_id)).state
        assert final.status is TaskStatus.CANCELLED
        # Exactly one terminal event, not two.
        events = await pod_a.store.list_events(scope, task_id, after_seq=0, limit=500)
        terminal = [
            e for e in events.events if e.event_type.value in {"task_cancelled", "task_completed", "task_failed"}
        ]
        assert len(terminal) == 1, [e.event_type.value for e in terminal]

        # ── scope isolation: the other scope simply cannot see it ─────
        from parrot.tools.working_memory.task_memory.service import TaskNotFound

        with pytest.raises((TaskNotFound, Exception)) as exc:
            await pod_b.service.get_task(other, task_id)
        assert "not found" in str(exc.value).lower() or exc.type.__name__ in {
            "TaskNotFound",
            "ScopeViolation",
        }
        other_page = await pod_b.store.list_tasks(other, limit=50)
        assert other_page.items == (), "a task leaked across scopes"
    finally:
        await pod_a.close()
        await pod_b.close()


async def test_multi_pod_lease_has_exactly_one_holder(pg: Tuple[str, str, Any]) -> None:
    """Only one pod may hold a task's append lease at a time."""
    dsn, schema, fm = pg
    redis = pytest.importorskip("redis.asyncio", reason="redis-py is required for the lease case")
    client = redis.from_url("redis://127.0.0.1:6379/9")
    try:
        await client.ping()
    except Exception:  # noqa: BLE001 — an unreachable Redis is a skip
        await client.aclose()
        pytest.skip(
            "no Redis reachable at 127.0.0.1:6379. ENVIRONMENTAL SKIP, not a pass — "
            "no lease behaviour was exercised."
        )

    from parrot.tools.working_memory.task_memory.association import TaskAssociationStore

    class _Mem:
        """Supplies the live client to the association store."""

        def __init__(self, redis_client: Any) -> None:
            self.redis = redis_client
            # `key_prefix` is the name the store actually reads. Getting
            # it wrong falls back to the shared default, which makes the
            # case non-isolated: a lease left by an earlier run blocks it.
            self.key_prefix = f"tm3004:{uuid.uuid4().hex[:8]}"

    scope = _scope()
    store = TaskAssociationStore(_Mem(client), TaskMemoryConfig(enabled=True))
    task_id = "TASK-lease-1"
    try:
        first = await store.acquire_lease(scope, task_id, "pod-a")
        second = await store.acquire_lease(scope, task_id, "pod-b")
        # Two pods, one lease. The second must be refused rather than
        # silently sharing it.
        assert first is True
        assert second is False

        # `acquire_lease` is strictly take-if-free, so even the holder is
        # refused a second acquire; renewal is a separate, owner-checked
        # operation. That separation is what makes renewal safe: it
        # compares the owner rather than blindly extending whatever is
        # there.
        assert await store.acquire_lease(scope, task_id, "pod-a") is False
        assert await store.renew_lease(scope, task_id, "pod-a") is True, "the holder must be able to renew"
        assert await store.renew_lease(scope, task_id, "pod-b") is False, "a non-holder must not renew"

        # Released by its owner, the lease becomes available again.
        assert await store.release_lease(scope, task_id, "pod-b") is False, "a non-holder must not release"
        assert await store.release_lease(scope, task_id, "pod-a") is True
        assert await store.acquire_lease(scope, task_id, "pod-b") is True
    finally:
        await client.aclose()
