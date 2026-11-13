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


class _ToolClient(Client):
    def _msg(self, prompt: str) -> AIMessage:
        from parrot.models.basic import ToolCall

        msg = super()._msg(prompt)
        msg.tool_calls = [ToolCall(id="t1", name="lookup", arguments={"q": "x"}, result={"answer": 42},
                                   execution_time=0.1)]
        return msg


async def test_ask_publishes_the_finalized_response():
    """The presentation is built after sources / tool data / formatting are applied, not before."""
    bot = await _bot(lambda mem: RecordingPublisher(mem, "uuid-1"))
    bot.llm = _ToolClient()
    response = await _round(bot)
    assert response.data is not None  # ask() lifted the tool result into response.data after the save point
    event = bot.turn_publisher.events[0]
    assert event.presentation["data"] == response.data
    # the raw turn snapshot is unaffected by that post-processing
    assert event.turn["assistant_response"] == "reply"


async def test_history_flag_does_not_disable_durable_publication():
    """use_conversation_history=False controls only what reaches the LLM; the turn is still published."""
    bot = await _bot(lambda mem: RecordingPublisher(mem, "uuid-1"))
    response = await bot.ask("hi", user_id="u", session_id="s", use_vector_context=False,
                             use_conversation_history=False)
    assert [e.turn["turn_id"] for e in bot.turn_publisher.events] == [response.turn_id]
    assert bot.turn_publisher.events[0].turn["sequence"] >= 1
    assert await bot.conversation_memory.get_history("u", "s", chatbot_id="uuid-1") is None  # working memory untouched


async def test_stream_and_conversation_publish_with_history_disabled():
    bot = await _bot(lambda mem: RecordingPublisher(mem, "uuid-1"))
    async for _ in bot.ask_stream("q", user_id="u", session_id="s", use_vector_context=False,
                                  use_conversation_history=False):
        pass
    await bot.conversation("hi", user_id="u", session_id="s2", use_vector_context=False,
                           use_conversation_history=False)
    assert len(bot.turn_publisher.events) == 2



async def test_sequence_floor_failure_does_not_fail_the_round(caplog):
    """A durable-maximum lookup that fails must degrade to the local allocator, not lose the answer."""
    from parrot.memory import LocalSequenceAllocator
    from parrot.memory.hydration import HydrationSource, HydrationUnavailableError

    class _BrokenFloor(HydrationSource):
        async def load_turns(self, *a, **kw):
            return None

        async def is_deleted(self, *a, **kw):
            return False

        async def max_sequence(self, *a, **kw):
            raise HydrationUnavailableError("cold store down")

    bot = await _bot(lambda mem: RecordingPublisher(mem, "uuid-1"))
    bot.hydration_source = _BrokenFloor()
    bot.sequence_allocator = LocalSequenceAllocator()
    response = await _round(bot)
    assert response.output == "reply" or response.response == "reply"
    assert bot.turn_publisher.events[0].turn["sequence"] >= 1
    assert any("sequence allocation failed" in r.getMessage() for r in caplog.records)


async def test_naive_local_timestamp_keeps_its_instant():
    from datetime import datetime, timezone
    from parrot.memory import ConversationTurn

    bot = await _bot(lambda mem: RecordingPublisher(mem, "uuid-1"))
    naive = datetime.now()  # what the ConversationTurn default factory produces: local time
    turn = ConversationTurn(turn_id="t", user_id="u", user_message="q", assistant_response="a",
                            chatbot_id="uuid-1", timestamp=naive)
    await bot._stamp_turn_ordering("u", "s", turn)
    assert turn.timestamp.tzinfo is not None
    assert turn.timestamp == naive.astimezone(timezone.utc)


SECRET = "sk-1234abcdefghij"


class _SecretClient(Client):
    def _msg(self, prompt: str) -> AIMessage:
        msg = super()._msg(prompt)
        msg.output = msg.response = f"your key is API_KEY={SECRET}"
        return msg


async def _bot_with_secrets_guardrail(publisher_factory) -> BaseBot:
    from parrot.bots.guardrails.base import GuardrailStage
    from parrot.bots.guardrails.builtin.secrets import SecretsGuardrail

    bot = await _bot(publisher_factory)
    bot._guardrail_pipelines[GuardrailStage.OUTPUT].add(SecretsGuardrail())
    bot.llm = _SecretClient()
    return bot


async def test_transformed_output_is_what_working_memory_and_the_bus_keep():
    """A TRANSFORM verdict (redaction) must reach the stored turn and the published turn, never the raw text."""
    bot = await _bot_with_secrets_guardrail(lambda mem: RecordingPublisher(mem, "uuid-1"))
    response = await _round(bot)
    assert SECRET not in str(response.output)  # the caller got the redacted text
    event = bot.turn_publisher.events[0]
    assert SECRET not in event.turn["assistant_response"] and "REDACTED" in event.turn["assistant_response"]
    stored = (await bot.conversation_memory.get_history("u", "s", chatbot_id="uuid-1")).turns[0]
    assert SECRET not in stored.assistant_response  # working memory does not retain the raw text either
    assert event.presentation["output"] == response.response or SECRET not in str(event.presentation["output"])


async def test_failure_before_the_save_leaves_neither_memory_nor_bus_with_the_turn():
    bot = await _bot(lambda mem: RecordingPublisher(mem, "uuid-1"))

    async def explode(response, method):
        raise RuntimeError("pipeline blew up")

    bot._run_output_pipeline = explode
    with pytest.raises(RuntimeError):
        await _round(bot)
    assert bot.turn_publisher.events == []
    assert await bot.conversation_memory.get_history("u", "s", chatbot_id="uuid-1") in (None,) or \
        (await bot.conversation_memory.get_history("u", "s", chatbot_id="uuid-1")).turns == []


async def test_cancellation_before_the_save_leaves_neither_memory_nor_bus_with_the_turn():
    bot = await _bot(lambda mem: RecordingPublisher(mem, "uuid-1"))

    async def hang(response, method):
        await asyncio.sleep(30)

    bot._run_output_pipeline = hang
    task = asyncio.create_task(_round(bot))
    await asyncio.sleep(0.3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert bot.turn_publisher.events == []
    history = await bot.conversation_memory.get_history("u", "s", chatbot_id="uuid-1")
    assert history is None or history.turns == []


async def test_failure_after_the_save_still_leaves_memory_and_bus_equal():
    """The save and the publication are ONE unit: a later failure (suggestions) cannot split them."""
    bot = await _bot(lambda mem: RecordingPublisher(mem, "uuid-1"))

    async def explode(question, response, **kw):
        raise RuntimeError("suggestions LLM down")

    bot._attach_suggestions = explode
    with pytest.raises(RuntimeError):
        await _round(bot)
    history = await bot.conversation_memory.get_history("u", "s", chatbot_id="uuid-1")
    assert [t.turn_id for t in history.turns] == [e.turn["turn_id"] for e in bot.turn_publisher.events]
    assert len(bot.turn_publisher.events) == 1
