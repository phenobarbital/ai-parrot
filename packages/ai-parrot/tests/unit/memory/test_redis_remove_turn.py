"""issue:afbd39c93c94 — ``RedisConversation.remove_turn`` drops one turn in ONE compare-and-swap write.

Runs against a real Redis (db 15, isolated key prefix) and skips explicitly when none answers.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, AsyncIterator, Awaitable, Callable, List

import pytest

from parrot.memory import ConversationTurn, InMemoryConversation
from parrot.memory.redis import RedisConversation

REDIS_TEST_URL = "redis://localhost:6379/15"
_SKIP_REASON = (
    "no Redis reachable at " + REDIS_TEST_URL + " — the remove_turn CAS cases did not run. "
    "This is an ENVIRONMENTAL SKIP, not a pass."
)


async def _redis_available() -> bool:
    """Return whether a Redis server answers on the test URL."""
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


def _turn(turn_id: str) -> ConversationTurn:
    return ConversationTurn(turn_id=turn_id, user_id="u", user_message=f"q-{turn_id}", assistant_response="a")


@pytest.fixture(params=[True, False], ids=["hash", "string"])
async def memory(request) -> AsyncIterator[RedisConversation]:
    """A ``RedisConversation`` on an isolated prefix (hash and string storage), cleaned up after."""
    if not await _redis_available():
        pytest.skip(_SKIP_REASON)
    prefix = f"rmturn_{uuid.uuid4().hex[:10]}"
    store = RedisConversation(redis_url=REDIS_TEST_URL, key_prefix=prefix, use_hash_storage=request.param)
    try:
        yield store
    finally:
        keys = [k async for k in store.redis.scan_iter(match=f"{prefix}*")]
        if keys:
            await store.redis.delete(*keys)
        await store.close()


async def _seed(memory: RedisConversation, *turn_ids: str, chatbot_id: str | None = "bot") -> None:
    await memory.create_history("u", "s", chatbot_id=chatbot_id)
    for turn_id in turn_ids:
        await memory.add_turn("u", "s", _turn(turn_id), chatbot_id=chatbot_id)


async def _turn_ids(memory: RedisConversation, chatbot_id: str | None = "bot") -> List[str]:
    history = await memory.get_history("u", "s", chatbot_id=chatbot_id)
    return [t.turn_id for t in history.turns] if history else []


class _ReadHookPipeline:
    """Wraps a redis pipeline and awaits ``on_read`` right after the WATCHed read — the race window."""

    def __init__(self, inner: Any, on_read: Callable[[], Awaitable[None]]) -> None:
        self._inner = inner
        self._on_read = on_read

    async def __aenter__(self) -> "_ReadHookPipeline":
        await self._inner.__aenter__()
        return self

    async def __aexit__(self, *exc: Any) -> Any:
        return await self._inner.__aexit__(*exc)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def hget(self, *args: Any, **kwargs: Any) -> Any:
        value = await self._inner.hget(*args, **kwargs)
        await self._on_read()
        return value

    async def get(self, *args: Any, **kwargs: Any) -> Any:
        value = await self._inner.get(*args, **kwargs)
        await self._on_read()
        return value


async def test_remove_turn_drops_only_that_turn(memory):
    await _seed(memory, "t1", "t2")
    assert await memory.remove_turn("u", "s", "t1", chatbot_id="bot") is True
    assert await _turn_ids(memory) == ["t2"]
    assert await memory.remove_turn("u", "s", "t1", chatbot_id="bot") is False  # idempotent
    assert await memory.remove_turn("u", "s", "nope", chatbot_id="bot") is False
    assert await memory.remove_turn("u", "missing", "t2", chatbot_id="bot") is False
    assert await _turn_ids(memory) == ["t2"]


async def test_a_turn_appended_between_the_read_and_the_write_survives(memory, monkeypatch):
    """The WATCHed key changes after the read: EXEC aborts, the filter re-runs, the new turn is kept."""
    await _seed(memory, "t1", "t2")
    other = RedisConversation(
        redis_url=REDIS_TEST_URL, key_prefix=memory.key_prefix, use_hash_storage=memory.use_hash_storage
    )
    reads: List[int] = []

    async def concurrent_append() -> None:
        reads.append(1)
        if len(reads) == 1:  # only inside the first attempt's window
            await other.add_turn("u", "s", _turn("t3"), chatbot_id="bot")

    real_pipeline = memory.redis.pipeline
    monkeypatch.setattr(
        memory.redis, "pipeline", lambda *a, **kw: _ReadHookPipeline(real_pipeline(*a, **kw), concurrent_append)
    )
    try:
        assert await memory.remove_turn("u", "s", "t1", chatbot_id="bot") is True
    finally:
        await other.close()
    assert len(reads) >= 2, "the conflicting write must force a retry"
    assert await _turn_ids(memory) == ["t2", "t3"]


async def test_remove_turn_keeps_the_metadata(memory):
    await _seed(memory, "t1", "t2")
    await memory.merge_metadata("u", "s", "bot", mutate=lambda meta: {**meta, "task_memory": {"k": "v"}})
    assert await memory.remove_turn("u", "s", "t1", chatbot_id="bot") is True
    assert (await memory.read_metadata("u", "s", "bot") or {}).get("task_memory") == {"k": "v"}


async def test_a_legacy_history_is_rekeyed_before_the_removal(memory):
    """FEAT-524: a history only under the un-segmented key is migrated, then the turn leaves the segmented copy."""
    await _seed(memory, "t1", "t2", chatbot_id=None)
    assert await memory.remove_turn("u", "s", "t1", chatbot_id="bot") is True
    assert await _turn_ids(memory, chatbot_id="bot") == ["t2"]


async def test_the_base_default_removes_from_an_in_memory_history():
    """``ConversationMemory.remove_turn`` (the default every backend inherits) keeps the other turns."""
    memory = InMemoryConversation()
    await memory.create_history("u", "s", chatbot_id="bot")
    for turn_id in ("t1", "t2"):
        await memory.add_turn("u", "s", _turn(turn_id), chatbot_id="bot")
    assert await memory.remove_turn("u", "s", "t1", chatbot_id="bot") is True
    assert [t.turn_id for t in (await memory.get_history("u", "s", chatbot_id="bot")).turns] == ["t2"]
    assert await memory.remove_turn("u", "s", "t1", chatbot_id="bot") is False
    assert await memory.remove_turn("u", "other", "t2", chatbot_id="bot") is False
