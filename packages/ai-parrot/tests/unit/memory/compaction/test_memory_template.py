"""Unit tests for FEAT-525 ConversationMemory.add_turn template method."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from parrot.memory import FileConversationMemory, InMemoryConversation, RedisConversation
from parrot.memory.abstract import ConversationTurn
from parrot.memory.compaction.models import CompactionCommit, ToolInvocation
from parrot.memory.compaction.omission import content_id
from parrot.memory.compaction.tokens import HeuristicCounter


class _FakeRedis:
    """Minimal async fake: hget/hset/hgetall/delete/srem/sadd/smembers/expire over dicts."""

    def __init__(self):
        self._hashes: Dict[str, Dict[str, str]] = {}
        self._sets: Dict[str, set] = {}
        self.hset_calls: List[Dict[str, Any]] = []
        self.expire_calls: List[tuple] = []

    async def hset(self, key, field=None, value=None, mapping=None):
        h = self._hashes.setdefault(key, {})
        if mapping:
            h.update({str(k): str(v) for k, v in mapping.items()})
            self.hset_calls.append({"key": key, "mapping": dict(mapping)})
        else:
            h[field] = value
            self.hset_calls.append({"key": key, "mapping": {field: value}})

    async def hget(self, key, field):
        return self._hashes.get(key, {}).get(field)

    async def hgetall(self, key):
        return dict(self._hashes.get(key, {}))

    async def hdel(self, key, *fields):
        h = self._hashes.get(key, {})
        for f in fields:
            h.pop(f, None)

    async def delete(self, *keys):
        count = 0
        for k in keys:
            if k in self._hashes:
                del self._hashes[k]
                count += 1
            self._sets.pop(k, None)
        return count

    async def sadd(self, key, *values):
        self._sets.setdefault(key, set()).update(values)

    async def srem(self, key, *values):
        s = self._sets.get(key, set())
        for v in values:
            s.discard(v)

    async def smembers(self, key):
        return set(self._sets.get(key, set()))

    async def expire(self, key, ttl):
        self.expire_calls.append((key, ttl))

    async def close(self):
        pass


@pytest.fixture(params=["memory", "file", "redis"])
def memory(request, tmp_path):
    counter = HeuristicCounter()
    if request.param == "memory":
        return InMemoryConversation(token_counter=counter)
    if request.param == "file":
        return FileConversationMemory(str(tmp_path), token_counter=counter)
    m = RedisConversation(redis_url="redis://unused", token_counter=counter)
    m.redis = _FakeRedis()
    m._omission_store = None  # force default RedisOmissionStore rebuild on the fake client
    from parrot.memory.compaction.omission import RedisOmissionStore

    m._omission_store = RedisOmissionStore(m.redis, key_prefix=m.key_prefix)
    return m


async def test_write_time_offload_preview(memory):
    big = "x" * 40_000  # 10_000 heuristic tokens > 2_000
    turn = ConversationTurn(
        turn_id="t1",
        user_id="u",
        user_message="q",
        assistant_response="a",
        chatbot_id="bot",
        tool_invocations=[ToolInvocation(tool_name="query", input={}, output=big)],
    )
    await memory.create_history("u", "s", chatbot_id="bot")
    await memory.add_turn("u", "s", turn, chatbot_id="bot")
    stored = (await memory.get_history("u", "s", chatbot_id="bot")).turns[-1]
    inv = stored.tool_invocations[0]
    assert inv.omitted["output"] == content_id(big)
    assert inv.output_chars == 40_000
    assert inv.output.startswith("x" * 200)
    assert await memory.omission_store.get(memory.omission_key("u", "s", "bot"), inv.omitted["output"]) == big
    assert stored.schema_version == 2
    assert stored.token_count.tokenizer == "heuristic"
    assert stored.norm_version == "1"


async def test_single_write_with_metadata_redis():
    m = RedisConversation(redis_url="redis://unused", token_counter=HeuristicCounter())
    fake = m.redis = _FakeRedis()
    from parrot.memory.compaction.omission import RedisOmissionStore

    m._omission_store = RedisOmissionStore(fake, key_prefix=m.key_prefix)

    await m.create_history("u", "s", chatbot_id="bot")
    turn = ConversationTurn(turn_id="t1", user_id="u", user_message="q", assistant_response="a", chatbot_id="bot")
    fake.hset_calls.clear()
    await m.add_turn("u", "s", turn, chatbot_id="bot", compaction=CompactionCommit(100, "t0", False))
    assert len(fake.hset_calls) == 1
    assert {"turns", "metadata"} <= set(fake.hset_calls[0]["mapping"])


async def test_clear_delete_cascade(memory):
    big = "y" * 40_000
    turn = ConversationTurn(
        turn_id="t1",
        user_id="u",
        user_message="q",
        assistant_response="a",
        chatbot_id="bot",
        tool_invocations=[ToolInvocation(tool_name="query", input={}, output=big)],
    )
    await memory.create_history("u", "s", chatbot_id="bot")
    await memory.add_turn("u", "s", turn, chatbot_id="bot")
    key = memory.omission_key("u", "s", "bot")
    assert await memory.omission_store.list_by_turn(key, "t1") == [content_id(big)]

    await memory.clear_history("u", "s", chatbot_id="bot")
    assert await memory.omission_store.list_by_turn(key, "t1") == []
    assert await memory.omission_store.get(key, content_id(big)) is None


async def test_delete_cascade(memory):
    big = "z" * 40_000
    turn = ConversationTurn(
        turn_id="t1",
        user_id="u",
        user_message="q",
        assistant_response="a",
        chatbot_id="bot",
        tool_invocations=[ToolInvocation(tool_name="query", input={}, output=big)],
    )
    await memory.create_history("u", "s", chatbot_id="bot")
    await memory.add_turn("u", "s", turn, chatbot_id="bot")
    key = memory.omission_key("u", "s", "bot")

    await memory.delete_history("u", "s", chatbot_id="bot")
    assert await memory.omission_store.list_by_turn(key, "t1") == []
    assert await memory.omission_store.get(key, content_id(big)) is None


async def test_normalize_off_escape_hatch():
    m = InMemoryConversation(normalize=False, token_counter=HeuristicCounter())
    await m.create_history("u", "s", chatbot_id="bot")
    turn = ConversationTurn(
        turn_id="t1", user_id="u", user_message="hello   ", assistant_response="world", chatbot_id="bot"
    )
    await m.add_turn("u", "s", turn, chatbot_id="bot")
    stored = (await m.get_history("u", "s", chatbot_id="bot")).turns[-1]
    assert stored.user_message == "hello   "
    assert stored.norm_version is None
    assert stored.token_count is not None


async def test_chat_storage_tier_counted_not_compacted():
    m = RedisConversation(redis_url="redis://unused", key_prefix="chat", token_counter=HeuristicCounter())
    fake = m.redis = _FakeRedis()
    from parrot.memory.compaction.omission import RedisOmissionStore

    m._omission_store = RedisOmissionStore(fake, key_prefix=m.key_prefix)

    await m.create_history("u", "s", chatbot_id="agent")
    turn = ConversationTurn(turn_id="t1", user_id="u", user_message="q", assistant_response="a", chatbot_id="agent")
    await m.add_turn("u", "s", turn, chatbot_id="agent")
    stored = (await m.get_history("u", "s", chatbot_id="agent")).turns[-1]
    assert stored.token_count is not None
    assert stored.norm_version == "1"


async def test_report_usage_updates_calibration_without_writing_turn():
    m = InMemoryConversation(token_counter=HeuristicCounter())
    await m.create_history("u", "s", chatbot_id="bot")
    await m.report_usage("u", "s", estimated_prompt_tokens=100, provider_prompt_tokens=150, chatbot_id="bot")
    history = await m.get_history("u", "s", chatbot_id="bot")
    assert history.turns == []
    assert history.metadata["compaction"]["calibration"] == pytest.approx(1.5)
