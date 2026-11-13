"""FEAT-886 M15 — publish ordering, raw snapshot, failure isolation, ordering stamps, caller turn_id."""
from __future__ import annotations

import ast
import asyncio
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

import parrot.bots as bots_pkg
from parrot.bots.base import BaseBot
from parrot.clients.base import AbstractClient
from parrot.memory import InMemoryConversation
from parrot.memory.compaction.models import ToolInvocation, ToolStatus
from parrot.models import AIMessage
from parrot.models.responses import CompletionUsage


class Client(AbstractClient):
    client_type = "recording"
    supported_models = ["stub"]

    def __init__(self, mode: str = "ok", **kwargs: Any) -> None:
        kwargs.setdefault("model", "stub")
        super().__init__(**kwargs)
        self.mode = mode

    async def get_client(self) -> "Client":
        return self

    async def _ensure_client(self) -> "Client":
        return self

    def _msg(self, prompt: str) -> AIMessage:
        return AIMessage(input=prompt, output="reply", model="stub", provider="stub",
                         usage=CompletionUsage(prompt_tokens=3, completion_tokens=5),
                         turn_id=str(uuid.uuid4()))

    async def ask(self, prompt: str, model: Optional[str] = None, **kwargs: Any) -> AIMessage:
        return self._msg(prompt)

    async def ask_stream(self, prompt: str, **kwargs: Any):
        yield "partial "
        if self.mode == "explode":
            raise RuntimeError("stream died")
        if self.mode == "hang":
            await asyncio.sleep(30)
        yield self._msg(prompt)

    async def resume(self, *a: Any, **kw: Any):
        raise NotImplementedError

    async def invoke(self, *a: Any, **kw: Any):
        raise NotImplementedError


class RecordingPublisher:
    """Real TurnPublisher; records each event and what the memory held when it arrived."""

    def __init__(self, memory: InMemoryConversation, key: str, fail: bool = False) -> None:
        self.events: list = []
        self.memory_at_publish: list = []
        self._memory, self._key, self._fail = memory, key, fail

    async def publish(self, event) -> None:
        history = await self._memory.get_history(event.user_id, event.session_id, chatbot_id=self._key)
        self.memory_at_publish.append([t.turn_id for t in history.turns] if history else None)
        if self._fail:
            raise RuntimeError("outbox full")
        self.events.append(event)


async def _bot(publisher_factory=None, mode="ok", **kw) -> BaseBot:
    bot = BaseBot(name="alpha", chatbot_id="uuid-1", llm=Client(mode=mode), memory_type="memory",
                  injection_detection=False, **kw)
    await bot.configure()
    bot.conversation_memory = InMemoryConversation()
    if publisher_factory is not None:
        bot.turn_publisher = publisher_factory(bot.conversation_memory)
    return bot


async def _round(bot: BaseBot, text: str = "hello", **kw) -> AIMessage:
    return await bot.ask(text, user_id="u", session_id="s", use_vector_context=False, **kw)


async def test_publish_after_add_turn():
    bot = await _bot(lambda mem: RecordingPublisher(mem, "uuid-1"))
    response = await _round(bot)
    pub = bot.turn_publisher
    assert len(pub.events) == 1
    assert pub.memory_at_publish == [[response.turn_id]]  # the turn was already stored when it was published


async def test_event_identity_ordering_and_presentation():
    bot = await _bot(lambda mem: RecordingPublisher(mem, "uuid-1"))
    await _round(bot, "one")
    await _round(bot, "two")
    first, second = bot.turn_publisher.events
    assert first.agent_name == "alpha" and first.chatbot_id == "uuid-1"  # NAME and memory_key_id both travel
    assert first.turn["timestamp"].endswith("+00:00")
    assert second.turn["sequence"] == first.turn["sequence"] + 1 >= 2
    assert first.presentation["model"] == "stub" and first.presentation["usage"]["prompt_tokens"] == 3
    assert first.presentation["response_time_ms"] is not None


async def test_snapshot_is_raw_before_normalization_and_offload():
    bot = await _bot(lambda mem: RecordingPublisher(mem, "uuid-1"))
    big = "x" * 80_000
    from parrot.memory import ConversationTurn

    turn = ConversationTurn(turn_id="t-raw", user_id="u", user_message="q", assistant_response="a",
                            chatbot_id="uuid-1",
                            tool_invocations=[ToolInvocation(tool_name="t", input={}, output=big,
                                                             status=ToolStatus.COMPLETED)])
    await bot.conversation_memory.create_history("u", "s", chatbot_id="uuid-1")
    await bot.save_conversation_turn("u", "s", turn)
    event = bot.turn_publisher.events[0]
    assert event.turn["tool_invocations"][0]["output"] == big  # raw: not the offloaded preview
    stored = (await bot.conversation_memory.get_history("u", "s", chatbot_id="uuid-1")).turns[0]
    assert len(stored.tool_invocations[0].output) < len(big)


async def test_publish_failure_does_not_fail_round(caplog):
    bot = await _bot(lambda mem: RecordingPublisher(mem, "uuid-1", fail=True))
    response = await _round(bot)
    assert response.response == "reply" or response.output == "reply"
    history = await bot.conversation_memory.get_history("u", "s", chatbot_id="uuid-1")
    assert len(history.turns) == 1
    assert any("turn publish failed" in r.getMessage() for r in caplog.records)


async def test_conversation_less_bot_builds_no_event_and_stamps_nothing():
    bot = await _bot()
    assert bot.turn_publisher is None and bot.sequence_allocator is None
    assert bot._turn_presentation(None) is None
    await _round(bot)
    turn = (await bot.conversation_memory.get_history("u", "s", chatbot_id="uuid-1")).turns[0]
    assert turn.sequence is None and turn.timestamp.tzinfo is None  # exactly as today


async def test_ask_honors_caller_turn_id():
    bot = await _bot(lambda mem: RecordingPublisher(mem, "uuid-1"))
    response = await _round(bot, turn_id="client-1")
    assert response.turn_id == "client-1"
    assert bot.turn_publisher.events[0].turn["turn_id"] == "client-1"
    stored = (await bot.conversation_memory.get_history("u", "s", chatbot_id="uuid-1")).turns[0]
    assert stored.turn_id == "client-1"


async def test_conversation_honors_caller_turn_id():
    bot = await _bot(lambda mem: RecordingPublisher(mem, "uuid-1"))
    await bot.conversation("hi", user_id="u", session_id="s2", use_vector_context=False, turn_id="client-2")
    assert bot.turn_publisher.events[0].turn["turn_id"] == "client-2"


async def test_stream_disconnect_stores_partial_turn():
    bot = await _bot(lambda mem: RecordingPublisher(mem, "uuid-1"), mode="explode")
    async for _ in bot.ask_stream("q", user_id="u", session_id="s", use_vector_context=False, turn_id="st-1"):
        pass
    event = bot.turn_publisher.events[0]
    assert event.turn["turn_id"] == "st-1" and "partial" in event.turn["assistant_response"]
    assert "stream died" in (event.turn["error"] or "")


async def test_stream_caller_cancel_saves_partial_turn():
    bot = await _bot(lambda mem: RecordingPublisher(mem, "uuid-1"), mode="hang")
    stream = bot.ask_stream("q", user_id="u", session_id="s", use_vector_context=False)

    async def consume():
        async for _ in stream:
            pass

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.5)  # the first chunk was streamed; the client then hangs
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(bot.turn_publisher.events) == 1  # saved once, even though the caller left
    event = bot.turn_publisher.events[0]
    assert "partial" in event.turn["assistant_response"] and event.turn["error"]


def test_bots_package_never_imports_chat_storage():
    root = Path(bots_pkg.__file__).parent
    offenders = []
    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.ImportFrom):
                names = [(node.module or "") + "." + a.name for a in node.names]
            elif isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            if any("storage.chat" in n or n.endswith("storage.ChatStorage") for n in names):
                offenders.append(str(path))
    assert not offenders
