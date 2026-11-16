"""FEAT-886 M13 — guarded NX install, pending merge, sequence allocation (real backends)."""
from __future__ import annotations

import asyncio
import shutil
import socket
import subprocess
import time
from datetime import datetime, timedelta, timezone

import pytest

from parrot.memory import (
    ConversationHistory,
    ConversationMemory,
    ConversationTurn,
    FileConversationMemory,
    InMemoryConversation,
    LocalSequenceAllocator,
    RedisConversation,
    RedisSequenceAllocator,
)
from parrot.memory.compaction.models import ToolInvocation, ToolStatus

T0 = datetime(2026, 11, 1, 10, 0, 0, tzinfo=timezone.utc)


def _turn(tid: str, sec: int, seq: int | None = None, **kw) -> ConversationTurn:
    return ConversationTurn(turn_id=tid, user_id="u", user_message=f"q{tid}", assistant_response=f"a{tid}",
                            timestamp=T0 + timedelta(seconds=sec), sequence=seq, chatbot_id="bot", **kw)


@pytest.fixture(scope="module")
def redis_url(tmp_path_factory):
    binary = shutil.which("redis-server")
    if not binary:
        pytest.skip("redis-server not installed")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    proc = subprocess.Popen([binary, "--port", str(port), "--save", "", "--appendonly", "no",
                             "--dir", str(tmp_path_factory.mktemp("redis"))],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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


@pytest.fixture(params=["memory", "file", "redis-hash", "redis-string"])
async def memory(request, tmp_path):
    kind = request.param
    if kind == "memory":
        yield InMemoryConversation()
    elif kind == "file":
        yield FileConversationMemory(base_path=str(tmp_path))
    else:
        url = request.getfixturevalue("redis_url")
        m = RedisConversation(redis_url=url, key_prefix=f"hyd-{request.node.name}", use_hash_storage=kind == "redis-hash")
        yield m
        await m.redis.aclose()


async def test_nx_install_first_wins_and_never_overwrites(memory):
    assert await memory.install_history("u", "s", [_turn("a", 1), _turn("b", 2)], chatbot_id="bot") is True
    assert await memory.install_history("u", "s", [_turn("z", 9)], chatbot_id="bot") is False
    history = await memory.get_history("u", "s", chatbot_id="bot")
    assert [t.turn_id for t in history.turns] == ["a", "b"]


async def test_two_racing_installs_exactly_one_wins(memory):
    results = await asyncio.gather(
        memory.install_history("u", "race", [_turn("a", 1)], chatbot_id="bot"),
        memory.install_history("u", "race", [_turn("b", 2)], chatbot_id="bot"),
    )
    assert sorted(results) == [False, True]
    history = await memory.get_history("u", "race", chatbot_id="bot")
    assert len(history.turns) == 1  # the winner's complete history, never a mix


async def test_pending_history_merges_older_turns_idempotently(memory):
    await memory.create_history("u", "p", metadata={"hydration": {"state": "pending"}, "compaction": {"k": 1}},
                                chatbot_id="bot")
    await memory.add_turn("u", "p", _turn("new", 50, 5), chatbot_id="bot")
    assert await memory.install_history("u", "p", [_turn("old1", 1, 1), _turn("old2", 2, 2), _turn("new", 50, 5),
                                                   _turn("later", 99, 9)], chatbot_id="bot") is True
    history = await memory.get_history("u", "p", chatbot_id="bot")
    assert [t.turn_id for t in history.turns] == ["old1", "old2", "new"]  # newer / duplicate turns dropped
    assert "hydration" not in history.metadata and history.metadata.get("compaction") == {"k": 1}
    # the marker is gone: a second install is a no-op
    assert await memory.install_history("u", "p", [_turn("x", 0)], chatbot_id="bot") is False


async def test_non_pending_history_is_never_touched(memory):
    await memory.create_history("u", "n", metadata={"hydration": {"state": "complete"}}, chatbot_id="bot")
    assert await memory.install_history("u", "n", [_turn("a", 1)], chatbot_id="bot") is False
    assert (await memory.get_history("u", "n", chatbot_id="bot")).turns == []


async def test_install_stages_turns_like_add_turn(memory):
    big = "x" * 60_000
    turn = _turn("t", 1, tool_invocations=[ToolInvocation(tool_name="q", input={}, output=big,
                                                          status=ToolStatus.COMPLETED)])
    await memory.install_history("u", "stage", [turn], chatbot_id="bot")
    stored = (await memory.get_history("u", "stage", chatbot_id="bot")).turns[0]
    assert stored.schema_version == 2 and stored.token_count is not None
    assert "output" in stored.tool_invocations[0].omitted and len(stored.tool_invocations[0].output) < len(big)


async def test_redis_create_history_persists_metadata_in_hash_mode(redis_url):
    m = RedisConversation(redis_url=redis_url, key_prefix="hyd-create", use_hash_storage=True)
    try:
        await m.create_history("u", "c", metadata={"hydration": {"state": "pending"}}, chatbot_id="bot")
        history = await m.get_history("u", "c", chatbot_id="bot")
        assert history is not None and history.metadata == {"hydration": {"state": "pending"}}
    finally:
        await m.redis.aclose()


def test_custom_backend_without_install_primitive_is_abstract():
    class _Legacy(ConversationMemory):
        pass

    assert "_install_history" in ConversationMemory.__abstractmethods__
    with pytest.raises(TypeError):
        _Legacy()  # type: ignore[abstract]


async def test_local_allocator_is_monotonic_and_recovers_from_floor():
    alloc = LocalSequenceAllocator()
    calls = []

    async def floor():
        calls.append(1)
        return 41

    first = await alloc.next("a", "u", "s", floor=floor)
    others = await asyncio.gather(*(alloc.next("a", "u", "s", floor=floor) for _ in range(20)))
    assert first == 42 and sorted(others) == list(range(43, 63)) and len(calls) == 1
    assert await alloc.next("a", "u", "other") == 1  # no floor: starts at 1


async def test_redis_allocator_recovers_from_floor_and_converges(redis_url):
    from redis.asyncio import Redis

    client = Redis.from_url(redis_url, decode_responses=True)
    try:
        alloc = RedisSequenceAllocator(client, key_prefix="hyd-seq")

        async def floor():
            return 100

        values = await asyncio.gather(*(alloc.next("a", "u", "s", floor=floor) for _ in range(10)))
        assert sorted(values) == list(range(101, 111))
        assert await client.ttl("hyd-seq:seq:a:u:s") == -1  # no TTL
        await client.delete("hyd-seq:seq:a:u:s")  # counter loss
        assert await alloc.next("a", "u", "s", floor=floor) == 101  # recovered from the durable maximum
    finally:
        await client.aclose()
