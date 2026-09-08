"""Task association and atomic Redis metadata merging (FEAT-538 / TASK-2986).

Three required cases from the task's Test Specification:

- ``test_race_hash`` — race a task selection against a compaction/turn
  write **using real Redis**; every piece of metadata survives.
- ``test_race_full`` — the same in full-history mode, and against a stale
  history object; no lost selected task or calibration.
- ``test_selection`` — several unselected tasks yield
  ``needs_task_selection``; explicit-id recovery never crosses a scope.

Live cases run against a real Redis on the conventional local port, in
database 15, under a unique key prefix that is deleted afterwards. When no
Redis is reachable they SKIP with an explicit message — a skip is never
reported as a pass. The lost-update behaviour is *also* covered without a
server by :class:`_InterleavingRedis`, which deterministically injects a
competing write between the read and the write; that is the only way to
prove the fix rather than merely fail to observe the bug.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Dict, List, Optional

import pytest
from parrot.tools.working_memory.task_memory.association import (
    ASSOCIATION_KEY,
    CONTEXT_FAMILY,
    LEASE_FAMILY,
    RECALL_FAMILY,
    AssociationResult,
    TaskAssociation,
    TaskAssociationStore,
)
from parrot.tools.working_memory.task_memory.config import TaskMemoryConfig
from parrot.tools.working_memory.task_memory.models import Limits, TaskScope

REDIS_TEST_URL = "redis://localhost:6379/15"

SCOPE = TaskScope(chatbot_id="bot-a", user_id="user-1", session_id="sess-1")
OTHER_USER = TaskScope(chatbot_id="bot-a", user_id="user-2", session_id="sess-1")
OTHER_BOT = TaskScope(chatbot_id="bot-b", user_id="user-1", session_id="sess-1")

_SKIP_REASON = (
    "no Redis reachable at " + REDIS_TEST_URL + " — the live association/race cases did not run. "
    "This is an ENVIRONMENTAL SKIP, not a pass."
)


async def _redis_available() -> bool:
    """Return whether a Redis server answers on the test URL.

    Returns:
        ``True`` when reachable.
    """
    try:
        from redis.asyncio import Redis

        client = Redis.from_url(REDIS_TEST_URL, decode_responses=True, socket_connect_timeout=2)
        try:
            await asyncio.wait_for(client.ping(), timeout=2)
            return True
        finally:
            await client.aclose()
    except Exception:  # noqa: BLE001 — unreachable for any reason is a skip
        return False


@pytest.fixture()
async def memory(request):
    """Yield a RedisConversation on an isolated prefix, cleaned up after.

    Skips explicitly when no Redis is reachable.

    Args:
        request: pytest request, used to read the ``hash_storage`` param.

    Yields:
        The memory instance.
    """
    if not await _redis_available():
        pytest.skip(_SKIP_REASON)

    from parrot.memory.redis import RedisConversation

    use_hash = getattr(request, "param", True)
    prefix = f"tmassoc_{uuid.uuid4().hex[:10]}"
    store = RedisConversation(redis_url=REDIS_TEST_URL, key_prefix=prefix, use_hash_storage=use_hash)
    try:
        yield store
    finally:
        keys = [k async for k in store.redis.scan_iter(match=f"{prefix}*")]
        if keys:
            await store.redis.delete(*keys)
        await store.close()


async def _seed(memory: Any, scope: TaskScope, metadata: Dict[str, Any]) -> None:
    """Create a conversation and persist ``metadata``.

    ``create_history`` does **not** persist in hash mode (see the
    pre-existing bug reported with this task), so the record is written
    with ``update_history``, which does.

    Args:
        memory: The conversation memory.
        scope: The trusted scope.
        metadata: Metadata to store.
    """
    history = await memory.create_history(
        scope.user_id, scope.session_id, metadata=dict(metadata), chatbot_id=scope.chatbot_id
    )
    history.metadata = dict(metadata)
    await memory.update_history(history)


# ─────────────────────────────────────────────────────────────
# Server-free proof of the lost-update fix
# ─────────────────────────────────────────────────────────────


class _InterleavingRedis:
    """A minimal Redis double that injects a competing write mid-transaction.

    Real Redis will only *sometimes* interleave two writers, so a passing
    live race is weak evidence. This double makes the interleaving happen
    **deterministically**: the competing write lands between the watched
    read and the write, which is precisely the window the old
    read-modify-write lost. A ``WATCH`` that is honoured must therefore
    abort and retry; an implementation without one silently overwrites.
    """

    def __init__(self, initial: Dict[str, str], *, competing_writes: int = 1) -> None:
        """Initialize the double.

        Args:
            initial: Initial hash contents for the single key.
            competing_writes: How many times to inject a competing write.
        """
        self.data: Dict[str, str] = dict(initial)
        self._remaining = competing_writes
        self.aborts = 0
        self.dirty = False
        self.version = 0

    def _inject(self) -> None:
        """Simulate another writer touching the key."""
        if self._remaining <= 0:
            return
        self._remaining -= 1
        meta = json.loads(self.data.get("metadata", "{}"))
        meta["compaction"] = {"calibration": 1.75, "written_by": "competing writer"}
        self.data["metadata"] = json.dumps(meta)
        self.dirty = True

    def pipeline(self) -> "_InterleavingPipeline":
        """Return a new pipeline over this store."""
        return _InterleavingPipeline(self)


class _InterleavingPipeline:
    """Pipeline half of :class:`_InterleavingRedis`."""

    def __init__(self, store: _InterleavingRedis) -> None:
        """Initialize the pipeline.

        Args:
            store: The backing double.
        """
        self._store = store
        self._watching = False
        self._version = 0
        self._queued: List[tuple] = []

    async def __aenter__(self) -> "_InterleavingPipeline":
        """Enter the pipeline context."""
        return self

    async def __aexit__(self, *exc: Any) -> None:
        """Leave the pipeline context."""
        return None

    async def watch(self, key: str) -> None:
        """Begin watching ``key``.

        Args:
            key: The key to watch.
        """
        self._watching = True
        self._version = getattr(self._store, "version", 0)

    async def hget(self, key: str, field: str) -> Optional[str]:
        """Read a hash field, then let a competing writer in.

        Args:
            key: The key.
            field: The field.

        Returns:
            The stored value, or ``None``.
        """
        value = self._store.data.get(field)
        # The competing write lands AFTER our read — the exact window.
        self._store._inject()
        self._store.version = getattr(self._store, "version", 0) + (1 if self._store.dirty else 0)
        self._store.dirty = False
        return value

    def multi(self) -> None:
        """Switch to buffered mode."""

    def hset(self, key: str, field: Optional[str] = None, value: Optional[str] = None, mapping=None) -> None:
        """Buffer a hash write.

        Args:
            key: The key.
            field: Field name, for the field/value form.
            value: Field value, for the field/value form.
            mapping: Mapping form.
        """
        self._queued.append((field, value, mapping))

    def expire(self, key: str, ttl: int) -> None:
        """Buffer an expiry (ignored by the double)."""

    async def execute(self) -> None:
        """Commit, or abort if the key changed since ``watch``.

        Raises:
            WatchError: When a competing writer touched the key.
        """
        from redis.exceptions import WatchError

        if self._watching and getattr(self._store, "version", 0) != self._version:
            self._store.aborts += 1
            raise WatchError("key changed")
        for field, value, mapping in self._queued:
            if mapping:
                self._store.data.update({k: str(v) for k, v in mapping.items()})
            else:
                self._store.data[field] = value
        self._queued.clear()


@pytest.mark.asyncio
async def test_merge_retries_when_a_competing_writer_interleaves() -> None:
    """A write landing between our read and our write must not be lost.

    Deterministic, server-free proof of the actual bug: the competing
    writer sets ``metadata["compaction"]`` after we have read the blob. A
    correct implementation aborts, re-reads, and merges on top; the old
    read-modify-write would have written its stale copy and erased the
    competitor.
    """
    from parrot.memory.redis import RedisConversation

    double = _InterleavingRedis({"metadata": json.dumps({"unrelated": "keep me"})})

    memory = RedisConversation.__new__(RedisConversation)
    memory.key_prefix = "t"
    memory.use_hash_storage = True
    memory.redis = double

    merged = await memory.merge_metadata(
        "u", "s", "bot", mutate=lambda md: {**md, "task_memory": {"selected_task_id": "t-1"}}
    )

    assert double.aborts >= 1, "the CAS never aborted — the competing write was not detected"
    assert merged["task_memory"]["selected_task_id"] == "t-1", "our own write was lost"
    assert (
        merged["compaction"]["written_by"] == "competing writer"
    ), "the competing writer's update was overwritten — this is the lost update the fix exists to prevent"
    assert merged["unrelated"] == "keep me", "an unrelated key was dropped"


# ─────────────────────────────────────────────────────────────
# test_race_hash
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("memory", [True], indirect=True)
async def test_race_hash(memory: Any) -> None:
    """Required case: race selection against calibration/turn saves (hash mode)."""
    from parrot.memory.abstract import ConversationTurn

    store = TaskAssociationStore(memory)
    await _seed(memory, SCOPE, {"unrelated": "keep me"})

    async def select(task_id: str) -> AssociationResult:
        return await store.associate(SCOPE, task_id, select=True)

    async def calibrate(value: float) -> None:
        await memory.merge_metadata(
            SCOPE.user_id,
            SCOPE.session_id,
            SCOPE.chatbot_id,
            mutate=lambda md: {**md, "compaction": {"calibration": value, "tokenizer": "heuristic"}},
        )

    async def save_turn(n: int) -> None:
        turn = ConversationTurn(
            turn_id=f"turn-{n}", user_id=SCOPE.user_id, user_message=f"q{n}", assistant_response=f"a{n}"
        )
        await memory._store_turn(
            SCOPE.user_id,
            SCOPE.session_id,
            turn,
            SCOPE.chatbot_id,
            compaction_state={"calibration": 1.5, "tokenizer": "heuristic"},
        )

    await asyncio.gather(
        select("task-A"),
        calibrate(1.25),
        save_turn(1),
        select("task-B"),
        calibrate(1.4),
        save_turn(2),
    )

    metadata = await memory.read_metadata(SCOPE.user_id, SCOPE.session_id, SCOPE.chatbot_id)
    assert metadata is not None

    # Every writer's key survived: unrelated, compaction and task_memory.
    assert metadata["unrelated"] == "keep me", "an unrelated metadata key was lost"
    assert "compaction" in metadata, "the compaction writer's state was lost"
    assert "calibration" in metadata["compaction"]
    assert ASSOCIATION_KEY in metadata, "the task association was lost"

    association = TaskAssociation.from_metadata(metadata)
    assert set(association.open_task_ids) == {"task-A", "task-B"}, "a concurrent association was lost"
    assert association.selected_task_id in {"task-A", "task-B"}
    assert association.revision >= 2

    # Both turns landed — the turn writer is under the same CAS.
    history = await memory.get_history(SCOPE.user_id, SCOPE.session_id, SCOPE.chatbot_id)
    assert history is not None
    assert {t.turn_id for t in history.turns} == {"turn-1", "turn-2"}, "a concurrent turn append was lost"


# ─────────────────────────────────────────────────────────────
# test_race_full
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("memory", [False], indirect=True)
async def test_race_full(memory: Any) -> None:
    """Required case: the same race in full-history mode, plus a stale history."""
    from parrot.memory.abstract import ConversationTurn

    store = TaskAssociationStore(memory)
    await _seed(memory, SCOPE, {"unrelated": "keep me"})

    # A caller holding a STALE history object — the classic full-history
    # hazard, because update_history replaces the whole record.
    stale = await memory.get_history(SCOPE.user_id, SCOPE.session_id, SCOPE.chatbot_id)

    async def select(task_id: str) -> AssociationResult:
        return await store.associate(SCOPE, task_id, select=True)

    async def calibrate(value: float) -> None:
        await memory.merge_metadata(
            SCOPE.user_id,
            SCOPE.session_id,
            SCOPE.chatbot_id,
            mutate=lambda md: {**md, "compaction": {"calibration": value}},
        )

    async def save_turn(n: int) -> None:
        turn = ConversationTurn(
            turn_id=f"turn-{n}", user_id=SCOPE.user_id, user_message=f"q{n}", assistant_response=f"a{n}"
        )
        await memory._store_turn(
            SCOPE.user_id, SCOPE.session_id, turn, SCOPE.chatbot_id, compaction_state={"calibration": 1.5}
        )

    await asyncio.gather(select("task-A"), calibrate(1.25), save_turn(1), select("task-B"))

    metadata = await memory.read_metadata(SCOPE.user_id, SCOPE.session_id, SCOPE.chatbot_id)
    assert metadata is not None
    assert metadata["unrelated"] == "keep me"
    assert "compaction" in metadata
    association = TaskAssociation.from_metadata(metadata)
    assert set(association.open_task_ids) == {"task-A", "task-B"}

    # Now the stale writer lands. It legitimately overwrites the record
    # (that is what update_history means), so the association must be
    # re-established through the merge path rather than assumed.
    stale.metadata["unrelated"] = "stale writer"
    await memory.update_history(stale)

    recovered = await store.select(SCOPE, "task-A")
    assert recovered.degraded is False
    assert recovered.association.selected_task_id == "task-A"

    final = await memory.read_metadata(SCOPE.user_id, SCOPE.session_id, SCOPE.chatbot_id)
    assert (
        TaskAssociation.from_metadata(final).selected_task_id == "task-A"
    ), "explicit selection must repair an association a stale full-history write dropped"


# ─────────────────────────────────────────────────────────────
# test_selection
# ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("memory", [True], indirect=True)
async def test_selection(memory: Any) -> None:
    """Required case: unselected tasks need selection; explicit ids never cross scope."""
    store = TaskAssociationStore(memory)
    await _seed(memory, SCOPE, {})

    # One open task resolves without a selection.
    await store.associate(SCOPE, "task-A", select=False)
    resolved = await store.resolve(SCOPE)
    assert resolved.task_id == "task-A" and resolved.needs_selection is False

    # A second unselected task makes it ambiguous — never a guess.
    await store.associate(SCOPE, "task-B", select=False)
    ambiguous = await store.resolve(SCOPE)
    assert ambiguous.task_id is None
    assert ambiguous.needs_selection is True
    assert set(ambiguous.candidates) == {"task-A", "task-B"}

    # An explicit selection resolves it.
    await store.select(SCOPE, "task-B")
    chosen = await store.resolve(SCOPE)
    assert chosen.task_id == "task-B" and chosen.needs_selection is False

    # Another scope sees NOTHING — association is per conversation.
    for foreign in (OTHER_USER, OTHER_BOT):
        assert (await store.read(foreign)).open_task_ids == ()
        foreign_resolved = await store.resolve(foreign)
        assert foreign_resolved.task_id is None
        assert foreign_resolved.needs_selection is False
        assert foreign_resolved.candidates == ()

    # An explicit id is honoured, but it does not import another scope's
    # association: selecting in one scope leaves the other empty.
    await store.select(OTHER_USER, "task-B")
    assert (await store.read(SCOPE)).selected_task_id == "task-B"
    assert set((await store.read(OTHER_USER)).open_task_ids) == {"task-B"}
    assert set((await store.read(SCOPE)).open_task_ids) == {"task-A", "task-B"}

    # Closing the selected task clears the selection rather than guessing.
    closed = await store.close_task(SCOPE, "task-B")
    assert closed.association.selected_task_id is None
    assert set(closed.association.open_task_ids) == {"task-A"}


# ─────────────────────────────────────────────────────────────
# Association semantics (server-free)
# ─────────────────────────────────────────────────────────────


def test_association_survives_unreadable_metadata() -> None:
    """A malformed association block yields an empty one, never an exception.

    A conversation with a corrupt pointer has lost a selection, not its
    work; refusing to serve the user over it would be the worse failure.
    """
    for bad in (None, {}, {ASSOCIATION_KEY: "not a dict"}, {ASSOCIATION_KEY: {"open_task_ids": "nope"}}):
        association = TaskAssociation.from_metadata(bad)
        assert association.open_task_ids == ()
        assert association.selected_task_id is None


def test_association_revision_advances_and_preserves_others() -> None:
    """Every change bumps the revision; unrelated keys are untouched."""
    first = TaskAssociation().with_task("t-1")
    assert first.revision == 1 and first.selected_task_id == "t-1"

    second = first.with_task("t-2", select=False)
    assert second.revision == 2
    assert second.selected_task_id == "t-1", "select=False must not steal the selection"
    assert second.open_task_ids == ("t-1", "t-2")

    # Re-registering is idempotent in membership but still a revision.
    again = second.with_task("t-2", select=False)
    assert again.open_task_ids == ("t-1", "t-2")
    assert again.revision == 3

    closed = second.without_task("t-1")
    assert closed.open_task_ids == ("t-2",)
    assert closed.selected_task_id is None, "closing the selected task must not guess a replacement"


def test_association_open_task_ceiling_is_enforced() -> None:
    """A conversation cannot open unbounded tasks."""
    association = TaskAssociation()
    for n in range(Limits.MAX_OPEN_TASKS_PER_SCOPE):
        association = association.with_task(f"t-{n}", select=False)
    with pytest.raises(ValueError, match="cannot open more than"):
        association.with_task("one-too-many", select=False)


def test_association_round_trips_through_metadata() -> None:
    """The stored block reconstructs the same association."""
    original = TaskAssociation().with_task("t-1").with_task("t-2", select=False)
    metadata = {"unrelated": 1, ASSOCIATION_KEY: original.to_metadata_value()}
    assert TaskAssociation.from_metadata(metadata) == original


@pytest.mark.asyncio
async def test_association_degrades_without_duplicating_a_task() -> None:
    """A failed association reports the committed task; it never raises.

    Raising here would tempt a caller into creating a second task for work
    that has already been committed — much worse than a missing pointer.
    """

    class _BrokenMemory:
        key_prefix = "broken"

        async def merge_metadata(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
            raise ConnectionError("redis is down")

        async def get_history(self, *args: Any, **kwargs: Any) -> None:
            return None

    store = TaskAssociationStore(_BrokenMemory())
    result = await store.associate(SCOPE, "committed-task-1")

    assert result.degraded is True
    assert result.task_id == "committed-task-1", "the caller must learn the committed task id"
    assert "redis is down" in (result.reason or "")

    # And resolution still works, degraded, without inventing a task.
    selection = await store.resolve(SCOPE)
    assert selection.task_id is None and selection.needs_selection is False


@pytest.mark.asyncio
async def test_association_without_merge_support_is_degraded_not_crashed() -> None:
    """A memory with no atomic merge is reported, not silently accepted."""

    class _PlainMemory:
        key_prefix = "plain"

        async def get_history(self, *args: Any, **kwargs: Any) -> None:
            return None

    result = await TaskAssociationStore(_PlainMemory()).associate(SCOPE, "t-1")
    assert result.degraded is True
    assert "atomic metadata merge" in (result.reason or "")


# ─────────────────────────────────────────────────────────────
# Hot keys and leases
# ─────────────────────────────────────────────────────────────


def test_hot_keys_are_scope_encoded_and_cannot_be_forged() -> None:
    """Scope components are percent-encoded, so a ``:`` cannot forge a key."""

    class _Mem:
        key_prefix = "conversation"

    store = TaskAssociationStore(_Mem())

    plain = TaskScope(chatbot_id="bot-a", user_id="user-1", session_id="sess-1")
    sneaky = TaskScope(chatbot_id="bot-a:user-1", user_id="sess-1", session_id="x")
    assert store.context_key(plain) != store.context_key(sneaky)

    assert store.lease_key(plain, "t-1").startswith(f"conversation{LEASE_FAMILY}:")
    assert store.recall_key(plain, "digest").startswith(f"conversation{RECALL_FAMILY}:")
    assert store.context_key(plain).startswith(f"conversation{CONTEXT_FAMILY}:")

    # A task id containing a separator cannot escape its component either.
    assert store.lease_key(plain, "t:1") != store.lease_key(plain, "t") + ":1"


@pytest.mark.asyncio
@pytest.mark.parametrize("memory", [True], indirect=True)
async def test_lease_is_owner_fenced(memory: Any) -> None:
    """A lease is renewed and released only by its owner."""
    config = TaskMemoryConfig()
    store = TaskAssociationStore(memory, config)

    assert await store.acquire_lease(SCOPE, "t-1", "owner-A") is True
    assert await store.acquire_lease(SCOPE, "t-1", "owner-B") is False, "a held lease must not be re-taken"

    assert await store.renew_lease(SCOPE, "t-1", "owner-B") is False, "a non-owner must not extend a lease"
    assert await store.renew_lease(SCOPE, "t-1", "owner-A") is True

    assert await store.release_lease(SCOPE, "t-1", "owner-B") is False, "a non-owner must not release a lease"
    assert await store.release_lease(SCOPE, "t-1", "owner-A") is True

    # Released: now available again.
    assert await store.acquire_lease(SCOPE, "t-1", "owner-B") is True
    await store.release_lease(SCOPE, "t-1", "owner-B")


@pytest.mark.asyncio
@pytest.mark.parametrize("memory", [True], indirect=True)
async def test_association_write_sets_finite_retention(memory: Any) -> None:
    """Task-memory mode gives the hot key a finite TTL.

    History keys carry no TTL of their own, so without this the
    association would outlive every retention policy that governs it.
    """
    store = TaskAssociationStore(memory, TaskMemoryConfig())
    await _seed(memory, SCOPE, {})
    await store.associate(SCOPE, "t-1")

    ttl = await memory.redis.ttl(memory._get_key(SCOPE.user_id, SCOPE.session_id, SCOPE.chatbot_id))
    assert ttl > 0, "the association write must apply a finite hot-key retention"
    assert ttl <= TaskMemoryConfig().context_ttl_seconds
