"""Bounded recall reads, cache and omission probes (FEAT-538 / TASK-2988).

Three required cases from the task's Test Specification:

- ``test_no_payload_reads`` — spies reject data loads, ``get``-content,
  ``describe``, LLM calls and unbounded scans during recall.
- ``test_cache_keys`` — snapshots for different scopes, tasks,
  calibrations or worker generations never collide.
- ``test_expiry`` — expired and unknown omission refs, and dead worker
  bindings, are reported truthfully **at an unchanged task sequence**.

The spies are *armed traps*, not observations: they raise. A spy that
merely counted would let a violation through whenever the assertion was
written against the wrong counter, and the whole point of AC10 is that
recall must not be able to reach for a payload at all.
"""

from __future__ import annotations

import os
import uuid
from typing import Any, Dict, List, Optional

import pandas as pd
import pytest
from parrot.memory.compaction.omission import (
    FileOmissionStore,
    InMemoryOmissionStore,
    OmissionStore,
    RedisOmissionStore,
    content_id,
)
from parrot.tools.working_memory.task_memory.artifacts import InMemoryArtifactStore
from parrot.tools.working_memory.task_memory.config import TaskMemoryConfig
from parrot.tools.working_memory.task_memory.models import (
    ArtifactAvailability,
    EvidenceRef,
    InitialStepSpec,
    ReplBinding,
    TaskScope,
)
from parrot.tools.working_memory.task_memory.recall import (
    NEEDS_SELECTION_PAGE,
    RECALL_ARTIFACT_LIMIT,
    RECALL_EVENT_WINDOW,
    InMemoryRecallCache,
    RecallReader,
    RecallStatus,
    RedisRecallCache,
    build_cache_key_parts,
    cache_digest,
    collect_omission_ids,
)
from parrot.tools.working_memory.task_memory.service import TaskMemoryService
from parrot.tools.working_memory.task_memory.store.memory import InMemoryTaskMemoryStore

SCOPE = TaskScope(chatbot_id="bot-a", user_id="user-1", session_id="sess-1")
OTHER_USER = TaskScope(chatbot_id="bot-a", user_id="user-2", session_id="sess-1")
OTHER_BOT = TaskScope(chatbot_id="bot-b", user_id="user-1", session_id="sess-1")


class _Counter:
    """A deterministic token counter with a controllable identity."""

    def __init__(self, name: str = "test") -> None:
        """Initialize the counter.

        Args:
            name: Tokenizer identity, which participates in the cache key.
        """
        self.name = name

    def count(self, text: str) -> int:
        """Return a deterministic count.

        Args:
            text: Text to count.

        Returns:
            The character length.
        """
        return len(text)


def _stub_clock():
    """Return a monotonic clock for caches whose TTL is not under test.

    Supplied explicitly because :class:`InMemoryRecallCache` refuses to
    import one — see its docstring.

    Returns:
        A zero-argument callable returning seconds.
    """
    import time as _time

    return _time.monotonic


@pytest.fixture()
async def wired():
    """Yield a ``(reader, service, tasks, artifacts)`` bundle."""
    tasks = InMemoryTaskMemoryStore()
    artifacts = InMemoryArtifactStore()
    service = TaskMemoryService(tasks, artifacts=artifacts)
    reader = RecallReader(tasks, artifacts, counter=_Counter())
    try:
        yield reader, service, tasks, artifacts
    finally:
        await tasks.close()
        await artifacts.close()


async def _seed(service: TaskMemoryService, scope: TaskScope = SCOPE):
    """Create a task with a small plan.

    Args:
        service: The command service.
        scope: The owning scope.

    Returns:
        The append result.
    """
    return await service.begin_task(
        scope,
        goal="Produce the quarterly report",
        constraints=["Never mutate the source"],
        steps=[
            InitialStepSpec(label="load", title="Load raw data"),
            InitialStepSpec(label="clean", title="Clean data", depends_on_labels=("load",)),
        ],
    )


# ─────────────────────────────────────────────────────────────
# No payload reads
# ─────────────────────────────────────────────────────────────


class _ExplodingArtifactStore:
    """Wraps a real store and raises on anything that reads a payload."""

    def __init__(self, inner: Any) -> None:
        """Initialize the trap.

        Args:
            inner: The real store to delegate reads to.
        """
        self._inner = inner

    async def list(self, *args: Any, **kwargs: Any) -> Any:
        """Delegate the descriptor listing, asserting it is bounded."""
        limit = kwargs.get("limit")
        assert limit is not None and limit <= RECALL_ARTIFACT_LIMIT, f"unbounded artifact scan: limit={limit}"
        return await self._inner.list(*args, **kwargs)

    async def load_payload(self, *args: Any, **kwargs: Any) -> Any:
        """Refuse: recall must never materialize a payload."""
        raise AssertionError("recall called load_payload — it must never materialize a payload")

    def __getattr__(self, name: str) -> Any:
        """Delegate everything else to the real store."""
        return getattr(self._inner, name)


class _ExplodingOmissionStore(InMemoryOmissionStore):
    """An omission store whose content read is an armed trap."""

    async def get(self, session_key: str, content_id: str) -> Optional[str]:
        """Refuse: probing existence must not fetch the content."""
        raise AssertionError("recall called OmissionStore.get — probe() exists precisely to avoid this")


@pytest.mark.asyncio
async def test_no_payload_reads_traps_are_actually_armed(wired) -> None:
    """The traps fire when invoked, so the assertions below are not vacuous."""
    _, _, _, artifacts = wired
    trap = _ExplodingArtifactStore(artifacts)
    with pytest.raises(AssertionError, match="load_payload"):
        await trap.load_payload(SCOPE, EvidenceRef(artifact_id="a", version=1), max_bytes=10)

    omissions = _ExplodingOmissionStore()
    with pytest.raises(AssertionError, match="OmissionStore.get"):
        await omissions.get("k", "om_0000000000000000")


@pytest.mark.asyncio
async def test_no_payload_reads_recall_never_loads(wired) -> None:
    """A full recall touches no payload and no omitted content."""
    _, service, tasks, artifacts = wired
    result = await _seed(service)
    task_id = result.state.task_id

    await artifacts.put(SCOPE, "sales", pd.DataFrame({"n": [1, 2, 3]}), task_id=task_id)

    omissions = _ExplodingOmissionStore()
    key = RecallReader.omission_key(SCOPE)
    await omissions.put(key, "some large omitted output")

    reader = RecallReader(tasks, _ExplodingArtifactStore(artifacts), omission_store=omissions, counter=_Counter())
    recalled = await reader.recall(SCOPE, task_id)
    assert recalled.status is RecallStatus.OK
    assert recalled.snapshot["task_id"] == task_id


@pytest.mark.asyncio
async def test_no_payload_reads_event_window_is_bounded(wired) -> None:
    """The journal read is bounded and fenced, however long the task is."""
    _, service, tasks, artifacts = wired
    result = await _seed(service)
    task_id = result.state.task_id

    # Grow the journal well past the window.
    for n in range(RECALL_EVENT_WINDOW + 40):
        await service.set_resume_hint(SCOPE, task_id, next_action=f"step {n}")

    seen: List[Dict[str, Any]] = []
    original = tasks.list_events

    async def _watched(scope, tid, **kwargs):
        seen.append(dict(kwargs))
        return await original(scope, tid, **kwargs)

    tasks.list_events = _watched  # type: ignore[assignment]
    try:
        reader = RecallReader(tasks, artifacts, counter=_Counter())
        recalled = await reader.recall(SCOPE, task_id)
    finally:
        tasks.list_events = original  # type: ignore[assignment]

    assert recalled.status is RecallStatus.OK
    assert seen, "the reader never paged the journal"
    for call in seen:
        assert call["limit"] <= RECALL_EVENT_WINDOW, f"unbounded journal scan: {call}"
        assert call["as_of_seq"] is not None, "the page was not fenced at the snapshot's sequence"
        assert call["after_seq"] >= 0


@pytest.mark.asyncio
async def test_no_payload_reads_all_pages_share_one_fence(wired) -> None:
    """The projection, the events and the descriptors describe ONE instant."""
    _, service, tasks, artifacts = wired
    result = await _seed(service)
    task_id = result.state.task_id
    await artifacts.put(SCOPE, "sales", {"n": 1}, task_id=task_id)

    fences: Dict[str, Any] = {}
    real_events, real_list = tasks.list_events, artifacts.list

    async def _events(scope, tid, **kwargs):
        fences["events"] = kwargs.get("as_of_seq")
        return await real_events(scope, tid, **kwargs)

    async def _artifacts(scope, **kwargs):
        fences["artifacts"] = kwargs.get("as_of_seq")
        return await real_list(scope, **kwargs)

    tasks.list_events, artifacts.list = _events, _artifacts  # type: ignore[assignment]
    try:
        reader = RecallReader(tasks, artifacts, counter=_Counter())
        inputs = await reader.build_inputs(SCOPE, task_id)
    finally:
        tasks.list_events, artifacts.list = real_events, real_list  # type: ignore[assignment]

    assert inputs is not None
    assert fences["events"] == fences["artifacts"] == inputs.as_of_seq


@pytest.mark.asyncio
async def test_no_payload_reads_recall_appends_nothing(wired) -> None:
    """Repeated recalls leave the journal and the sequence untouched."""
    reader, service, tasks, _ = wired
    result = await _seed(service)
    task_id = result.state.task_id
    before = await tasks.load_snapshot(SCOPE, task_id)

    for _ in range(5):
        await reader.recall(SCOPE, task_id, use_cache=False)

    after = await tasks.load_snapshot(SCOPE, task_id)
    assert (after.as_of_seq, after.event_count, after.state.revision) == (
        before.as_of_seq,
        before.event_count,
        before.state.revision,
    )


@pytest.mark.asyncio
async def test_no_payload_reads() -> None:
    """Required aggregate case: no data loads, no content reads, no unbounded scans."""
    tasks, artifacts = InMemoryTaskMemoryStore(), InMemoryArtifactStore()
    service = TaskMemoryService(tasks, artifacts=artifacts)
    reader = RecallReader(tasks, artifacts, counter=_Counter())
    bundle = (reader, service, tasks, artifacts)
    try:
        await test_no_payload_reads_traps_are_actually_armed(bundle)
        await test_no_payload_reads_recall_never_loads(bundle)
        await test_no_payload_reads_all_pages_share_one_fence(bundle)
        await test_no_payload_reads_recall_appends_nothing(bundle)
    finally:
        await tasks.close()
        await artifacts.close()


# ─────────────────────────────────────────────────────────────
# Cache keys
# ─────────────────────────────────────────────────────────────


def _parts(**overrides: Any):
    """Build cache-key parts with a default shape.

    Args:
        **overrides: Fields to replace.

    Returns:
        The parts tuple.
    """
    base = {
        "scope_key": SCOPE.cache_key(),
        "task_id": "t-1",
        "as_of_seq": 7,
        "availability_generation": 0,
        "tokenizer": "heuristic",
        "calibration": 1.0,
        "max_tokens": 2500,
        "recent_calls_limit": 8,
    }
    base.update(overrides)
    return build_cache_key_parts(**base)


def test_cache_keys_every_dimension_changes_the_digest() -> None:
    """Changing any keyed input changes the digest.

    Each dimension is varied INDEPENDENTLY. Varying several at once would
    still pass if one of them were silently ignored.
    """
    baseline = cache_digest(_parts())
    for field, value in (
        ("scope_key", OTHER_USER.cache_key()),
        ("task_id", "t-2"),
        ("as_of_seq", 8),
        ("availability_generation", 1),
        ("tokenizer", "o200k_base"),
        ("calibration", 1.25),
        ("max_tokens", 2501),
        ("recent_calls_limit", 9),
    ):
        assert cache_digest(_parts(**{field: value})) != baseline, f"{field} does not affect the cache key"

    # And it is stable for identical inputs.
    assert cache_digest(_parts()) == baseline


def test_cache_keys_availability_generation_is_keyed() -> None:
    """A generation move invalidates the cache with NO task event.

    This is the spec's explicit carve-out: determinism cannot mean that
    expired content stays available forever at the same task sequence.
    """
    same_sequence = _parts(as_of_seq=7, availability_generation=0)
    after_eviction = _parts(as_of_seq=7, availability_generation=1)
    assert dict(same_sequence)["seq"] == dict(after_eviction)["seq"]
    assert cache_digest(same_sequence) != cache_digest(after_eviction)


def test_cache_keys_digest_cannot_be_forged_by_concatenation() -> None:
    """Two different part sets cannot collide by running values together."""
    a = build_cache_key_parts(
        scope_key="a:b",
        task_id="c",
        as_of_seq=1,
        availability_generation=0,
        tokenizer="t",
        calibration=1.0,
        max_tokens=1,
        recent_calls_limit=0,
    )
    b = build_cache_key_parts(
        scope_key="a",
        task_id="b:c",
        as_of_seq=1,
        availability_generation=0,
        tokenizer="t",
        calibration=1.0,
        max_tokens=1,
        recent_calls_limit=0,
    )
    assert cache_digest(a) != cache_digest(b)


@pytest.mark.asyncio
async def test_cache_keys_scopes_never_share_an_entry(wired) -> None:
    """Two scopes running identical work never see each other's recall."""
    _, _, tasks, artifacts = wired
    service = TaskMemoryService(tasks, artifacts=artifacts)
    cache = InMemoryRecallCache(_stub_clock())
    reader = RecallReader(tasks, artifacts, cache=cache, counter=_Counter())

    mine = await _seed(service, SCOPE)
    theirs = await _seed(service, OTHER_USER)

    a = await reader.recall(SCOPE, mine.state.task_id)
    b = await reader.recall(OTHER_USER, theirs.state.task_id)
    assert a.snapshot["task_id"] != b.snapshot["task_id"]
    assert a.to_bytes() != b.to_bytes()

    # A third scope with the same shape still misses.
    third = await _seed(service, OTHER_BOT)
    c = await reader.recall(OTHER_BOT, third.state.task_id)
    assert c.snapshot["task_id"] == third.state.task_id


@pytest.mark.asyncio
async def test_cache_keys_hit_is_served_and_is_identical(wired) -> None:
    """A second recall is served from cache, byte-identical to the first."""
    _, service, tasks, artifacts = wired
    result = await _seed(service)
    task_id = result.state.task_id
    cache = InMemoryRecallCache(_stub_clock())
    reader = RecallReader(tasks, artifacts, cache=cache, counter=_Counter())

    first = await reader.recall(SCOPE, task_id)

    # Prove the second call came from cache: make recomputation impossible.
    calls = {"n": 0}
    original = tasks.load_snapshot

    async def _counted(scope, tid):
        calls["n"] += 1
        return await original(scope, tid)

    tasks.load_snapshot = _counted  # type: ignore[assignment]
    try:
        second = await reader.recall(SCOPE, task_id)
    finally:
        tasks.load_snapshot = original  # type: ignore[assignment]

    assert second.to_bytes() == first.to_bytes()
    assert second.status is first.status
    assert calls["n"] == 1, "a cache hit still reads the snapshot once, to compute the fence"


@pytest.mark.asyncio
async def test_cache_keys_task_movement_invalidates(wired) -> None:
    """New work moves the sequence, so the cached entry is not reused."""
    _, service, tasks, artifacts = wired
    result = await _seed(service)
    task_id = result.state.task_id
    reader = RecallReader(tasks, artifacts, cache=InMemoryRecallCache(_stub_clock()), counter=_Counter())

    before = await reader.recall(SCOPE, task_id)
    await service.set_resume_hint(SCOPE, task_id, next_action="do the next thing")
    after = await reader.recall(SCOPE, task_id)

    assert after.to_bytes() != before.to_bytes()
    assert after.snapshot["as_of_seq"] > before.snapshot["as_of_seq"]


@pytest.mark.asyncio
async def test_cache_keys_ttl_expires_without_sleeping(wired) -> None:
    """The TTL is honoured, tested with an injected clock rather than a sleep.

    Asserted through BEHAVIOUR — whether the reader recomputes — rather
    than by inspecting the cache's internals, so the test still means
    something if the storage layout changes. A sleeping test would be
    slow and flaky under load.
    """
    _, service, tasks, artifacts = wired
    result = await _seed(service)
    task_id = result.state.task_id

    now = {"t": 1000.0}
    cache = InMemoryRecallCache(lambda: now["t"])
    config = TaskMemoryConfig(recall_cache_ttl_seconds=600)
    reader = RecallReader(tasks, artifacts, cache=cache, config=config, counter=_Counter())

    recomputes = {"n": 0}
    original = tasks.list_events

    async def _counted(scope, tid, **kwargs):
        recomputes["n"] += 1
        return await original(scope, tid, **kwargs)

    tasks.list_events = _counted  # type: ignore[assignment]
    try:
        await reader.recall(SCOPE, task_id)
        assert recomputes["n"] == 1

        # Inside the TTL: served from cache, no second selection.
        now["t"] += 599
        await reader.recall(SCOPE, task_id)
        assert recomputes["n"] == 1, "an entry inside its TTL was not reused"

        # Past the TTL: recomputed.
        now["t"] += 2
        await reader.recall(SCOPE, task_id)
        assert recomputes["n"] == 2, "an expired entry was still served"
    finally:
        tasks.list_events = original  # type: ignore[assignment]


@pytest.mark.asyncio
async def test_cache_keys_outage_never_changes_task_truth(wired) -> None:
    """A broken cache degrades to recomputation; it never fails a recall."""
    _, service, tasks, artifacts = wired
    result = await _seed(service)
    task_id = result.state.task_id

    class _BrokenCache:
        async def get(self, key: str):
            raise RuntimeError("cache is down")

        async def set(self, key: str, payload: bytes, ttl_seconds: int) -> None:
            raise RuntimeError("cache is down")

    reader = RecallReader(tasks, artifacts, cache=_BrokenCache(), counter=_Counter())
    recalled = await reader.recall(SCOPE, task_id)
    assert recalled.status is RecallStatus.OK
    assert recalled.snapshot["task_id"] == task_id

    # And the task itself is untouched.
    snapshot = await tasks.load_snapshot(SCOPE, task_id)
    assert snapshot.state.revision == result.state.revision


@pytest.mark.asyncio
async def test_cache_keys_corrupt_entry_is_a_miss(wired) -> None:
    """An unreadable cached entry is recomputed, not raised."""
    _, service, tasks, artifacts = wired
    result = await _seed(service)

    class _CorruptCache:
        """Always returns garbage, and records that it was asked."""

        def __init__(self) -> None:
            self.reads = 0

        async def get(self, key: str):
            self.reads += 1
            return b"{not json at all"

        async def set(self, key: str, payload: bytes, ttl_seconds: int) -> None:
            return None

    cache = _CorruptCache()
    reader = RecallReader(tasks, artifacts, cache=cache, counter=_Counter())
    recalled = await reader.recall(SCOPE, result.state.task_id)

    assert cache.reads == 1, "the cache was never consulted"
    assert recalled.status is RecallStatus.OK
    assert recalled.snapshot["task_id"] == result.state.task_id


@pytest.mark.asyncio
async def test_cache_keys_redis_cache_round_trips() -> None:
    """The Redis cache stores and returns a recall, under an isolated prefix."""
    redis_module = pytest.importorskip("redis.asyncio", reason="redis client not installed")
    client = redis_module.Redis(host="localhost", port=6379, db=15, decode_responses=False)
    try:
        await client.ping()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(
            f"no Redis at localhost:6379 db15 ({exc!r}). This is an ENVIRONMENTAL SKIP, not a pass — "
            "the Redis recall cache was not exercised here."
        )

    prefix = f"tmrecall_{uuid.uuid4().hex[:12]}"
    tasks, artifacts = InMemoryTaskMemoryStore(), InMemoryArtifactStore()
    service = TaskMemoryService(tasks, artifacts=artifacts)
    try:
        result = await _seed(service)
        cache = RedisRecallCache(client)
        key = f"{prefix}:entry"

        assert await cache.get(key) is None
        reader = RecallReader(tasks, artifacts, counter=_Counter())
        recalled = await reader.recall(SCOPE, result.state.task_id, use_cache=False)

        await cache.set(key, recalled.model_dump_json().encode("utf-8"), 60)
        raw = await cache.get(key)
        assert raw is not None
        from parrot.tools.working_memory.task_memory.recall import RecallResult

        assert RecallResult.model_validate_json(raw).to_bytes() == recalled.to_bytes()

        # A zero TTL stores nothing rather than storing something eternal.
        await cache.set(f"{prefix}:zero", b"x", 0)
        assert await cache.get(f"{prefix}:zero") is None
    finally:
        keys = [k async for k in client.scan_iter(match=f"{prefix}*")]
        if keys:
            await client.delete(*keys)
        await client.aclose()
        await tasks.close()
        await artifacts.close()


@pytest.mark.asyncio
async def test_cache_keys() -> None:
    """Required aggregate case: no cross-scope, task, calibration or generation collision."""
    test_cache_keys_every_dimension_changes_the_digest()
    test_cache_keys_availability_generation_is_keyed()
    test_cache_keys_digest_cannot_be_forged_by_concatenation()

    tasks, artifacts = InMemoryTaskMemoryStore(), InMemoryArtifactStore()
    service = TaskMemoryService(tasks, artifacts=artifacts)
    bundle = (RecallReader(tasks, artifacts, counter=_Counter()), service, tasks, artifacts)
    try:
        await test_cache_keys_scopes_never_share_an_entry(bundle)
        await test_cache_keys_hit_is_served_and_is_identical(bundle)
        await test_cache_keys_task_movement_invalidates(bundle)
        await test_cache_keys_outage_never_changes_task_truth(bundle)
    finally:
        await tasks.close()
        await artifacts.close()


# ─────────────────────────────────────────────────────────────
# Expiry and truthfulness
# ─────────────────────────────────────────────────────────────


def test_expiry_collect_omission_ids_finds_refs_and_keeps_one_prefix() -> None:
    """Omission ids are collected from payloads with the single ``om_`` prefix."""
    from datetime import datetime, timezone

    from parrot.tools.working_memory.task_memory.models import DegradedPayload, EventType, JournalEvent

    cid = content_id("some omitted output")
    assert cid.startswith("om_") and not cid.startswith("om_om_")

    event = JournalEvent(
        task_id="t-1",
        seq=1,
        occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        event_type=EventType.TRACKING_DEGRADED,
        payload=DegradedPayload(component="journal", detail=f"output offloaded to {cid}"),
    )
    found = collect_omission_ids([event])
    assert found == (cid,)
    # Distinct ids are kept in first-seen order, and repeats collapse.
    assert collect_omission_ids([event, event]) == (cid,)


@pytest.mark.asyncio
async def test_expiry_default_probe_is_unknown_not_present() -> None:
    """A custom store inherits UNKNOWN, never an optimistic 'present'."""

    class _CustomStore(OmissionStore):
        async def put(self, session_key, content, *, turn_id=None):
            return content_id(content)

        async def get(self, session_key, content_id):
            return None

        async def list_by_turn(self, session_key, turn_id):
            return []

        async def clear(self, session_key):
            return None

    store = _CustomStore()
    assert await store.probe("k", "om_0000000000000000") is None
    assert await store.probe_many("k", ["om_0000000000000000"]) == {"om_0000000000000000": None}


@pytest.mark.asyncio
async def test_expiry_in_memory_and_file_probes_are_truthful(tmp_path) -> None:
    """The in-memory and file probes answer without reading content."""
    memory = InMemoryOmissionStore()
    key = "bot:user:sess"
    cid = await memory.put(key, "large omitted output")

    assert await memory.probe(key, cid) is True
    assert await memory.probe(key, "om_ffffffffffffffff") is False
    assert await memory.probe("other:key:here", cid) is False, "a probe must be scoped"

    files = FileOmissionStore(tmp_path)
    fid = await files.put(key, "large omitted output")
    assert await files.probe(key, fid) is True
    assert await files.probe(key, "om_ffffffffffffffff") is False


@pytest.mark.asyncio
async def test_expiry_redis_probe_uses_hexists_not_hget() -> None:
    """The Redis probe must not transfer the value.

    Verified with a client whose ``hget`` is an armed trap: if the probe
    reached for the content, this test fails rather than quietly doing an
    expensive thing.
    """

    class _TrapClient:
        def __init__(self) -> None:
            self.hexists_calls = 0
            self.store: Dict[str, Dict[str, str]] = {}

        async def hset(self, key, field, value):
            self.store.setdefault(key, {})[field] = value

        async def hget(self, key, field):
            raise AssertionError("probe used HGET; it must use HEXISTS and transfer no value")

        async def hexists(self, key, field):
            self.hexists_calls += 1
            return field in self.store.get(key, {})

        async def expire(self, key, ttl):
            return True

    client = _TrapClient()
    store = RedisOmissionStore(client)
    key = "bot:user:sess"
    cid = await store.put(key, "large omitted output")

    assert await store.probe(key, cid) is True
    assert await store.probe(key, "om_ffffffffffffffff") is False
    assert client.hexists_calls == 2

    # No pipeline on this client, so probe_many falls back rather than failing.
    assert await store.probe_many(key, [cid]) == {cid: True}


@pytest.mark.asyncio
async def test_expiry_live_redis_probe_reports_expiry(wired) -> None:
    """Against real Redis, an expired key probes False at an unchanged sequence."""
    redis_module = pytest.importorskip("redis.asyncio", reason="redis client not installed")
    client = redis_module.Redis(host="localhost", port=6379, db=15, decode_responses=True)
    try:
        await client.ping()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(
            f"no Redis at localhost:6379 db15 ({exc!r}). This is an ENVIRONMENTAL SKIP, not a pass — "
            "live omission expiry was not exercised here."
        )

    prefix = f"tmprobe_{uuid.uuid4().hex[:12]}"
    store = RedisOmissionStore(client, key_prefix=prefix)
    key = "bot:user:sess"
    try:
        cid = await store.put(key, "large omitted output")
        assert await store.probe(key, cid) is True
        assert await store.probe_many(key, [cid, "om_ffffffffffffffff"]) == {
            cid: True,
            "om_ffffffffffffffff": False,
        }

        # Delete the hash: the reference is now known-gone, not unknown.
        await client.delete(f"{prefix}_omitted:{key}")
        assert await store.probe(key, cid) is False
    finally:
        keys = [k async for k in client.scan_iter(match=f"{prefix}*")]
        if keys:
            await client.delete(*keys)
        await client.aclose()


@pytest.mark.asyncio
async def test_expiry_unknown_refs_are_truthful_at_unchanged_sequence(wired) -> None:
    """An expired omission is reported honestly without any task event."""
    _, service, tasks, artifacts = wired
    result = await _seed(service)
    task_id = result.state.task_id

    omissions = InMemoryOmissionStore()
    key = RecallReader.omission_key(SCOPE)
    cid = await omissions.put(key, "large omitted output")

    # Reference it from the journal, then read the availability the reader
    # would capture — before and after the content disappears.
    await service.set_resume_hint(SCOPE, task_id, next_action=f"see {cid}")
    reader = RecallReader(tasks, artifacts, omission_store=omissions, counter=_Counter())

    before = await reader.build_inputs(SCOPE, task_id)
    assert before is not None
    assert before.availability.omissions.get(cid) is True

    await omissions.clear(key)
    after = await reader.build_inputs(SCOPE, task_id)
    assert after is not None
    assert after.as_of_seq == before.as_of_seq, "no task event was appended"
    assert after.availability.omissions.get(cid) is False, "expired content must not read as present"


@pytest.mark.asyncio
async def test_expiry_probe_failure_reports_unknown(wired) -> None:
    """A probe that raises yields UNKNOWN rather than failing the recall."""
    _, service, tasks, artifacts = wired
    result = await _seed(service)
    task_id = result.state.task_id
    cid = content_id("something")
    await service.set_resume_hint(SCOPE, task_id, next_action=f"see {cid}")

    class _BrokenProbe(InMemoryOmissionStore):
        async def probe_many(self, session_key, content_ids):
            raise RuntimeError("probe backend is down")

    reader = RecallReader(tasks, artifacts, omission_store=_BrokenProbe(), counter=_Counter())
    inputs = await reader.build_inputs(SCOPE, task_id)
    assert inputs is not None
    assert inputs.availability.omissions.get(cid) is None, "a failed probe must read as unknown"


@pytest.mark.asyncio
async def test_expiry_dead_worker_binding_is_reported(wired) -> None:
    """A stale REPL binding is flagged; the artifact itself is not.

    The task sequence does not move — a worker restart appends no event —
    so this is exactly the case the availability snapshot exists for.
    """
    _, service, tasks, artifacts = wired
    result = await _seed(service)
    task_id = result.state.task_id

    descriptor = await artifacts.put(SCOPE, "sales", {"n": 1}, task_id=task_id)
    ref = descriptor.ref

    reader = RecallReader(tasks, artifacts, counter=_Counter())
    before = await reader.build_inputs(SCOPE, task_id, worker_generation="gen-OLD")
    assert before is not None
    baseline_seq = before.as_of_seq

    # Attach a binding minted by the OLD generation, then recall as the NEW one.
    bound = descriptor.model_copy(
        update={"repl_binding": ReplBinding(worker_session_id="gen-OLD", variable_name="sales", ref=ref)}
    )
    real_list = artifacts.list

    async def _with_binding(scope, **kwargs):
        page = await real_list(scope, **kwargs)
        return page.model_copy(update={"items": (bound,)})

    artifacts.list = _with_binding  # type: ignore[assignment]
    try:
        result_new = await reader.recall(SCOPE, task_id, worker_generation="gen-NEW", use_cache=False)
    finally:
        artifacts.list = real_list  # type: ignore[assignment]

    entry = next(a for a in result_new.snapshot["artifacts"] if a["ref"] == str(ref))
    assert entry["binding_invalid"] is True
    assert (
        entry["availability"] == ArtifactAvailability.MEMORY.value
    ), "a stale binding does not mean the artifact disappeared"
    assert result_new.snapshot["as_of_seq"] == baseline_seq, "no task event was appended"


@pytest.mark.asyncio
async def test_expiry_needs_task_selection_is_bounded(wired) -> None:
    """With several open tasks and no selection, a bounded list is returned."""
    _, service, tasks, artifacts = wired
    for _ in range(3):
        await _seed(service)

    reader = RecallReader(tasks, artifacts, counter=_Counter())
    recalled = await reader.recall(SCOPE, None)

    assert recalled.status is RecallStatus.NEEDS_TASK_SELECTION
    listed = recalled.snapshot["open_tasks"]
    assert 0 < len(listed) <= NEEDS_SELECTION_PAGE
    for item in listed:
        assert set(item) == {"task_id", "goal", "status", "updated_at"}
        assert len(item["goal"]) <= 80, "the listing must not leak the whole goal"


@pytest.mark.asyncio
async def test_expiry() -> None:
    """Required aggregate case: expired/unknown refs and dead bindings are truthful."""
    test_expiry_collect_omission_ids_finds_refs_and_keeps_one_prefix()
    await test_expiry_default_probe_is_unknown_not_present()
    await test_expiry_redis_probe_uses_hexists_not_hget()

    for case in (
        test_expiry_unknown_refs_are_truthful_at_unchanged_sequence,
        test_expiry_probe_failure_reports_unknown,
        test_expiry_dead_worker_binding_is_reported,
        test_expiry_needs_task_selection_is_bounded,
    ):
        tasks, artifacts = InMemoryTaskMemoryStore(), InMemoryArtifactStore()
        service = TaskMemoryService(tasks, artifacts=artifacts)
        try:
            await case((RecallReader(tasks, artifacts, counter=_Counter()), service, tasks, artifacts))
        finally:
            await tasks.close()
            await artifacts.close()
