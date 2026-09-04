"""Lazy legacy re-key on the persistent memory backends (FEAT-524, TASK-2810).

Spec §3 Module 2b, §4 M2b rows.

FEAT-524 unifies the conversation storage key to ``(chatbot, user, session)``.
Redis history keys carry **no TTL** (``memory/redis.py`` — the only ``expire``
call is commented out), so every history written under the old un-segmented
key would be orphaned forever the moment bots start reading under the new one.
``get_history()`` therefore falls back to the legacy key once, copies the
record under the segmented key, and leaves the legacy record untouched.

``fakeredis`` is not installed in this environment, so the Redis tests drive
``RedisConversation`` against :class:`_FakeRedis` — a small in-process double
implementing only the handful of commands the backend uses. That exercises the
real backend logic (key derivation, hash serialization, the fallback branch)
and, unlike a live server, lets the tests *count* reads to prove the legacy key
is not consulted twice.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

import pytest

from parrot.memory import ConversationTurn, FileConversationMemory, RedisConversation


class _FakeRedis:
    """Minimal async Redis double: hashes, strings and sets, plus a read log."""

    def __init__(self) -> None:
        self.hashes: Dict[str, Dict[str, str]] = {}
        self.strings: Dict[str, str] = {}
        self.sets: Dict[str, Set[str]] = {}
        #: Every key passed to a read command, in order — lets tests assert
        #: which keys were consulted and how many times.
        self.reads: List[str] = []

    async def hgetall(self, key: str) -> Dict[str, str]:
        self.reads.append(key)
        return dict(self.hashes.get(key, {}))

    async def hset(self, key: str, mapping: Optional[Dict[str, Any]] = None, **kwargs: Any) -> int:
        entry = self.hashes.setdefault(key, {})
        entry.update({k: str(v) for k, v in (mapping or {}).items()})
        return len(entry)

    async def hget(self, key: str, field: str) -> Optional[str]:
        self.reads.append(key)
        return self.hashes.get(key, {}).get(field)

    async def get(self, key: str) -> Optional[str]:
        self.reads.append(key)
        return self.strings.get(key)

    async def set(self, key: str, value: str) -> bool:
        self.strings[key] = value
        return True

    async def sadd(self, key: str, *values: str) -> int:
        self.sets.setdefault(key, set()).update(values)
        return len(values)

    async def smembers(self, key: str) -> Set[str]:
        return set(self.sets.get(key, set()))

    def exists_key(self, key: str) -> bool:
        """True when ``key`` holds a hash or a string."""
        return bool(self.hashes.get(key)) or key in self.strings


@pytest.fixture(params=[True, False], ids=["hash_storage", "string_storage"])
def redis_memory(request) -> RedisConversation:
    """A ``RedisConversation`` backed by :class:`_FakeRedis`.

    Parametrized over both storage modes because the legacy fallback has to
    work for each — they take different code paths in ``_load_history``.
    """
    memory = RedisConversation.__new__(RedisConversation)
    # Bypass __init__: it would build a real redis.asyncio client from a URL.
    super(RedisConversation, memory).__init__()
    memory.redis_url = "redis://fake"
    memory.key_prefix = "conversation"
    memory.use_hash_storage = request.param
    memory.redis = _FakeRedis()
    return memory


def _turn(turn_id: str = "t1") -> ConversationTurn:
    """A legacy-shaped turn: no ``chatbot_id`` (predates attribution)."""
    return ConversationTurn(turn_id, "u", "q", "a")


# ---------------------------------------------------------------------------
# Redis backend
# ---------------------------------------------------------------------------


async def test_legacy_key_rekey_redis(redis_memory: RedisConversation):
    """A history under the legacy key is returned and copied, legacy kept."""
    await redis_memory.create_history("u", "s")
    await redis_memory.add_turn("u", "s", _turn())

    legacy_key = redis_memory._get_key("u", "s", None)
    segmented_key = redis_memory._get_key("u", "s", "bot")
    assert legacy_key == "conversation:u:s"
    assert segmented_key == "conversation:bot:u:s"
    assert not redis_memory.redis.exists_key(segmented_key)

    history = await redis_memory.get_history("u", "s", chatbot_id="bot")

    assert history is not None
    assert history.chatbot_id == "bot"
    assert len(history.turns) == 1
    assert history.turns[0].user_message == "q"
    # Copied under the new key, and the legacy record still exists.
    assert redis_memory.redis.exists_key(segmented_key)
    assert redis_memory.redis.exists_key(legacy_key)


async def test_legacy_rekey_redis_keeps_turns_unattributed(redis_memory: RedisConversation):
    """Copied turns keep ``chatbot_id=None`` — they predate attribution."""
    await redis_memory.create_history("u", "s")
    await redis_memory.add_turn("u", "s", _turn())

    history = await redis_memory.get_history("u", "s", chatbot_id="bot")

    assert history.turns[0].chatbot_id is None


async def test_legacy_rekey_redis_second_read_ignores_legacy(redis_memory: RedisConversation):
    """Once re-keyed, the legacy key is never consulted again."""
    await redis_memory.create_history("u", "s")
    await redis_memory.add_turn("u", "s", _turn())
    legacy_key = redis_memory._get_key("u", "s", None)

    await redis_memory.get_history("u", "s", chatbot_id="bot")
    redis_memory.redis.reads.clear()

    history = await redis_memory.get_history("u", "s", chatbot_id="bot")

    assert history is not None
    assert legacy_key not in redis_memory.redis.reads
    assert redis_memory.redis.reads == [redis_memory._get_key("u", "s", "bot")]


async def test_legacy_rekey_noop_when_segmented_exists(redis_memory: RedisConversation):
    """A segmented record present ⇒ the legacy record is never read."""
    await redis_memory.create_history("u", "s")
    await redis_memory.add_turn("u", "s", _turn("legacy-turn"))
    await redis_memory.create_history("u", "s", chatbot_id="bot")
    await redis_memory.add_turn("u", "s", _turn("segmented-turn"), chatbot_id="bot")
    redis_memory.redis.reads.clear()

    history = await redis_memory.get_history("u", "s", chatbot_id="bot")

    assert [t.turn_id for t in history.turns] == ["segmented-turn"]
    assert redis_memory._get_key("u", "s", None) not in redis_memory.redis.reads


async def test_redis_no_rekey_without_chatbot_id(redis_memory: RedisConversation):
    """Without a ``chatbot_id`` there is nothing to migrate to — plain read."""
    await redis_memory.create_history("u", "s")
    # add_turn is what actually materializes the record in hash mode: on `dev`
    # RedisConversation.create_history builds its hash `mapping` and never
    # hset()s it (pre-existing bug, out of FEAT-524's scope).
    await redis_memory.add_turn("u", "s", _turn())

    history = await redis_memory.get_history("u", "s")

    assert history is not None
    assert history.chatbot_id is None


async def test_redis_returns_none_when_neither_key_exists(redis_memory: RedisConversation):
    """Missing everywhere still means ``None``, not an empty history."""
    assert await redis_memory.get_history("u", "s", chatbot_id="bot") is None


async def test_redis_rekey_registers_session_for_chatbot(redis_memory: RedisConversation):
    """``list_sessions(user, chatbot_id)`` finds the migrated session.

    ``update_history`` only writes the history key; without the extra ``sadd``
    the re-keyed conversation would be invisible to ``list_sessions`` under its
    new chatbot segment.
    """
    await redis_memory.create_history("u", "s")
    await redis_memory.add_turn("u", "s", _turn())

    await redis_memory.get_history("u", "s", chatbot_id="bot")

    assert await redis_memory.list_sessions("u", "bot") == ["s"]


async def test_redis_rekey_is_idempotent(redis_memory: RedisConversation):
    """Two concurrent-style first reads copy the same content — race is benign."""
    await redis_memory.create_history("u", "s")
    await redis_memory.add_turn("u", "s", _turn())

    first = await redis_memory.get_history("u", "s", chatbot_id="bot")
    second = await redis_memory.get_history("u", "s", chatbot_id="bot")

    assert first.to_dict()["turns"] == second.to_dict()["turns"]
    assert len(second.turns) == 1


# ---------------------------------------------------------------------------
# File backend
# ---------------------------------------------------------------------------


@pytest.fixture
def file_memory(tmp_path) -> FileConversationMemory:
    """A ``FileConversationMemory`` rooted in a temp directory."""
    return FileConversationMemory(base_path=str(tmp_path))


async def test_legacy_key_rekey_file(file_memory: FileConversationMemory):
    """Legacy file is read, copied to the segmented path, and left in place."""
    await file_memory.create_history("u", "s")
    await file_memory.add_turn("u", "s", _turn())

    history = await file_memory.get_history("u", "s", chatbot_id="bot")

    assert history is not None
    assert history.chatbot_id == "bot"
    assert len(history.turns) == 1
    assert file_memory._get_file_path("u", "s", "bot").exists()
    assert file_memory._get_file_path("u", "s", None).exists()


async def test_legacy_rekey_file_keeps_turns_unattributed(file_memory: FileConversationMemory):
    """Copied turns keep ``chatbot_id=None``."""
    await file_memory.create_history("u", "s")
    await file_memory.add_turn("u", "s", _turn())

    history = await file_memory.get_history("u", "s", chatbot_id="bot")

    assert history.turns[0].chatbot_id is None


async def test_legacy_rekey_file_noop_when_segmented_exists(file_memory: FileConversationMemory):
    """A segmented file present ⇒ the legacy file is not consulted."""
    await file_memory.create_history("u", "s")
    await file_memory.add_turn("u", "s", _turn("legacy-turn"))
    await file_memory.create_history("u", "s", chatbot_id="bot")
    await file_memory.add_turn("u", "s", _turn("segmented-turn"), chatbot_id="bot")

    history = await file_memory.get_history("u", "s", chatbot_id="bot")

    assert [t.turn_id for t in history.turns] == ["segmented-turn"]


async def test_file_legacy_record_is_not_mutated(file_memory: FileConversationMemory):
    """Re-keying must not rewrite the legacy file (rollback safety)."""
    await file_memory.create_history("u", "s")
    await file_memory.add_turn("u", "s", _turn())
    legacy_path = file_memory._get_file_path("u", "s", None)
    before = legacy_path.read_text(encoding="utf-8")

    await file_memory.get_history("u", "s", chatbot_id="bot")

    assert legacy_path.read_text(encoding="utf-8") == before
    assert '"chatbot_id": null' in before or '"chatbot_id":null' in before


async def test_file_no_rekey_without_chatbot_id(file_memory: FileConversationMemory):
    """Without a ``chatbot_id`` the legacy path is read as-is."""
    await file_memory.create_history("u", "s")

    history = await file_memory.get_history("u", "s")

    assert history is not None
    assert history.chatbot_id is None


async def test_file_returns_none_when_neither_path_exists(file_memory: FileConversationMemory):
    """Missing everywhere still means ``None``."""
    assert await file_memory.get_history("u", "s", chatbot_id="bot") is None


async def test_file_get_history_does_not_deadlock_on_rekey(file_memory: FileConversationMemory):
    """The re-key write happens under the SAME lock acquisition as the read.

    ``FileConversationMemory._lock`` is a plain ``asyncio.Lock`` — not
    reentrant. Calling ``update_history()`` (which takes the lock) from inside
    ``get_history()`` (which already holds it) would hang forever. This test
    would time out rather than fail if that regressed.
    """
    import asyncio

    await file_memory.create_history("u", "s")

    history = await asyncio.wait_for(
        file_memory.get_history("u", "s", chatbot_id="bot"), timeout=5
    )

    assert history is not None
    # And the lock is properly released afterwards.
    assert not file_memory._lock.locked()
    assert await file_memory.get_history("u", "s", chatbot_id="bot") is not None


async def test_file_update_history_still_works(file_memory: FileConversationMemory):
    """The public ``update_history`` still takes the lock and writes."""
    history = await file_memory.create_history("u", "s", chatbot_id="bot")
    history.add_turn(_turn())

    await file_memory.update_history(history)

    reloaded = await file_memory.get_history("u", "s", chatbot_id="bot")
    assert len(reloaded.turns) == 1
    assert not file_memory._lock.locked()
