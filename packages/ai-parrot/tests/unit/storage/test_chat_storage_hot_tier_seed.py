"""issue:734c1ca9eb4b — an expired ChatStorage hot entry is re-seeded from the cold tier, never recreated partial.

Cold tier: the real SQLite backend. Hot tier: a real ``RedisConversation`` on the Redis named by
``TEST_REDIS_URL`` (a dedicated database; db 0-3 are refused), isolated by a per-test key prefix that is
deleted afterwards. Without ``TEST_REDIS_URL`` (or when nothing answers) every case SKIPS — an
environmental skip, not a pass.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator, List
from urllib.parse import urlparse

import pytest

from parrot.memory import RedisConversation
from parrot.memory.persistence import TurnPresentation
from parrot.storage.backends.sqlite import ConversationSQLiteBackend
from parrot.storage.chat import HOT_SEED_METADATA_KEY, ChatStorage
from parrot.storage.errors import ConversationDeletedError, StorageWriteError
from parrot.storage.models import ChatStorageTurn

REDIS_URL = os.environ.get("TEST_REDIS_URL", "")
T0 = datetime(2026, 11, 13, 9, 0, 0, tzinfo=timezone.utc)
USER, AGENT, SESSION = "u1", "bot1", "s1"
_COLD_READS = {"query_turn_window", "query_turns"}


def _redis_db(url: str) -> int:
    path = urlparse(url).path.strip("/")
    return int(path) if path.isdigit() else 0


async def _redis_answers(url: str) -> bool:
    from redis.asyncio import Redis

    client = Redis.from_url(url, socket_connect_timeout=2)
    try:
        return bool(await asyncio.wait_for(client.ping(), timeout=2))
    except Exception:  # noqa: BLE001 — unreachable for any reason is a skip
        return False
    finally:
        await client.aclose()


@pytest.fixture
async def cold(tmp_path) -> AsyncIterator[ConversationSQLiteBackend]:
    backend = ConversationSQLiteBackend(path=str(tmp_path / "chat.db"))
    await backend.initialize()
    yield backend
    await backend.close()


@pytest.fixture
def prefix() -> str:
    return f"chatseed_{uuid.uuid4().hex[:10]}"


@pytest.fixture(params=[True, False], ids=["hash", "string"])
async def hot_factory(request, prefix):
    """Build ``RedisConversation`` clients on one isolated prefix; every key under it is deleted afterwards."""
    if not REDIS_URL:
        pytest.skip("TEST_REDIS_URL not set — ENVIRONMENTAL SKIP, not a pass")
    if _redis_db(REDIS_URL) <= 3:
        pytest.fail(f"TEST_REDIS_URL must name a dedicated test database (> 3), got {REDIS_URL}")
    if not await _redis_answers(REDIS_URL):
        pytest.skip(f"no Redis answers at {REDIS_URL} — ENVIRONMENTAL SKIP, not a pass")
    made: List[RedisConversation] = []

    def make(cls=RedisConversation) -> RedisConversation:
        hot = cls(redis_url=REDIS_URL, key_prefix=prefix, use_hash_storage=request.param)
        made.append(hot)
        return hot

    yield make
    keys = [k async for k in made[0].redis.scan_iter(match=f"{prefix}*")] if made else []
    if keys:
        await made[0].redis.delete(*keys)
    for hot in made:
        await hot.redis.aclose()


@pytest.fixture
def storage(cold, hot_factory) -> ChatStorage:
    st = ChatStorage(redis_conversation=hot_factory(), dynamodb=cold)
    st._initialized = True
    return st


class _CountingBackend:
    """Delegates to the real SQLite backend and records every call by method name."""

    def __init__(self, inner: Any) -> None:
        self._inner, self.calls = inner, []

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._inner, name)
        if not callable(attr):
            return attr

        async def _wrapped(*a: Any, **kw: Any) -> Any:
            self.calls.append(name)
            return await attr(*a, **kw)

        return _wrapped


def _turn(n: int) -> ChatStorageTurn:
    return ChatStorageTurn(
        turn_id=f"t{n}",
        user_id=USER,
        session_id=SESSION,
        agent_id=AGENT,
        chatbot_id="bot-uuid",
        timestamp=T0 + timedelta(seconds=n),
        sequence=n,
        user_message=f"q-t{n}",
        assistant_response=f"a-t{n}",
        presentation=TurnPresentation(model="gemini", provider="google"),
    )


async def _expire_hot(storage: ChatStorage) -> None:
    """What ``CHAT_HOT_TTL_HOURS`` does in production: the hot key disappears."""
    hot = storage._redis
    assert await hot.redis.delete(hot._get_key(USER, SESSION, AGENT)) == 1


async def _hot_ids(storage: ChatStorage) -> List[str]:
    history = await storage._redis.get_history(USER, SESSION, chatbot_id=AGENT)
    return [t.turn_id for t in history.turns] if history else []


async def _served(storage: ChatStorage, limit: int = 50) -> List[str]:
    messages = await storage.load_conversation(USER, SESSION, agent_id=AGENT, limit=limit)
    return [m["content"] for m in messages if m["role"] == "user"]


async def test_a_turn_after_hot_expiry_does_not_shrink_the_conversation(storage):
    await storage.store_turn(_turn(1))
    await storage.store_turn(_turn(2))
    await _expire_hot(storage)

    await storage.store_turn(_turn(3))

    assert await _hot_ids(storage) == ["t1", "t2", "t3"]  # the recreated hot entry is NOT just [t3]
    assert await _served(storage) == ["q-t1", "q-t2", "q-t3"]
    context = await storage.get_context_for_agent(USER, SESSION, agent_id=AGENT)
    assert [m["content"] for m in context if m["role"] == "user"] == ["q-t1", "q-t2", "q-t3"]


async def test_the_seed_never_resurrects_a_tombstoned_turn(storage, cold):
    await storage.store_turn(_turn(1))
    await storage.store_turn(_turn(2))
    await cold.put_tombstone(USER, AGENT, SESSION, "t2")  # tombstone committed, cleanup not run: row still there
    await _expire_hot(storage)

    await storage.store_turn(_turn(3))

    assert await _hot_ids(storage) == ["t1", "t3"]  # raw hot entry: t2 was never copied back
    assert await _served(storage) == ["q-t1", "q-t3"]


async def test_steady_state_write_and_read_cost_no_cold_window_read(storage, cold):
    await storage.store_turn(_turn(1))
    await storage.store_turn(_turn(2))
    counting = _CountingBackend(cold)
    storage._dynamo = counting

    await storage.store_turn(_turn(3))
    assert _COLD_READS.isdisjoint(counting.calls), counting.calls
    assert await _served(storage) == ["q-t1", "q-t2", "q-t3"]
    assert _COLD_READS.isdisjoint(counting.calls), counting.calls


async def test_a_hot_miss_costs_exactly_one_cold_window_read(storage, cold):
    await storage.store_turn(_turn(1))
    await _expire_hot(storage)
    counting = _CountingBackend(cold)
    storage._dynamo = counting

    await storage.store_turn(_turn(2))

    assert [c for c in counting.calls if c in _COLD_READS] == ["query_turn_window"]


async def test_a_truncated_seed_sends_a_longer_read_to_the_cold_tier(storage, cold):
    storage.hot_seed_turns = 2
    for n in range(1, 5):
        await storage.store_turn(_turn(n))
    await _expire_hot(storage)

    await storage.store_turn(_turn(5))

    assert await _hot_ids(storage) == ["t4", "t5"]  # the newest window only
    history = await storage._redis.get_history(USER, SESSION, chatbot_id=AGENT)
    assert history.metadata[HOT_SEED_METADATA_KEY] == {"window": 2, "complete": False}
    assert await _served(storage) == [f"q-t{n}" for n in range(1, 6)]  # older turns come from the cold tier
    context = await storage.get_context_for_agent(USER, SESSION, agent_id=AGENT, max_turns=10)
    assert [m["content"] for m in context if m["role"] == "user"] == [f"q-t{n}" for n in range(1, 6)]

    counting = _CountingBackend(cold)
    storage._dynamo = counting
    assert await _served(storage, limit=2) == ["q-t4", "q-t5"]  # the hot entry covers it: no cold read
    assert _COLD_READS.isdisjoint(counting.calls), counting.calls


async def test_a_complete_seed_keeps_serving_from_the_hot_tier(storage, cold):
    await storage.store_turn(_turn(1))
    await _expire_hot(storage)
    await storage.store_turn(_turn(2))
    history = await storage._redis.get_history(USER, SESSION, chatbot_id=AGENT)
    assert history.metadata[HOT_SEED_METADATA_KEY] == {"window": storage.hot_seed_turns, "complete": True}

    counting = _CountingBackend(cold)
    storage._dynamo = counting
    assert await _served(storage) == ["q-t1", "q-t2"]
    assert _COLD_READS.isdisjoint(counting.calls), counting.calls


async def test_two_writers_on_a_hot_miss_neither_duplicate_nor_lose_turns(cold, hot_factory):
    gate = asyncio.Barrier(2)
    armed = False
    installs: List[bool] = []

    class _BothMissFirst(RedisConversation):
        async def install_history(self, *a: Any, **kw: Any) -> bool:
            if not armed:
                return await super().install_history(*a, **kw)
            await asyncio.wait_for(gate.wait(), timeout=10)  # both missed + read the cold window; neither installed
            installed = await super().install_history(*a, **kw)
            installs.append(installed)
            return installed

    first = ChatStorage(redis_conversation=hot_factory(_BothMissFirst), dynamodb=cold)
    second = ChatStorage(redis_conversation=hot_factory(_BothMissFirst), dynamodb=cold)
    for st in (first, second):
        st._initialized = True
    await first.store_turn(_turn(1))
    await first.store_turn(_turn(2))
    await _expire_hot(first)
    armed = True

    await asyncio.gather(first.store_turn(_turn(3)), second.store_turn(_turn(4)))

    assert sorted(installs) == [False, True]  # the NX install: exactly one seed landed
    assert await _hot_ids(first) == ["t1", "t2", "t3", "t4"]
    assert await _served(second) == ["q-t1", "q-t2", "q-t3", "q-t4"]


async def test_without_a_cold_tier_the_hot_tier_behaves_as_before(hot_factory):
    storage = ChatStorage(redis_conversation=hot_factory(), dynamodb=None)
    storage._initialized = True
    await storage.store_turn(_turn(1))
    await _expire_hot(storage)

    await storage.store_turn(_turn(2))  # nothing to seed from: no error, the new turn is stored

    assert await _hot_ids(storage) == ["t2"]


async def test_without_redis_reads_come_from_the_cold_tier(cold):
    storage = ChatStorage(redis_conversation=None, dynamodb=cold)
    storage._initialized = True
    for n in (1, 2, 3):
        await storage.store_turn(_turn(n))

    assert await _served(storage) == ["q-t1", "q-t2", "q-t3"]


async def test_a_tombstoned_conversation_is_never_seeded(storage, cold):
    await storage.store_turn(_turn(1))
    await _expire_hot(storage)
    await cold.put_tombstone(USER, AGENT, SESSION)
    counting = _CountingBackend(cold)
    storage._dynamo = counting

    with pytest.raises(ConversationDeletedError):
        await storage.store_turn(_turn(2))

    assert await _hot_ids(storage) == []
    assert _COLD_READS.isdisjoint(counting.calls), counting.calls  # the guard raised before any seed read


async def test_a_late_seed_never_overwrites_a_hot_entry_another_writer_installed(cold, hot_factory):
    other_done = asyncio.Event()
    armed = False
    installs: List[bool] = []

    class _SlowSeed(RedisConversation):
        async def install_history(self, *a: Any, **kw: Any) -> bool:
            if armed:  # this writer read its cold window, then stalls until the other writer has finished
                await asyncio.wait_for(other_done.wait(), timeout=10)
            installed = await super().install_history(*a, **kw)
            if armed:
                installs.append(installed)
            return installed

    slow = ChatStorage(redis_conversation=hot_factory(_SlowSeed), dynamodb=cold)
    fast = ChatStorage(redis_conversation=hot_factory(), dynamodb=cold)
    for st in (slow, fast):
        st._initialized = True
    await slow.store_turn(_turn(1))
    await slow.store_turn(_turn(2))
    await _expire_hot(slow)
    armed = True

    async def fast_writer() -> None:
        await asyncio.sleep(0.05)  # let the slow writer miss and read its window first
        await fast.store_turn(_turn(4))
        other_done.set()

    await asyncio.gather(slow.store_turn(_turn(3)), fast_writer())

    assert installs == [False]  # NX: the late seed lost to the installed entry
    assert await _hot_ids(fast) == ["t1", "t2", "t3", "t4"]  # t4 survived the late seed


async def test_a_replayed_turn_older_than_a_truncated_seed_leaves_no_gap(storage):
    for n in range(1, 6):
        await storage.store_turn(_turn(n))
    storage.hot_seed_turns = 2
    await _expire_hot(storage)

    await storage.store_turn(_turn(1))  # a delayed / replayed envelope for the oldest turn

    assert await _hot_ids(storage) == ["t4", "t5"]  # contiguous newest suffix; t1 stays cold-only
    assert await _served(storage, limit=3) == ["q-t3", "q-t4", "q-t5"]  # NOT t1, t4, t5


async def test_a_replay_inside_the_seed_window_is_replaced_in_place(storage):
    for n in range(1, 6):
        await storage.store_turn(_turn(n))
    storage.hot_seed_turns = 2
    await _expire_hot(storage)

    await storage.store_turn(_turn(4))  # inside the window of the seed that this very write creates
    await storage.store_turn(_turn(1))  # and a later one predating the now-present truncated entry

    assert await _hot_ids(storage) == ["t4", "t5"]
    assert await _served(storage, limit=3) == ["q-t3", "q-t4", "q-t5"]


def _vanishing_hot(hot_factory, times: int):
    """A hot tier whose key disappears right after each of the first ``times`` installs (an expiry in the gap)."""
    state = {"left": times, "installs": 0}

    class _Vanishing(RedisConversation):
        async def install_history(self, user_id: str, session_id: str, *a: Any, **kw: Any) -> bool:
            installed = await super().install_history(user_id, session_id, *a, **kw)
            state["installs"] += 1
            if state["left"] > 0:
                state["left"] -= 1
                await self.redis.delete(self._get_key(user_id, session_id, kw.get("chatbot_id")))
            return installed

    return hot_factory(_Vanishing), state


async def test_a_key_that_vanishes_between_install_and_upsert_is_reseeded_not_recreated_partial(cold, hot_factory):
    hot, state = _vanishing_hot(hot_factory, times=0)
    st = ChatStorage(redis_conversation=hot, dynamodb=cold)
    st._initialized = True
    await st.store_turn(_turn(1))
    await st.store_turn(_turn(2))
    await _expire_hot(st)
    state.update(left=1, installs=0)

    await st.store_turn(_turn(3))

    assert state["installs"] == 2  # the seed, then exactly one retry of the seed path
    assert await _hot_ids(st) == ["t1", "t2", "t3"]  # NOT the partial [t3] the old create=True upsert made


async def test_the_seed_retry_is_bounded_and_never_leaves_a_partial_entry(cold, hot_factory):
    hot, state = _vanishing_hot(hot_factory, times=0)
    st = ChatStorage(redis_conversation=hot, dynamodb=cold)
    st._initialized = True
    await st.store_turn(_turn(1))
    await _expire_hot(st)
    state.update(left=99, installs=0)

    with pytest.raises(StorageWriteError):
        await st.store_turn(_turn(2))

    assert state["installs"] == 2  # the seed plus exactly one retry — never a loop
    assert await _hot_ids(st) == []  # no partial entry holding only t2


async def test_a_turn_deleted_between_the_cold_read_and_the_install_is_not_resurrected(cold, hot_factory):
    armed = delete_landed = False

    class _DeleteRaces(RedisConversation):
        async def install_history(self, *a: Any, **kw: Any) -> bool:
            nonlocal delete_landed
            if armed and not delete_landed:  # the seed has read its window (t1, t2); now a delete of t2 runs to completion
                delete_landed = True
                await cold.put_tombstone(USER, AGENT, SESSION, "t2")
                assert await self.remove_turn(USER, SESSION, "t2", chatbot_id=AGENT) is False  # no hot key yet
            return await super().install_history(*a, **kw)

    st = ChatStorage(redis_conversation=hot_factory(_DeleteRaces), dynamodb=cold)
    st._initialized = True
    await st.store_turn(_turn(1))
    await st.store_turn(_turn(2))
    await _expire_hot(st)
    armed = True

    await st.store_turn(_turn(3))

    assert delete_landed
    assert await _hot_ids(st) == ["t1", "t3"]  # read straight from the Redis key, as working memory does
