"""FEAT-886 M1 — ask_stream commits compaction state like ask() does."""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from parrot.bots.base import BaseBot
from parrot.clients.base import AbstractClient
from parrot.memory import InMemoryConversation
from parrot.memory.compaction.models import ContextBudget
from parrot.models import AIMessage
from parrot.models.responses import CompletionUsage


class _Client(AbstractClient):
    """Offline stub; ``explode`` makes the stream die after one chunk."""

    client_type = "recording"
    supported_models = ["stub"]

    def __init__(self, explode: bool = False, **kwargs: Any) -> None:
        kwargs.setdefault("model", "stub")
        super().__init__(**kwargs)
        self.calls: List[Dict[str, Any]] = []
        self.explode = explode

    async def get_client(self) -> "_Client":
        return self

    async def _ensure_client(self) -> "_Client":
        return self

    def _response(self, prompt: str) -> AIMessage:
        return AIMessage(
            input=prompt, output="reply", model="stub", provider="stub",
            usage=CompletionUsage(), turn_id=str(uuid.uuid4()),
        )

    async def ask(self, prompt: str, model: Optional[str] = None, **kwargs: Any) -> AIMessage:
        self.calls.append({"method": "ask", **kwargs})
        return self._response(prompt)

    async def ask_stream(self, prompt: str, **kwargs: Any):
        self.calls.append({"method": "ask_stream", **kwargs})
        yield "partial text "
        if self.explode:
            raise RuntimeError("stream died")
        yield self._response(prompt)

    async def resume(self, session_id: str, user_input: str, state: Dict[str, Any]):
        raise NotImplementedError

    async def invoke(self, prompt: str, **kwargs: Any):
        raise NotImplementedError


async def _make_bot(explode: bool = False) -> BaseBot:
    bot = BaseBot(
        name="stream-commit-probe",
        llm=_Client(explode=explode),
        memory_type="memory",
        injection_detection=False,
        context_budget=ContextBudget(window=50_000),
    )
    await bot.configure()
    bot.conversation_memory = InMemoryConversation()
    return bot


async def _stream(bot: BaseBot) -> None:
    async for _ in bot.ask_stream("q", user_id="u", session_id="s", use_vector_context=False):
        pass


async def test_ask_stream_commits_compaction():
    """A completed streamed round writes metadata['compaction'] (boundary + calibration)."""
    bot = await _make_bot()
    await _stream(bot)
    history = await bot.conversation_memory.get_history("u", "s", chatbot_id=bot.memory_key_id)
    assert history is not None
    assert "compaction" in history.metadata
    assert "boundary_turn_id" in history.metadata["compaction"]


async def test_ask_stream_partial_save_does_not_commit():
    """A stream that raised keeps compaction=None (spec M1 (b))."""
    bot = await _make_bot(explode=True)
    await _stream(bot)
    history = await bot.conversation_memory.get_history("u", "s", chatbot_id=bot.memory_key_id)
    assert history is not None and len(history.turns) == 1
    assert "partial text" in history.turns[0].assistant_response
    assert history.metadata.get("compaction") is None
