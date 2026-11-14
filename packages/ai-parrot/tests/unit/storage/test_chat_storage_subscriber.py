"""FEAT-886 M9 — ChatStorage as turn-bus subscriber: idempotency, error routing, deletion races.

Cold tier: the real SQLite backend. Hot tier: a real ``RedisConversation`` against a throw-away
``redis-server`` subprocess (skipped when the binary is missing).
"""

from __future__ import annotations

import asyncio
import shutil
import socket
import subprocess
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from parrot.memory import ConversationTurn, RedisConversation
from parrot.memory.persistence import CONVERSATION_DELETED_TOPIC, TurnPresentation
from parrot.storage.backends.sqlite import ConversationSQLiteBackend
from parrot.storage.chat import ChatStorage
from parrot.storage.errors import ConversationDeletedError, StorageUnavailableError, StorageWriteError
from parrot.storage.models import ChatStorageTurn

UTC = timezone.utc
T0 = datetime(2026, 11, 1, 10, 0, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def redis_url(tmp_path_factory):
    binary = shutil.which("redis-server")
    if not binary:
        pytest.skip("redis-server not installed")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    proc = subprocess.Popen(
        [
            binary,
            "--port",
            str(port),
            "--save",
            "",
            "--appendonly",
            "no",
            "--dir",
            str(tmp_path_factory.mktemp("redis")),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    else:
        proc.kill()
        pytest.skip("redis-server did not start")
    yield f"redis://127.0.0.1:{port}/0"
    proc.terminate()
    proc.wait(timeout=5)


@pytest.fixture
async def cold(tmp_path):
    b = ConversationSQLiteBackend(path=str(tmp_path / "chat.db"))
    await b.initialize()
    yield b
    await b.close()


@pytest.fixture
async def storage(cold, redis_url, request):
    hot = RedisConversation(redis_url=redis_url, key_prefix=f"chat-{request.node.name}")
    st = ChatStorage(redis_conversation=hot, dynamodb=cold)
    st._initialized = True
    yield st
    await hot.redis.aclose()


def _turn(tid: str, sec: int = 0, seq: int = 1, session: str = "s1", **kw) -> ChatStorageTurn:
    return ChatStorageTurn(
        turn_id=tid,
        user_id="u1",
        session_id=session,
        agent_id="bot1",
        chatbot_id="bot-uuid",
        timestamp=T0 + timedelta(seconds=sec),
        sequence=seq,
        user_message=f"q-{tid}",
        assistant_response=f"a-{tid}",
        presentation=TurnPresentation(model="m", usage={"t": 1}),
        **kw,
    )


def _envelope(turn: ChatStorageTurn) -> SimpleNamespace:
    ct = turn.to_conversation_turn()
    payload = {
        "agent_name": turn.agent_id,
        "chatbot_id": turn.chatbot_id,
        "user_id": turn.user_id,
        "session_id": turn.session_id,
        "turn": ct.to_dict(),
        "presentation": turn.presentation.model_dump(),
    }
    return SimpleNamespace(payload=payload, event_id=turn.turn_id)


async def _hot_ids(storage, session="s1"):
    h = await storage._redis.get_history("u1", session, chatbot_id="bot1")
    return [t.turn_id for t in h.turns] if h else []


async def test_store_turn_is_idempotent_in_both_tiers(storage, cold):
    await storage.store_turn(_turn("t1"))
    await storage.store_turn(_turn("t1"))
    assert [t["turn_id"] for t in await cold.query_turn_window("u1", "bot1", "s1", 10)] == ["t1"]
    assert await _hot_ids(storage) == ["t1"]


async def test_late_duplicate_keeps_ordering_fields(storage, cold):
    await storage.store_turn(_turn("t1", sec=0, seq=1))
    await storage.store_turn(_turn("t1", sec=50, seq=9))
    [row] = await cold.query_turn_window("u1", "bot1", "s1", 10)
    assert row["sequence"] == 1
    hot = await storage._redis.get_history("u1", "s1", chatbot_id="bot1")
    assert [(t.turn_id, t.sequence, t.timestamp.second) for t in hot.turns] == [("t1", 1, 0)]


async def test_hot_tier_orders_late_arrivals(storage):
    await storage.store_turn(_turn("t2", sec=2, seq=2))
    await storage.store_turn(_turn("t1", sec=1, seq=1))
    assert await _hot_ids(storage) == ["t1", "t2"]


async def test_handler_acks_terminal_errors_and_propagates_retryable(storage, cold, caplog):
    await storage.handle_turn_completed(_envelope(_turn("ok")))  # stored
    assert await _hot_ids(storage) == ["ok"]
    bad = _envelope(_turn("bad"))
    bad.payload["session_id"] = ""
    await storage.handle_turn_completed(bad)  # InvalidTurnPayloadError: acknowledged
    await cold.put_tombstone("u1", "bot1", "dead")
    await storage.handle_turn_completed(_envelope(_turn("late", session="dead")))  # ConversationDeletedError
    assert "late" not in await _hot_ids(storage, "dead")

    class _Down(ConversationSQLiteBackend):
        async def put_turn(self, *a, **kw):
            raise StorageUnavailableError("down")

    down = ChatStorage(redis_conversation=None, dynamodb=_Down(path=":memory:"))
    with pytest.raises(StorageUnavailableError):
        await down.handle_turn_completed(_envelope(_turn("x")))


async def test_foreign_exception_becomes_retryable_write_error(cold):
    class _Boom:
        async def upsert_turn(self, *a, **kw):
            raise RuntimeError("redis exploded")

    st = ChatStorage(redis_conversation=_Boom(), dynamodb=cold)
    with pytest.raises(StorageWriteError):
        await st.store_turn(_turn("t1"))


async def test_no_tier_configured_raises():
    with pytest.raises(StorageUnavailableError):
        await ChatStorage().store_turn(_turn("t1"))


async def test_delete_conversation_is_tombstone_first_and_final(storage, cold):
    published = []

    async def publisher(topic, payload):
        published.append((topic, payload))

    storage.attach_deletion_publisher(publisher)
    cleaned = []

    async def cleaner(user, agent, session):
        cleaned.append((user, agent, session))

    storage.register_memory_cleaner(cleaner)
    await storage.store_turn(_turn("t1"))
    assert await storage.delete_conversation("u1", "s1", "bot1") is True
    assert await cold.is_deleted("u1", "bot1", "s1") is True
    assert await _hot_ids(storage) == []
    assert cleaned == [("u1", "bot1", "s1")]
    assert published == [(CONVERSATION_DELETED_TOPIC, {"user_id": "u1", "agent_id": "bot1", "session_id": "s1"})]
    with pytest.raises(ConversationDeletedError):  # a replayed event can never resurrect it
        await storage.store_turn(_turn("t2"))
    assert await _hot_ids(storage) == []


async def test_tombstone_failure_aborts_the_delete(storage, cold, monkeypatch):
    await storage.store_turn(_turn("t1"))

    async def fail(*a, **kw):
        raise StorageWriteError("no tombstone")

    monkeypatch.setattr(cold, "put_tombstone", fail)
    with pytest.raises(StorageWriteError):
        await storage.delete_conversation("u1", "s1", "bot1")
    assert await _hot_ids(storage) == ["t1"]  # nothing was cleared
    assert len(await cold.query_turn_window("u1", "bot1", "s1", 10)) == 1


async def test_delete_landing_between_cold_and_hot_write_wins(cold, redis_url):
    class _RacyHot(RedisConversation):
        async def upsert_turn(self, user_id, session_id, turn, chatbot_id=None):
            await cold.put_tombstone(user_id, chatbot_id, session_id)  # the delete lands mid-store
            await super().upsert_turn(user_id, session_id, turn, chatbot_id)

    hot = _RacyHot(redis_url=redis_url, key_prefix="chat-race")
    st = ChatStorage(redis_conversation=hot, dynamodb=cold)
    try:
        with pytest.raises(ConversationDeletedError):
            await st.store_turn(_turn("t1", session="race"))
        assert await hot.get_history("u1", "race", chatbot_id="bot1") is None  # resurrected copy removed
    finally:
        await hot.redis.aclose()


async def test_delete_turn_is_turn_scoped(storage, cold):
    await storage.store_turn(_turn("t1", sec=1))
    await storage.store_turn(_turn("t2", sec=2))
    assert await storage.delete_turn("s1", "t1", user_id="u1", agent_id="bot1") is True
    assert await _hot_ids(storage) == ["t2"]
    assert [t["turn_id"] for t in await cold.query_turn_window("u1", "bot1", "s1", 10)] == ["t2"]
    with pytest.raises(ConversationDeletedError):
        await storage.store_turn(_turn("t1", sec=1))
    await storage.store_turn(_turn("t3", sec=3))  # other turns are unaffected
    assert await storage.delete_turn("s1", "t1", user_id=None, agent_id="bot1") is False


async def test_cleanup_retry_handler_raises_until_clean(storage, cold):
    calls = {"n": 0}

    async def flaky(user, agent, session):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("cleaner down")

    storage.register_memory_cleaner(flaky)
    await storage.store_turn(_turn("t1"))
    await storage.delete_conversation("u1", "s1", "bot1")  # cleanup error after the tombstone: still acknowledged
    env = SimpleNamespace(payload={"user_id": "u1", "agent_id": "bot1", "session_id": "s1"}, event_id="e1")
    await storage.handle_conversation_deleted(env)  # second attempt succeeds
    assert calls["n"] == 2
    calls["n"] = 0
    with pytest.raises(StorageWriteError):
        await storage.handle_conversation_deleted(env)
    await storage.handle_conversation_deleted(SimpleNamespace(payload={"nope": 1}, event_id="e2"))  # malformed: acked


async def test_public_properties_are_read_only(storage, cold):
    assert storage.cold_backend is cold
    assert storage.hot_redis_client is storage._redis.redis
    with pytest.raises(AttributeError):
        storage.cold_backend = None  # type: ignore[misc]
    assert ChatStorage().hot_redis_client is None


async def test_load_conversation_reads_cold_rows_through_the_tolerant_reader(cold):
    await cold.put_turn("u1", "bot1", "s9", "t1", _turn("t1", session="s9").to_row())
    st = ChatStorage(dynamodb=cold)
    msgs = await st.load_conversation("u1", "s9", agent_id="bot1")
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[1]["usage"] == {"t": 1} and msgs[1]["model"] == "m"


async def test_cleanup_failing_once_is_retried_until_done(storage, cold):
    storage.cleanup_retry_base_delay = 0.0
    await storage.store_turn(_turn("t1"))
    real = storage._redis.delete_history
    calls = {"n": 0}

    async def flaky_delete(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("redis hiccup")
        return await real(*a, **kw)

    storage._redis.delete_history = flaky_delete
    await storage.delete_conversation("u1", "s1", "bot1")  # no deletion publisher attached: the in-process retry runs
    assert await _hot_ids(storage) == ["t1"]  # first attempt failed, the resurrected copy is still there
    for _ in range(200):
        if not storage._cleanup_retries:
            break
        await asyncio.sleep(0.01)
    assert calls["n"] >= 2 and await _hot_ids(storage) == []


async def test_failed_deletion_publish_falls_back_to_the_in_process_retry(storage):
    storage.cleanup_retry_base_delay = 0.0
    await storage.store_turn(_turn("t1"))

    async def broken(topic, payload):
        raise RuntimeError("bus down")

    storage.attach_deletion_publisher(broken)
    await storage.delete_conversation("u1", "s1", "bot1")
    assert storage._cleanup_retries  # a retry exists even though the event could not be published
    for _ in range(200):
        if not storage._cleanup_retries:
            break
        await asyncio.sleep(0.01)
    assert not storage._cleanup_retries


async def test_reads_between_tombstone_and_cleanup_refuse_the_conversation(storage, cold):
    await storage.store_turn(_turn("t1"))
    await cold.put_tombstone("u1", "bot1", "s1")  # the delete was acknowledged; cleanup has not run yet
    assert await _hot_ids(storage) == ["t1"]  # the leftover copy is still physically present
    with pytest.raises(ConversationDeletedError):
        await storage.load_conversation("u1", "s1", agent_id="bot1")
    with pytest.raises(ConversationDeletedError):
        await storage.get_context_for_agent("u1", "s1", agent_id="bot1")
    await cold.put_thread("u1", "bot1", "s1", {"title": "x", "session_id": "s1", "agent_id": "bot1"})
    assert await storage.list_user_conversations("u1", agent_id="bot1") == []  # hidden from the list too


async def test_storage_errors_on_reads_are_raised_not_emptied(storage, cold, monkeypatch):
    async def down(*a, **kw):
        raise StorageUnavailableError("cold store down")

    monkeypatch.setattr(cold, "is_deleted", down)
    with pytest.raises(StorageUnavailableError):
        await storage.load_conversation("u1", "s1", agent_id="bot1")
    monkeypatch.undo()

    async def query_down(*a, **kw):
        raise StorageUnavailableError("cold store down")

    monkeypatch.setattr(cold, "query_threads", query_down)
    with pytest.raises(StorageUnavailableError):
        await storage.list_user_conversations("u1", agent_id="bot1")


async def test_cold_read_is_chronological_with_a_legacy_fallback(cold, tmp_path):
    """The cold fallback returns the NEWEST turns in chronological order, not the sort_key (uuid) order."""
    for i, tid in enumerate(("zz", "aa", "mm", "bb")):  # ids deliberately unrelated to time
        await cold.put_turn("u1", "bot1", "s1", tid, _turn(tid, sec=i, seq=i + 1).to_row())
    st = ChatStorage(dynamodb=cold)
    users = [
        m["content"] for m in await st.load_conversation("u1", "s1", agent_id="bot1", limit=3) if m["role"] == "user"
    ]
    assert users == ["q-aa", "q-mm", "q-bb"]  # newest three, ascending by time

    import sqlite3

    raw = sqlite3.connect(str(tmp_path / "chat.db"))
    raw.execute(
        "INSERT INTO conversations (user_id, agent_id, session_id, kind, sort_key, payload, updated_at)"
        " VALUES ('u1','bot1','legacy','turn','TURN#old','{\"user_message\": \"legacy q\", \"assistant_response\": \"a\"}',1.0)"
    )
    raw.commit()
    raw.close()
    legacy = await st.load_conversation("u1", "legacy", agent_id="bot1")  # index not ready: legacy read, not an error
    assert [m["content"] for m in legacy if m["role"] == "user"] == ["legacy q"]


async def test_turn_tombstones_hide_a_turn_on_every_read_path_before_cleanup(storage, cold):
    await storage.store_turn(_turn("t1", sec=1))
    await storage.store_turn(_turn("t2", sec=2))
    await cold.put_tombstone("u1", "bot1", "s1", "t1")  # delete_turn acknowledged, cleanup not run yet
    assert await _hot_ids(storage) == ["t1", "t2"]
    users = [m["content"] for m in await storage.load_conversation("u1", "s1", agent_id="bot1") if m["role"] == "user"]
    assert users == ["q-t2"]  # Redis hot read
    ctx = await storage.get_context_for_agent("u1", "s1", agent_id="bot1")
    assert all("q-t1" not in m["content"] for m in ctx)
    # the cold fallback (hot tier empty) and the legacy query_turns fallback
    cold_only = ChatStorage(dynamodb=cold)
    assert [
        m["content"] for m in await cold_only.load_conversation("u1", "s1", agent_id="bot1") if m["role"] == "user"
    ] == ["q-t2"]
    import sqlite3

    raw = sqlite3.connect(str(cold._path))
    for tid in ("old1", "old2"):
        raw.execute(
            "INSERT INTO conversations (user_id, agent_id, session_id, kind, sort_key, payload, updated_at)"
            " VALUES ('u1','bot1','legacy','turn',?, ?, 1.0)",
            (f"TURN#{tid}", f'{{"user_message": "legacy {tid}", "assistant_response": "a"}}'),
        )
    raw.commit()
    raw.close()
    await cold.put_tombstone("u1", "bot1", "legacy", "old1")
    legacy = [
        m["content"] for m in await cold_only.load_conversation("u1", "legacy", agent_id="bot1") if m["role"] == "user"
    ]
    assert legacy == ["legacy old2"]


async def test_titles_and_threads_cannot_be_recreated_for_a_deleted_session(storage, cold):
    await storage.delete_conversation("u1", "s1", "bot1")
    with pytest.raises(ConversationDeletedError):
        await storage.update_conversation_title("s1", "revived", user_id="u1", agent_id="bot1")
    with pytest.raises(ConversationDeletedError):
        await storage.create_conversation("u1", "s1", "bot1", title="again")
    with pytest.raises(ConversationDeletedError):
        await storage.assert_conversation_active("u1", "bot1", "s1")
    assert await cold.query_threads("u1", "bot1", limit=10) == []  # no thread row was resurrected


class _CountingBackend:
    """Delegates to the real SQLite backend and counts every call by method name."""

    def __init__(self, inner) -> None:
        self._inner, self.calls = inner, []

    def __getattr__(self, name):
        attr = getattr(self._inner, name)
        if not callable(attr):
            return attr

        async def _wrapped(*a, **kw):
            self.calls.append(name)
            return await attr(*a, **kw)

        return _wrapped


async def test_a_read_costs_a_bounded_number_of_backend_calls_not_one_per_turn(storage, cold):
    for i in range(1, 21):
        await storage.store_turn(_turn(f"t{i}", sec=i))
    await cold.put_tombstone("u1", "bot1", "s1", "t3")
    counting = _CountingBackend(cold)
    storage._dynamo = counting
    users = [
        m["content"]
        for m in await storage.load_conversation("u1", "s1", agent_id="bot1", limit=50)
        if m["role"] == "user"
    ]
    assert "q-t3" not in users and len(users) == 19  # Redis hot read, tombstone honoured
    assert counting.calls.count("deleted_turn_ids") == 1
    assert counting.calls.count("is_deleted") <= 1  # the session guard only; never per turn
    assert len(counting.calls) <= 3


async def test_limit_is_applied_after_filtering_tombstoned_turns(storage, cold):
    for i in range(1, 6):
        await storage.store_turn(_turn(f"t{i}", sec=i))
    await cold.put_tombstone("u1", "bot1", "s1", "t5")  # the two NEWEST turns are tombstoned
    await cold.put_tombstone("u1", "bot1", "s1", "t4")
    hot = [
        m["content"]
        for m in await storage.load_conversation("u1", "s1", agent_id="bot1", limit=3)
        if m["role"] == "user"
    ]
    assert hot == ["q-t1", "q-t2", "q-t3"]  # 3 live turns, not 1
    cold_only = ChatStorage(dynamodb=cold)
    window = [
        m["content"]
        for m in await cold_only.load_conversation("u1", "s1", agent_id="bot1", limit=3)
        if m["role"] == "user"
    ]
    assert window == ["q-t1", "q-t2", "q-t3"]


async def test_legacy_fallback_returns_limit_live_turns_when_tombstoned_ones_come_first(cold):
    import sqlite3

    raw = sqlite3.connect(str(cold._path))
    for i in range(1, 6):
        raw.execute(
            "INSERT INTO conversations (user_id, agent_id, session_id, kind, sort_key, payload, updated_at)"
            " VALUES ('u1','bot1','legacy2','turn',?, ?, 1.0)",
            (f"TURN#o{i}", f'{{"user_message": "legacy o{i}", "assistant_response": "a"}}'),
        )
    raw.commit()
    raw.close()
    await cold.put_tombstone("u1", "bot1", "legacy2", "o1")
    await cold.put_tombstone("u1", "bot1", "legacy2", "o2")
    got = [
        m["content"]
        for m in await ChatStorage(dynamodb=cold).load_conversation("u1", "legacy2", agent_id="bot1", limit=3)
        if m["role"] == "user"
    ]
    assert got == ["legacy o3", "legacy o4", "legacy o5"]


def _chat(backend) -> ChatStorage:
    """A ChatStorage over ``backend`` with no hot tier."""
    st = ChatStorage(dynamodb=backend)
    st._initialized = True
    return st


async def _seed_threads(cold, count: int) -> None:
    for i in range(count):
        sid = f"s{i:02d}"
        await cold.put_thread("u1", "bot1", sid, {"title": sid, "session_id": sid, "agent_id": "bot1"})


async def _newest_first(cold, agent: str = "bot1") -> list:
    """Session ids in the backend's own listing order (SQLite: insertion time, newest first)."""
    return [t["session_id"] for t in await cold.query_threads("u1", agent, limit=500)]


async def test_listing_reads_session_tombstones_once_per_agent_and_keeps_order(cold):
    await _seed_threads(cold, 20)
    for sid in ("s03", "s07", "s15"):
        await cold.put_tombstone("u1", "bot1", sid)
    await cold.put_tombstone("u1", "bot1", "s05", "t1")  # a turn tombstone does not hide its thread
    expected = [sid for sid in await _newest_first(cold) if sid not in {"s03", "s07", "s15"}]
    counting = _CountingBackend(cold)
    listed = await _chat(counting).list_user_conversations("u1", agent_id="bot1")
    assert [t["session_id"] for t in listed] == expected and len(expected) == 17  # tombstoned hidden, order kept
    assert counting.calls == ["query_threads", "deleted_session_ids"]  # one batched read, never one per thread


async def test_listing_returns_limit_live_threads_when_tombstoned_ones_fill_the_window(cold):
    await _seed_threads(cold, 10)
    order = await _newest_first(cold)
    for sid in order[:3]:  # the three newest threads are deleted, their cleanup has not run yet
        await cold.put_tombstone("u1", "bot1", sid)
    counting = _CountingBackend(cold)
    listed = await _chat(counting).list_user_conversations("u1", agent_id="bot1", limit=5)
    assert [t["session_id"] for t in listed] == order[3:8]  # limit counts LIVE threads
    assert counting.calls.count("query_threads") == 2  # the short window is read once more, larger
    assert counting.calls.count("deleted_session_ids") == 2  # the re-read checks only threads not seen yet
    assert "is_deleted" not in counting.calls


async def test_listing_does_not_requery_past_the_since_cutoff(cold):
    for i in range(6):  # payload updated_at grows in insertion order, the order SQLite lists threads in
        sid = f"s{i:02d}"
        stamp = (T0 + timedelta(minutes=i)).isoformat()
        await cold.put_thread(
            "u1", "bot1", sid, {"title": sid, "session_id": sid, "agent_id": "bot1", "updated_at": stamp}
        )
    await cold.put_tombstone("u1", "bot1", "s05")
    counting = _CountingBackend(cold)
    listed = await _chat(counting).list_user_conversations(
        "u1", agent_id="bot1", limit=6, since=T0 + timedelta(minutes=2)
    )
    assert [t["session_id"] for t in listed] == ["s04", "s03", "s02"]
    assert counting.calls.count("query_threads") == 1  # older rows cannot pass ``since``: no re-read


async def test_listing_groups_tombstone_reads_by_agent(cold):
    # Without agent_id the listing reads the "" partition; each thread's own agent_id keys its tombstone.
    for sid, owner in (("a1", "bot1"), ("a2", "bot2"), ("a3", "bot1"), ("a4", "bot2")):
        await cold.put_thread("u1", "", sid, {"title": sid, "session_id": sid, "agent_id": owner})
    await cold.put_tombstone("u1", "bot2", "a2")
    await cold.put_tombstone("u1", "bot2", "a3")  # a3 belongs to bot1: another agent's tombstone does not hide it
    expected = [sid for sid in await _newest_first(cold, "") if sid != "a2"]
    counting = _CountingBackend(cold)
    listed = await _chat(counting).list_user_conversations("u1")
    assert [t["session_id"] for t in listed] == expected
    assert counting.calls.count("deleted_session_ids") == 2  # one read per distinct agent, not per thread


@pytest.mark.parametrize("failure", [StorageUnavailableError("cold store down"), RuntimeError("driver bug")])
async def test_listing_fails_closed_when_the_batched_tombstone_read_fails(cold, monkeypatch, failure):
    await _seed_threads(cold, 10)

    async def down(*a, **kw):
        raise failure

    monkeypatch.setattr(cold, "deleted_session_ids", down)
    with pytest.raises(StorageUnavailableError):  # never an empty or unfiltered listing
        await _chat(cold).list_user_conversations("u1", agent_id="bot1")


async def test_fence_makes_one_tombstone_read_on_a_live_session(cold):
    st = _chat(cold)
    turn = _turn("t1", sec=1)
    await st.store_turn(turn)
    counting = _CountingBackend(cold)
    st._dynamo = counting
    await st._fence_after_write(turn)
    assert counting.calls == ["is_deleted"]  # session OR turn in one read


@pytest.mark.parametrize("scope", ["session", "turn"])
async def test_fence_still_cleans_up_session_and_turn_deletions(cold, scope):
    st = _chat(cold)
    turn = _turn("t1", sec=1)
    await st.store_turn(turn)
    await cold.put_tombstone("u1", "bot1", "s1", None if scope == "session" else "t1")
    counting = _CountingBackend(cold)
    st._dynamo = counting
    with pytest.raises(ConversationDeletedError):
        await st._fence_after_write(turn)
    assert counting.calls.count("is_deleted") == 2  # the second read tells a session deletion from a turn one
    assert ("delete_thread_cascade" in counting.calls) is (scope == "session")


@pytest.mark.parametrize("hot_outcome", ["miss", "error"])
async def test_context_fallback_reads_the_guard_and_the_hot_tier_once(cold, hot_outcome):
    st = ChatStorage(dynamodb=cold)
    st._initialized = True
    await st.store_turn(_turn("t1", sec=1))
    await st.store_turn(_turn("t2", sec=2))
    hot_reads = []

    async def get_history(user_id, session_id, chatbot_id=None):
        hot_reads.append(session_id)
        if hot_outcome == "error":
            raise ConnectionError("redis down")
        return None  # evicted / expired from the hot tier

    counting = _CountingBackend(cold)
    st._dynamo = counting
    st._redis = SimpleNamespace(get_history=get_history)
    ctx = await st.get_context_for_agent("u1", "s1", agent_id="bot1")
    assert [m["content"] for m in ctx] == ["q-t1", "a-t1", "q-t2", "a-t2"]
    assert counting.calls.count("is_deleted") == 1  # the guard runs once, not again in the fallback
    assert hot_reads == ["s1"]  # the hot tier is tried once, not again in the fallback
