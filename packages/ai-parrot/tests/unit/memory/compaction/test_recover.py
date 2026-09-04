"""Unit tests for FEAT-525 read_omitted_content recovery tool."""

import pytest

from parrot.memory import InMemoryConversation
from parrot.memory.compaction.omission import EXPIRED_MESSAGE
from parrot.memory.compaction.recover import NO_ARGS_MESSAGE, UNAVAILABLE_MESSAGE, bind_read_omitted_content
from parrot.observability.context import invocation_context


@pytest.fixture
def memory():
    return InMemoryConversation()


async def test_read_omitted_content_fail_closed(memory, monkeypatch):
    calls = []
    monkeypatch.setattr(memory.omission_store, "get", lambda *a, **k: calls.append(a))
    fn = bind_read_omitted_content(memory)
    assert await fn(content_id="om_x") == UNAVAILABLE_MESSAGE and calls == []
    with invocation_context("bot", user_id="u", session_id=None, memory_key_id="bot"):
        assert await fn(content_id="om_x") == UNAVAILABLE_MESSAGE and calls == []


async def test_read_omitted_content_by_id_and_turn(memory):
    key = memory.omission_key("u", "s", "bot")
    a = await memory.omission_store.put(key, "AAA", turn_id="t1")
    b = await memory.omission_store.put(key, "BBB", turn_id="t1")
    fn = bind_read_omitted_content(memory)
    with invocation_context("bot", user_id="u", session_id="s", memory_key_id="bot"):
        assert await fn(content_id=a) == "AAA"
        assert await fn(content_id="om_ffffffffffffffff") == EXPIRED_MESSAGE.format(
            content_id="om_ffffffffffffffff"
        )
        assert await fn(turn_id="t1") == f'<omitted id="{a}">\nAAA\n</omitted>\n<omitted id="{b}">\nBBB\n</omitted>'
        assert "may have expired" in await fn(turn_id="nope") and await fn() == NO_ARGS_MESSAGE
    with invocation_context("bot", user_id="u", session_id="other", memory_key_id="bot"):
        assert await fn(content_id=a) == EXPIRED_MESSAGE.format(content_id=a)
