"""Behavioral acceptance tests for single persistent-memory invocation lifecycles."""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator

import pytest

from parrot.bots.base import BaseBot
from parrot.bots.data import PandasAgent
from parrot.clients.base import AbstractClient
from parrot.memory import InMemoryConversation
from parrot.memory.agent_memory.models import MemoryEvent, MemoryRequestScope
from parrot.memory.unified.models import MemoryContext
from parrot.models import AIMessage, CompletionUsage


class _Client(AbstractClient):
    """Offline client double that exercises the real public bot paths."""

    client_type = "memory-lifecycle"
    supported_models = ["stub"]

    def __init__(self, mode: str = "ok") -> None:
        """Initialize a deterministic client mode."""
        super().__init__(model="stub")
        self.mode = mode

    async def get_client(self) -> "_Client":
        """Return the configured client."""
        return self

    async def _ensure_client(self) -> "_Client":
        """Satisfy the abstract client lifecycle."""
        return self

    def _message(self, prompt: str) -> AIMessage:
        """Build one stable answer envelope."""
        return AIMessage(
            input=prompt,
            output="reply",
            response="reply",
            model="stub",
            provider="memory-lifecycle",
            usage=CompletionUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        )

    async def ask(self, prompt: str, **kwargs: Any) -> AIMessage:
        """Return one deterministic answer."""
        return self._message(prompt)

    async def ask_stream(self, prompt: str, **kwargs: Any) -> AsyncIterator[str | AIMessage]:
        """Yield a partial answer and optionally simulate an incomplete stream."""
        yield "partial "
        if self.mode == "error":
            raise RuntimeError("stream failed")
        if self.mode == "hang":
            await asyncio.sleep(30)
        yield self._message(prompt)

    async def invoke(self, *args: Any, **kwargs: Any) -> AIMessage:
        """Satisfy the abstract client contract."""
        raise NotImplementedError

    async def resume(self, *args: Any, **kwargs: Any) -> AIMessage:
        """Satisfy the abstract client contract."""
        raise NotImplementedError


class _MemoryRecorder:
    """Observe lifecycle calls without replacing the real bot invocation code."""

    def __init__(self) -> None:
        """Initialize observable memory state."""
        self.scopes: list[MemoryRequestScope] = []
        self.events: list[MemoryEvent] = []

    async def prepare(self, query: str, *, scope: MemoryRequestScope) -> MemoryContext:
        """Record one scope and return a prompt-visible memory section."""
        self.scopes.append(scope)
        return MemoryContext(semantic_knowledge="remembered")

    async def complete(self, event: MemoryEvent) -> None:
        """Record one completed response event."""
        self.events.append(event)


async def _bot(mode: str = "ok") -> tuple[BaseBot, _MemoryRecorder]:
    """Construct a real BaseBot with an isolated history store and recorder."""
    bot = BaseBot(
        name="memory-agent",
        chatbot_id="memory-key",
        llm=_Client(mode),
        memory_type="memory",
        injection_detection=False,
    )
    await bot.configure()
    bot.conversation_memory = InMemoryConversation()
    recorder = _MemoryRecorder()
    bot.prepare_memory = recorder.prepare  # type: ignore[attr-defined]
    bot.complete_memory = recorder.complete  # type: ignore[attr-defined]
    return bot, recorder


@pytest.mark.asyncio
async def test_ask_stream_invoke_single_owner() -> None:
    """Verify each public BaseBot entry point prepares and finalizes exactly once."""
    bot, recorder = await _bot()

    await bot.ask("ask", user_id="u", session_id="s", use_vector_context=False)
    await bot.invoke("invoke", user_id="u", session_id="s")
    async for _chunk in bot.ask_stream("stream", user_id="u", session_id="s", use_vector_context=False):
        pass

    assert [scope.agent_id for scope in recorder.scopes] == ["memory-agent"] * 3
    assert [event.payload["response"] for event in recorder.events] == ["reply", "reply", "partial "]
    assert len(recorder.events) == len(recorder.scopes) == 3


@pytest.mark.asyncio
async def test_cancelled_stream_preserves_history_only() -> None:
    """Verify a cancelled stream persists its partial history but earns no response event."""
    bot, recorder = await _bot("hang")

    async def consume() -> None:
        """Consume the stream until the client blocks."""
        async for _chunk in bot.ask_stream("cancel", user_id="u", session_id="s", use_vector_context=False):
            pass

    task = asyncio.create_task(consume())
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    history = await bot.conversation_memory.get_history("u", "s", chatbot_id=bot.memory_key_id)
    assert history is not None and history.turns[0].error
    assert recorder.events == []


@pytest.mark.asyncio
async def test_direct_conversation_boundary_and_generic_hooks() -> None:
    """Verify direct conversation stays outside the new lifecycle and ask retains generic hooks."""
    bot, recorder = await _bot()
    calls: list[str] = []

    async def pre(*args: Any, **kwargs: Any) -> str:
        """Record generic pre-hook execution."""
        calls.append("pre")
        return ""

    async def post(*args: Any, **kwargs: Any) -> None:
        """Record generic post-hook execution."""
        calls.append("post")

    bot._on_pre_ask = pre  # type: ignore[method-assign]
    bot._on_post_ask = post  # type: ignore[method-assign]
    await bot.conversation("legacy", user_id="u", session_id="s", use_vector_context=False)
    assert recorder.events == [] and recorder.scopes == []

    await bot.ask("modern", user_id="u", session_id="s", use_vector_context=False)
    await asyncio.sleep(0)
    assert calls == ["pre", "post"]
    assert len(recorder.events) == 1


@pytest.mark.asyncio
async def test_pandas_agent_single_lifecycle() -> None:
    """Verify PandasAgent.ask owns one lifecycle and invoke delegates without duplication."""
    agent = PandasAgent(name="pandas-memory", llm="google:gemini-2.5-flash", injection_detection=False)
    agent._llm = _Client()
    agent.conversation_memory = InMemoryConversation()
    recorder = _MemoryRecorder()
    agent.prepare_memory = recorder.prepare  # type: ignore[method-assign]
    agent.complete_memory = recorder.complete  # type: ignore[method-assign]

    await agent.ask("ask", user_id="u", session_id="s", return_structured=False)
    await agent.invoke("invoke", user_id="u", session_id="s")

    assert len(recorder.scopes) == len(recorder.events) == 2
    assert [event.payload["response"] for event in recorder.events] == ["reply", "reply"]


@pytest.mark.asyncio
async def test_event_identity_and_partial_turns() -> None:
    """Verify retry-stable event IDs and error streams never emit successful memory events."""
    bot, recorder = await _bot()
    await bot.ask("retry", user_id="u", session_id="s", use_vector_context=False, turn_id="client-turn")
    await bot.ask("retry", user_id="u", session_id="s", use_vector_context=False, turn_id="client-turn")
    assert [event.event_id for event in recorder.events] == [recorder.events[0].event_id] * 2

    failing_bot, failing_recorder = await _bot("error")
    async for _chunk in failing_bot.ask_stream("error", user_id="u", session_id="s", use_vector_context=False):
        pass
    history = await failing_bot.conversation_memory.get_history("u", "s", chatbot_id=failing_bot.memory_key_id)
    assert history is not None and history.turns[0].error == "stream failed"
    assert failing_recorder.events == []
