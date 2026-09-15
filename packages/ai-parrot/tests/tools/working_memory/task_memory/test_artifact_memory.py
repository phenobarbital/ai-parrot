"""Unit tests for the in-memory versioned artifact backend (TASK-2976).

Three required cases from the task's Test Specification:

- ``test_alias_race`` — concurrent overwrite/drop/recreate preserves
  unique monotonic versions and old evidence.
- ``test_scope_pins`` — foreign scopes cannot read versions; multiple
  task pins prevent silent eviction.
- ``test_lru`` — capacity accounts for snapshot and live retained bytes,
  and bounded loads cannot exceed their ceiling.

The backend is also run against the shared ``ArtifactStoreConformance``
suite published by TASK-2972, so it cannot drift from the contract the
PostgreSQL backend will also have to satisfy.
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, List, Optional

import pandas as pd
import pytest
from parrot.interfaces.artifact_store import ArtifactStore, PayloadRefusal
from parrot.tools.working_memory.task_memory.artifacts import (
    CapacityReport,
    EvictionReason,
    InMemoryArtifactStore,
    InvalidationReceipt,
    SpillReceipt,
)
from parrot.tools.working_memory.task_memory.config import TaskMemoryConfig
from parrot.tools.working_memory.task_memory.models import (
    ArtifactAvailability,
    ArtifactKind,
    Attribution,
    CursorError,
    EvidenceRef,
    LimitExceeded,
    Limits,
    ScopeViolation,
    TaskScope,
)

from .test_contracts import SCOPE_A, SCOPE_B, SCOPE_C, ArtifactStoreConformance

# ─────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────


@pytest.fixture()
async def store() -> AsyncIterator[InMemoryArtifactStore]:
    """Yield a fresh store with the specification's default budgets."""
    backend = InMemoryArtifactStore()
    try:
        yield backend
    finally:
        await backend.close()


def tiny_config(**overrides: Any) -> TaskMemoryConfig:
    """Return a config with a deliberately small retention budget.

    Args:
        **overrides: Extra :class:`TaskMemoryConfig` fields.

    Returns:
        The configuration.
    """
    values: dict = {"memory_cache_max_bytes": 4_000}
    values.update(overrides)
    return TaskMemoryConfig(**values)


def frame(rows: int = 100) -> pd.DataFrame:
    """Return a deterministic numeric/string DataFrame.

    Args:
        rows: Row count.

    Returns:
        The frame.
    """
    return pd.DataFrame(
        {
            "n": range(rows),
            "v": [float(i) / 3 for i in range(rows)],
            "label": [f"row-{i:05d}" for i in range(rows)],
        }
    )


# ─────────────────────────────────────────────────────────────
# Shared conformance suite
# ─────────────────────────────────────────────────────────────


class TestInMemoryArtifactStoreConformance(ArtifactStoreConformance):
    """Runs TASK-2972's published conformance suite against this backend."""

    @pytest.fixture()
    async def artifacts(self) -> AsyncIterator[ArtifactStore]:
        """Yield a fresh in-memory backend."""
        backend = InMemoryArtifactStore()
        try:
            yield backend
        finally:
            await backend.close()


def test_backend_satisfies_the_protocol() -> None:
    """The concrete store is recognised as an ``ArtifactStore``."""
    assert isinstance(InMemoryArtifactStore(), ArtifactStore)


# ─────────────────────────────────────────────────────────────
# Alias identity, versioning and races
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_alias_race_concurrent_overwrites_get_unique_versions(
    store: InMemoryArtifactStore,
) -> None:
    """Concurrent writers to one alias never collide on a version.

    Snapshotting runs off the lock, so writers genuinely interleave;
    allocation is what serializes. If version minting were outside the
    lock two writers could both claim ``version=2``, and one would
    silently overwrite the other's evidence.
    """
    writers = 25
    results = await asyncio.gather(*(store.put(SCOPE_A, "sales", {"writer": n}, task_id="t-1") for n in range(writers)))

    versions = sorted(d.ref.version for d in results)
    assert versions == list(range(1, writers + 1)), "versions must be unique and contiguous"
    assert len({d.ref.artifact_id for d in results}) == 1, "an overwrite keeps one identity"

    current = await store.get_current(SCOPE_A, "sales", task_id="t-1")
    assert current is not None
    assert current.ref.version == writers, "the alias points at the highest version"

    # Every earlier version survives as resolvable evidence.
    for descriptor in results:
        resolved = await store.get_version(SCOPE_A, descriptor.ref)
        assert resolved is not None
        assert resolved.invalidated is False


@pytest.mark.asyncio
async def test_alias_race_drop_recreate_never_reuses_a_version(
    store: InMemoryArtifactStore,
) -> None:
    """A tombstoned identity continues its version counter after a drop.

    Restarting at ``1`` would let a fresh, unrelated value shadow
    still-pinned evidence that a completed step had bound.
    """
    first = await store.put(SCOPE_A, "sales", {"n": 1}, task_id="t-1")
    second = await store.put(SCOPE_A, "sales", {"n": 2}, task_id="t-1")
    assert (first.ref.version, second.ref.version) == (1, 2)

    assert await store.drop_alias(SCOPE_A, "sales", task_id="t-1") is True
    assert await store.get_current(SCOPE_A, "sales", task_id="t-1") is None

    recreated = await store.put(SCOPE_A, "sales", {"n": 3}, task_id="t-1")
    assert recreated.ref.artifact_id == first.ref.artifact_id
    assert recreated.ref.version == 3, "the counter survives the drop"

    # The old evidence is still exactly what it was.
    old = await store.get_version(SCOPE_A, first.ref)
    assert old is not None
    payload = await store.load_payload(SCOPE_A, first.ref, max_bytes=10_000)
    assert payload.ok and payload.payload == {"n": 1}


@pytest.mark.asyncio
async def test_alias_race_concurrent_drop_and_recreate_keeps_monotonicity(
    store: InMemoryArtifactStore,
) -> None:
    """Interleaved drops and writes still produce a strictly increasing series."""
    await store.put(SCOPE_A, "sales", {"seed": True}, task_id="t-1")

    async def write(n: int) -> EvidenceRef:
        descriptor = await store.put(SCOPE_A, "sales", {"n": n}, task_id="t-1")
        return descriptor.ref

    async def drop() -> None:
        await store.drop_alias(SCOPE_A, "sales", task_id="t-1")

    refs = await asyncio.gather(*(write(n) for n in range(10)), drop(), drop(), drop())
    versions = sorted(r.version for r in refs if isinstance(r, EvidenceRef))
    assert len(set(versions)) == len(versions), "no version was ever handed out twice"
    assert versions == sorted(versions)


@pytest.mark.asyncio
async def test_alias_race_namespaces_are_task_scoped(store: InMemoryArtifactStore) -> None:
    """The same key in two tasks is two independent identities."""
    a = await store.put(SCOPE_A, "sales", {"task": 1}, task_id="t-1")
    b = await store.put(SCOPE_A, "sales", {"task": 2}, task_id="t-2")
    unassociated = await store.put(SCOPE_A, "sales", {"task": None}, task_id=None)

    assert len({a.ref.artifact_id, b.ref.artifact_id, unassociated.ref.artifact_id}) == 3
    assert a.ref.version == b.ref.version == unassociated.ref.version == 1

    assert (await store.get_current(SCOPE_A, "sales", task_id="t-1")).ref == a.ref
    assert (await store.get_current(SCOPE_A, "sales", task_id="t-2")).ref == b.ref
    assert await store.get_current(SCOPE_A, "sales", task_id="t-99") is None


@pytest.mark.asyncio
async def test_alias_race_rejects_an_overlong_key(store: InMemoryArtifactStore) -> None:
    """A bounded field is bounded before anything is allocated."""
    with pytest.raises(LimitExceeded) as excinfo:
        await store.put(SCOPE_A, "k" * (Limits.MAX_IDENTIFIER + 1), {"n": 1}, task_id="t-1")
    assert excinfo.value.field == "artifact alias"
    assert (await store.list(SCOPE_A)).items == (), "a rejected put allocates nothing"


@pytest.mark.asyncio
async def test_alias_race() -> None:
    """Required aggregate case: concurrent overwrite/drop/recreate stays consistent."""
    backend = InMemoryArtifactStore()
    try:
        await test_alias_race_concurrent_overwrites_get_unique_versions(backend)
    finally:
        await backend.close()

    backend = InMemoryArtifactStore()
    try:
        await test_alias_race_drop_recreate_never_reuses_a_version(backend)
    finally:
        await backend.close()

    backend = InMemoryArtifactStore()
    try:
        await test_alias_race_concurrent_drop_and_recreate_keeps_monotonicity(backend)
    finally:
        await backend.close()


# ─────────────────────────────────────────────────────────────
# Scope isolation and evidence pins
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scope_pins_foreign_scopes_cannot_read(store: InMemoryArtifactStore) -> None:
    """A version resolves only in its own scope, and reads as absent elsewhere."""
    descriptor = await store.put(SCOPE_A, "sales", {"n": 1}, task_id="t-1")

    for foreign in (SCOPE_B, SCOPE_C):
        assert await store.get_version(foreign, descriptor.ref) is None
        assert await store.get_current(foreign, "sales", task_id="t-1") is None
        assert (await store.list(foreign)).items == ()

        result = await store.load_payload(foreign, descriptor.ref, max_bytes=1_000_000)
        assert not result.ok
        assert result.payload is None
        assert result.refusal == PayloadRefusal.MISSING

        assert await store.evict(foreign, descriptor.ref) is False
        assert await store.drop_alias(foreign, "sales", task_id="t-1") is False
        with pytest.raises(ScopeViolation):
            await store.invalidate(foreign, descriptor.ref, reason="not yours")

    # And the owner is unaffected by all of that.
    mine = await store.get_version(SCOPE_A, descriptor.ref)
    assert mine is not None and mine.invalidated is False


@pytest.mark.asyncio
async def test_scope_pins_cross_task_reference_is_not_implicit(store: InMemoryArtifactStore) -> None:
    """A same-scope version belonging to another task is not resolved by accident."""
    descriptor = await store.put(SCOPE_A, "sales", {"n": 1}, task_id="t-1")

    # Asking as t-1 resolves; asking as t-2 does not, because a cross-task
    # evidence reference must be explicit and validated.
    assert await store.get_version(SCOPE_A, descriptor.ref, task_id="t-1") is not None
    assert await store.get_version(SCOPE_A, descriptor.ref, task_id="t-2") is None
    # Without a task filter the scope alone authorizes the read.
    assert await store.get_version(SCOPE_A, descriptor.ref) is not None


@pytest.mark.asyncio
async def test_scope_pins_multiple_tasks_prevent_silent_eviction() -> None:
    """Pinned evidence outlives unpinned entries under memory pressure."""
    store = InMemoryArtifactStore(tiny_config())
    try:
        pinned = await store.put(SCOPE_A, "evidence", {"blob": "p" * 1_200}, task_id="t-1")
        assert await store.pin_evidence(SCOPE_A, pinned.ref, "t-1") is True
        assert await store.pin_evidence(SCOPE_A, pinned.ref, "t-2") is True
        assert await store.pins_for(SCOPE_A, pinned.ref) == ("t-1", "t-2")

        # Push well past the budget with unpinned entries.
        filler: List[EvidenceRef] = []
        for n in range(6):
            descriptor = await store.put(SCOPE_A, f"filler-{n}", {"blob": "f" * 1_200}, task_id="t-1")
            filler.append(descriptor.ref)

        survivor = await store.get_version(SCOPE_A, pinned.ref)
        assert survivor is not None
        assert survivor.availability is ArtifactAvailability.MEMORY, "pinned bytes survive"
        assert survivor.invalidated is False
        assert store.drain_receipts() == (), "no pinned evidence was sacrificed"

        # Something unpinned did go, and says so.
        evicted = [await store.get_version(SCOPE_A, ref) for ref in filler]
        assert any(d is not None and d.availability is ArtifactAvailability.MISSING for d in evicted)
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_scope_pins_unpinning_restores_evictability() -> None:
    """Deletion is deferred until *every* pin is gone, not just one."""
    store = InMemoryArtifactStore(tiny_config())
    try:
        descriptor = await store.put(SCOPE_A, "evidence", {"blob": "p" * 1_200}, task_id="t-1")
        await store.pin_evidence(SCOPE_A, descriptor.ref, "t-1")
        await store.pin_evidence(SCOPE_A, descriptor.ref, "t-2")

        assert await store.unpin_evidence(SCOPE_A, descriptor.ref, "t-1") is True
        assert await store.pins_for(SCOPE_A, descriptor.ref) == ("t-2",)

        # Still pinned by t-2, so pressure does not take it.
        for n in range(6):
            await store.put(SCOPE_A, f"filler-{n}", {"blob": "f" * 1_200}, task_id="t-1")
        alive = await store.get_version(SCOPE_A, descriptor.ref)
        assert alive is not None and alive.availability is ArtifactAvailability.MEMORY

        # Once the last pin goes it becomes an ordinary eviction candidate.
        assert await store.unpin_evidence(SCOPE_A, descriptor.ref, "t-2") is True
        assert await store.pins_for(SCOPE_A, descriptor.ref) == ()
        for n in range(6, 12):
            await store.put(SCOPE_A, f"filler-{n}", {"blob": "f" * 1_200}, task_id="t-1")
        gone = await store.get_version(SCOPE_A, descriptor.ref)
        assert gone is not None and gone.availability is ArtifactAvailability.MISSING
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_scope_pins_unretainable_evidence_is_invalidated_not_dropped() -> None:
    """When even pinned bytes must go, an explicit receipt is raised.

    Delivery A cannot promise retained bytes. What it *can* promise is
    that nothing is silently removed while a step still calls it valid.
    """
    store = InMemoryArtifactStore(tiny_config(memory_cache_max_bytes=2_000))
    try:
        # Both are pinned ATOMICALLY with registration. Pinning after the
        # fact would be too late: capacity is enforced at the end of put,
        # so an unpinned newcomer is simply evicted at birth and pinned
        # evidence is never reached.
        first = await store.put(SCOPE_A, "e1", {"blob": "a" * 1_500}, task_id="t-1", pin_for="t-1")
        assert await store.pins_for(SCOPE_A, first.ref) == ("t-1",)
        await store.put(SCOPE_A, "e2", {"blob": "b" * 1_500}, task_id="t-2", pin_for="t-2")

        receipts = store.drain_receipts()
        assert receipts, "sacrificing pinned evidence must produce a receipt"
        receipt = receipts[0]
        assert isinstance(receipt, InvalidationReceipt)
        assert receipt.reason == EvictionReason.CAPACITY_PINNED
        assert receipt.pinned_by
        assert receipt.released_bytes > 0

        sacrificed = await store.get_version(SCOPE_A, receipt.ref)
        assert sacrificed is not None
        assert sacrificed.invalidated is True, "a step must not keep calling this valid"
        assert sacrificed.availability is ArtifactAvailability.MISSING
        assert store.drain_receipts() == (), "receipts are drained exactly once"
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_scope_pins_a_late_pin_cannot_protect_an_evicted_newcomer() -> None:
    """Pinning after registration is too late, and the store says so.

    Capacity is enforced at the end of ``put``. A version that is not yet
    pinned is an ordinary eviction candidate, so under pressure it is
    evicted *at birth* — before any later pin could apply. This is why
    ``put(..., pin_for=...)`` exists; the test pins the hazard so the
    atomic form cannot be quietly dropped as redundant.
    """
    store = InMemoryArtifactStore(tiny_config(memory_cache_max_bytes=2_000))
    try:
        first = await store.put(SCOPE_A, "e1", {"blob": "a" * 1_500}, task_id="t-1", pin_for="t-1")

        # Registered without a pin, under pressure: evicted immediately.
        late = await store.put(SCOPE_A, "e2", {"blob": "b" * 1_500}, task_id="t-2")
        assert late.availability is ArtifactAvailability.MISSING
        assert (await store.get_version(SCOPE_A, first.ref)).availability is ArtifactAvailability.MEMORY

        # The pin still records, but there are no bytes left to protect.
        assert await store.pin_evidence(SCOPE_A, late.ref, "t-2") is True
        assert (await store.get_version(SCOPE_A, late.ref)).availability is ArtifactAvailability.MISSING
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_scope_pins_pin_of_unknown_version_is_false(store: InMemoryArtifactStore) -> None:
    """Pinning something that does not exist in this scope fails quietly."""
    descriptor = await store.put(SCOPE_A, "sales", {"n": 1}, task_id="t-1")
    assert await store.pin_evidence(SCOPE_B, descriptor.ref, "t-1") is False
    assert await store.unpin_evidence(SCOPE_A, descriptor.ref, "never-pinned") is False
    assert await store.pins_for(SCOPE_B, descriptor.ref) == ()


@pytest.mark.asyncio
async def test_scope_pins() -> None:
    """Required aggregate case: scope isolation and multi-task evidence pins."""
    backend = InMemoryArtifactStore()
    try:
        await test_scope_pins_foreign_scopes_cannot_read(backend)
        await test_scope_pins_cross_task_reference_is_not_implicit(backend)
    finally:
        await backend.close()

    await test_scope_pins_multiple_tasks_prevent_silent_eviction()
    await test_scope_pins_unpinning_restores_evictability()
    await test_scope_pins_unretainable_evidence_is_invalidated_not_dropped()
    await test_scope_pins_a_late_pin_cannot_protect_an_evicted_newcomer()


# ─────────────────────────────────────────────────────────────
# Capacity accounting and bounded loads
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_lru_accounts_retained_snapshot_bytes() -> None:
    """Capacity reflects the snapshots the store actually holds."""
    store = InMemoryArtifactStore(tiny_config(memory_cache_max_bytes=1_000_000))
    try:
        assert store.capacity().retained_bytes == 0

        descriptor = await store.put(SCOPE_A, "sales", {"blob": "x" * 5_000}, task_id="t-1")
        report = store.capacity()
        assert isinstance(report, CapacityReport)
        assert report.retained_bytes >= 5_000
        assert report.version_count == 1
        assert report.pinned_bytes == 0
        assert report.available_bytes == report.limit - report.retained_bytes
        assert descriptor.byte_size == report.retained_bytes
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_lru_accounts_live_references_for_unverifiable_values() -> None:
    """A retained *reference* is accounted too — it keeps the object alive.

    An unverifiable value is never copied, but the store still holds a
    reference to it, so reporting zero bytes would understate what is
    resident.
    """
    store = InMemoryArtifactStore(tiny_config(memory_cache_max_bytes=1_000_000))
    try:
        descriptor = await store.put(SCOPE_A, "raw", b"z" * 4_000, task_id="t-1")
        assert descriptor.kind is ArtifactKind.BINARY
        assert descriptor.evidence_verifiable is False, "binary carries no integrity claim"
        assert descriptor.availability is ArtifactAvailability.MEMORY

        assert store.capacity().retained_bytes >= 4_000, "the live reference is accounted"

        # It is still usable as working memory, just never as evidence.
        result = await store.load_payload(SCOPE_A, descriptor.ref, max_bytes=1_000_000)
        assert result.ok and result.payload == b"z" * 4_000
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_lru_evicts_least_recently_used_first() -> None:
    """Eviction follows access order, not insertion order."""
    store = InMemoryArtifactStore(tiny_config(memory_cache_max_bytes=3_500))
    try:
        a = await store.put(SCOPE_A, "a", {"blob": "a" * 1_000}, task_id="t-1")
        b = await store.put(SCOPE_A, "b", {"blob": "b" * 1_000}, task_id="t-1")
        c = await store.put(SCOPE_A, "c", {"blob": "c" * 1_000}, task_id="t-1")

        # Touch `a` so `b` becomes the least recently used.
        assert (await store.load_payload(SCOPE_A, a.ref, max_bytes=10_000)).ok

        await store.put(SCOPE_A, "d", {"blob": "d" * 1_000}, task_id="t-1")

        states = {
            "a": (await store.get_version(SCOPE_A, a.ref)).availability,
            "b": (await store.get_version(SCOPE_A, b.ref)).availability,
            "c": (await store.get_version(SCOPE_A, c.ref)).availability,
        }
        assert states["b"] is ArtifactAvailability.MISSING, "the least recently used went first"
        assert states["a"] is ArtifactAvailability.MEMORY, "a recent touch protected it"
        assert store.capacity().retained_bytes <= 3_500
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_lru_eviction_keeps_a_metadata_tombstone() -> None:
    """Losing the bytes never loses the descriptor."""
    store = InMemoryArtifactStore(tiny_config(memory_cache_max_bytes=1_500))
    try:
        first = await store.put(SCOPE_A, "a", {"blob": "a" * 1_200}, task_id="t-1")
        fingerprint = first.fingerprint
        assert fingerprint is not None

        await store.put(SCOPE_A, "b", {"blob": "b" * 1_200}, task_id="t-1")

        tombstone = await store.get_version(SCOPE_A, first.ref)
        assert tombstone is not None, "the descriptor survives"
        assert tombstone.availability is ArtifactAvailability.MISSING
        assert tombstone.fingerprint == fingerprint, "the fingerprint still describes it"
        assert store.capacity().tombstone_count >= 1

        result = await store.load_payload(SCOPE_A, first.ref, max_bytes=1_000_000)
        assert not result.ok and result.payload is None
        assert result.refusal == PayloadRefusal.MISSING
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_lru_bounded_loads_cannot_exceed_their_ceiling(store: InMemoryArtifactStore) -> None:
    """A read over the ceiling refuses; it never loads then truncates."""
    descriptor = await store.put(SCOPE_A, "big", {"blob": "x" * 20_000}, task_id="t-1")
    size = descriptor.byte_size
    assert size is not None and size > 20_000

    refused = await store.load_payload(SCOPE_A, descriptor.ref, max_bytes=size - 1)
    assert not refused.ok
    assert refused.payload is None
    assert refused.refusal == PayloadRefusal.TOO_LARGE
    assert refused.byte_size == size, "a refusal still says how far over it was"
    assert refused.guidance

    exact = await store.load_payload(SCOPE_A, descriptor.ref, max_bytes=size)
    assert exact.ok, "the ceiling is inclusive"
    assert exact.returned_bytes == size

    never = await store.load_payload(SCOPE_A, descriptor.ref, max_bytes=0)
    assert not never.ok and never.payload is None

    with pytest.raises(ValueError):
        await store.load_payload(SCOPE_A, descriptor.ref, max_bytes=-1)


@pytest.mark.asyncio
async def test_lru_tabular_page_reads_without_rehydrating_the_table(
    store: InMemoryArtifactStore,
) -> None:
    """A small page is readable from a table far over the ceiling."""
    descriptor = await store.put(SCOPE_A, "table", frame(5_000), task_id="t-1")
    assert descriptor.kind is ArtifactKind.DATAFRAME
    total = descriptor.byte_size
    assert total is not None

    # The whole table is refused...
    whole = await store.load_payload(SCOPE_A, descriptor.ref, max_bytes=1_000)
    assert not whole.ok and whole.refusal == PayloadRefusal.TOO_LARGE

    # ...but a bounded page of it is not.
    page = await store.load_payload(SCOPE_A, descriptor.ref, max_bytes=total, offset=10, limit=5)
    assert page.ok
    assert len(page.payload) == 5
    assert page.offset == 10
    assert page.limit == 5
    assert page.total_rows == 5_000
    assert page.truncated is True
    assert page.returned_bytes < total, "only the page was materialized"
    assert list(page.payload["n"]) == list(range(10, 15))

    # Even a page must fit; an over-ceiling page is refused, not trimmed.
    too_big = await store.load_payload(SCOPE_A, descriptor.ref, max_bytes=10, offset=0, limit=1_000)
    assert not too_big.ok
    assert too_big.payload is None
    assert too_big.refusal == PayloadRefusal.TOO_LARGE


@pytest.mark.asyncio
async def test_lru_page_limit_is_clamped_to_configuration(store: InMemoryArtifactStore) -> None:
    """A caller cannot page past the configured maximum row count."""
    descriptor = await store.put(SCOPE_A, "table", frame(3_000), task_id="t-1")
    page = await store.load_payload(SCOPE_A, descriptor.ref, max_bytes=10_000_000, offset=0, limit=99_999)
    assert page.ok
    assert page.limit == TaskMemoryConfig().raw_page_limit_max == 1_000
    assert len(page.payload) == 1_000


@pytest.mark.asyncio
async def test_lru_explicit_eviction_moves_the_availability_generation(
    store: InMemoryArtifactStore,
) -> None:
    """Availability changes without a task event must move the generation.

    Recall's cache key folds this in, which is what stops "deterministic"
    from meaning "expired content stays available forever".
    """
    descriptor = await store.put(SCOPE_A, "sales", {"n": 1}, task_id="t-1")
    before = (await store.list(SCOPE_A)).availability_generation

    assert await store.evict(SCOPE_A, descriptor.ref) is True
    after = (await store.list(SCOPE_A)).availability_generation
    assert after > before

    # Evicting again reclaims nothing and is reported honestly.
    assert await store.evict(SCOPE_A, descriptor.ref) is False

    # Explicit eviction is not invalidation: the caller asked for the
    # bytes back, and the fingerprint still describes what was there.
    tombstone = await store.get_version(SCOPE_A, descriptor.ref)
    assert tombstone is not None
    assert tombstone.invalidated is False
    assert tombstone.availability is ArtifactAvailability.MISSING


@pytest.mark.asyncio
async def test_lru_evicting_pinned_evidence_raises_a_receipt(store: InMemoryArtifactStore) -> None:
    """Explicitly evicting pinned evidence still produces a receipt."""
    descriptor = await store.put(SCOPE_A, "sales", {"n": 1}, task_id="t-1")
    await store.pin_evidence(SCOPE_A, descriptor.ref, "t-1")

    assert await store.evict(SCOPE_A, descriptor.ref) is True
    receipts = store.drain_receipts()
    assert len(receipts) == 1
    assert receipts[0].reason == EvictionReason.EXPLICIT
    assert receipts[0].pinned_by == ("t-1",)

    updated = await store.get_version(SCOPE_A, descriptor.ref)
    assert updated is not None and updated.invalidated is True


@pytest.mark.asyncio
async def test_lru() -> None:
    """Required aggregate case: capacity accounting and bounded loads."""
    await test_lru_accounts_retained_snapshot_bytes()
    await test_lru_accounts_live_references_for_unverifiable_values()
    await test_lru_evicts_least_recently_used_first()
    await test_lru_eviction_keeps_a_metadata_tombstone()

    backend = InMemoryArtifactStore()
    try:
        await test_lru_bounded_loads_cannot_exceed_their_ceiling(backend)
        await test_lru_tabular_page_reads_without_rehydrating_the_table(backend)
        await test_lru_page_limit_is_clamped_to_configuration(backend)
        await test_lru_explicit_eviction_moves_the_availability_generation(backend)
    finally:
        await backend.close()


# ─────────────────────────────────────────────────────────────
# Evidence honesty, spill protocol and listing
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_nested_mutable_frame_is_never_verifiable(store: InMemoryArtifactStore) -> None:
    """The store never launders a repr hash into an integrity claim.

    Phase 0 measured that pandas silently hashes unhashable object cells
    via their ``str`` repr. The snapshot layer refuses to call that
    evidence, and this store records that refusal rather than overriding
    it.
    """
    nested = pd.DataFrame({"v": [1.0, 2.0], "obj": pd.Series([{"a": 1}, {"b": 2}], dtype="object")})
    descriptor = await store.put(SCOPE_A, "nested", nested, task_id="t-1")

    assert descriptor.evidence_verifiable is False
    assert descriptor.fingerprint is None

    clean = await store.put(SCOPE_A, "clean", frame(10), task_id="t-1")
    assert clean.evidence_verifiable is True
    assert clean.fingerprint is not None


@pytest.mark.asyncio
async def test_oversized_value_without_a_durable_tier_is_unverifiable() -> None:
    """With nothing retaining it, an oversized value is recorded honestly."""
    store = InMemoryArtifactStore(TaskMemoryConfig(snapshot_max_bytes=100))
    try:
        descriptor = await store.put(SCOPE_A, "big", {"blob": "x" * 5_000}, task_id="t-1")
        assert descriptor.evidence_verifiable is False
        assert descriptor.fingerprint is None
        assert descriptor.availability is ArtifactAvailability.MISSING
        assert descriptor.byte_size and descriptor.byte_size > 5_000, "metadata is still bounded and honest"
        assert descriptor.storage_ref is None
        assert store.capacity().retained_bytes == 0, "nothing was retained"

        result = await store.load_payload(SCOPE_A, descriptor.ref, max_bytes=1_000_000)
        assert not result.ok and result.payload is None
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_spill_handler_makes_an_oversized_value_persisted() -> None:
    """A configured durable tier takes the bytes and the version says so."""

    class _Spill:
        """Minimal test double for the durable tier."""

        def __init__(self) -> None:
            self.calls: List[Any] = []

        async def spill(self, scope: TaskScope, ref: EvidenceRef, kind: ArtifactKind, value: Any) -> SpillReceipt:
            self.calls.append((scope, kind))
            return SpillReceipt(storage_ref="blob://bucket/x", byte_size=5_011)

        async def load(self, scope: TaskScope, ref: EvidenceRef, storage_ref: str, *, max_bytes: int) -> Any:
            raise NotImplementedError

    handler = _Spill()
    store = InMemoryArtifactStore(TaskMemoryConfig(snapshot_max_bytes=100), spill_handler=handler)
    try:
        descriptor = await store.put(SCOPE_A, "big", {"blob": "x" * 5_000}, task_id="t-1")
        assert handler.calls, "the durable tier was offered the value"
        assert descriptor.availability is ArtifactAvailability.PERSISTED
        assert descriptor.storage_ref == "blob://bucket/x"
        assert descriptor.byte_size == 5_011
        # The tier returned no fingerprint, so no integrity claim is made.
        assert descriptor.evidence_verifiable is False
    finally:
        await store.close()


@pytest.mark.asyncio
async def test_descriptor_carries_producer_correlation(store: InMemoryArtifactStore) -> None:
    """Provenance supplied at registration is retained on the descriptor."""
    descriptor = await store.put(
        SCOPE_A,
        "sales",
        {"n": 1},
        task_id="t-1",
        producer_call_id="call-42",
        attribution=Attribution.DECLARED,
        turn_id="turn-7",
    )
    assert descriptor.producer_call_id == "call-42"
    assert descriptor.attribution is Attribution.DECLARED
    assert descriptor.task_id == "t-1"
    assert descriptor.alias == "sales"


@pytest.mark.asyncio
async def test_listing_filters_by_kind_and_pages_with_a_scoped_cursor(
    store: InMemoryArtifactStore,
) -> None:
    """Listings are filtered, bounded and cursor-validated."""
    for n in range(4):
        await store.put(SCOPE_A, f"j{n}", {"n": n}, task_id="t-1")
    await store.put(SCOPE_A, "table", frame(5), task_id="t-1")

    frames = await store.list(SCOPE_A, task_id="t-1", kinds=[ArtifactKind.DATAFRAME])
    assert len(frames.items) == 1
    assert frames.items[0].kind is ArtifactKind.DATAFRAME

    first = await store.list(SCOPE_A, task_id="t-1", limit=2)
    assert len(first.items) == 2 and first.next_cursor is not None
    second = await store.list(SCOPE_A, task_id="t-1", limit=2, cursor=first.next_cursor)
    assert {d.ref for d in first.items}.isdisjoint({d.ref for d in second.items})

    # A cursor is bound to its scope AND its query.
    with pytest.raises(CursorError):
        await store.list(SCOPE_B, task_id="t-1", limit=2, cursor=first.next_cursor)
    with pytest.raises(CursorError):
        await store.list(SCOPE_A, task_id="t-2", limit=2, cursor=first.next_cursor)
    with pytest.raises(CursorError):
        await store.list(SCOPE_A, task_id="t-1", limit=0)


@pytest.mark.asyncio
async def test_invalidate_leaves_bytes_but_withdraws_the_claim(store: InMemoryArtifactStore) -> None:
    """Invalidation is about evidence, not storage."""
    descriptor = await store.put(SCOPE_A, "sales", frame(10), task_id="t-1")
    assert descriptor.evidence_verifiable is True

    updated = await store.invalidate(SCOPE_A, descriptor.ref, reason="source mutated")
    assert updated.invalidated is True
    assert updated.invalidated_at is not None
    assert updated.evidence_verifiable is False, "the claim is withdrawn"
    assert updated.availability is ArtifactAvailability.MEMORY, "the bytes are untouched"

    # And it remains loadable, exactly as the contract says.
    result = await store.load_payload(SCOPE_A, descriptor.ref, max_bytes=10_000_000)
    assert result.ok


@pytest.mark.asyncio
async def test_transaction_is_a_usable_no_op(store: InMemoryArtifactStore) -> None:
    """The in-memory transaction handle satisfies the shared shape."""
    async with store.transaction() as tx:
        assert tx.is_active is True
        descriptor = await store.put(SCOPE_A, "sales", {"n": 1}, task_id="t-1", transaction=tx)
        assert descriptor.ref.version == 1

    with pytest.raises(RuntimeError):
        async with store.transaction() as tx:
            raise RuntimeError("boom")
    assert tx.is_active is False, "an error rolls the handle back"


@pytest.mark.asyncio
async def test_close_releases_everything(store: InMemoryArtifactStore) -> None:
    """Closing drops payloads, aliases and accounting together."""
    descriptor = await store.put(SCOPE_A, "sales", {"blob": "x" * 2_000}, task_id="t-1")
    assert store.capacity().retained_bytes > 0

    await store.close()
    assert store.capacity().retained_bytes == 0
    assert await store.get_version(SCOPE_A, descriptor.ref) is None
    assert await store.get_current(SCOPE_A, "sales", task_id="t-1") is None
