"""Unit tests for FEAT-525 bind-after-defaulting across BaseBot entry points.

A call without ``user_id``/``session_id`` must reach
``ConversationMemory.add_turn`` with ``current_user_id``/``current_session_id``/
``current_memory_key_id`` already equal to the (defaulted) ids and the bot's
``memory_key_id`` — never ``None`` (spec §7 "Binding-order hazard").
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

import pytest

from parrot.bots.base import BaseBot
from parrot.clients.base import AbstractClient
from parrot.memory import InMemoryConversation
from parrot.models import AIMessage
from parrot.models.responses import CompletionUsage
from parrot.observability.context import (
    current_memory_key_id,
    current_session_id,
    current_user_id,
)


class _StubClient(AbstractClient):
    """Offline stub client returning a canned reply, no network I/O."""

    client_type = "stub"
    supported_models = ["stub"]

    def __init__(self, reply: str = "ok", **kwargs: Any) -> None:
        kwargs.setdefault("model", "stub")
        super().__init__(**kwargs)
        self.reply = reply

    async def get_client(self) -> "_StubClient":
        return self

    async def _ensure_client(self) -> "_StubClient":
        return self

    async def ask(self, prompt: str, model: Optional[str] = None, **kwargs: Any) -> AIMessage:
        return AIMessage(
            input=prompt,
            output=self.reply,
            model="stub",
            provider="stub",
            usage=CompletionUsage(),
            turn_id=str(uuid.uuid4()),
        )

    async def ask_stream(self, prompt: str, **kwargs: Any):
        yield self.reply

    async def resume(self, session_id: str, user_input: str, state: Dict[str, Any]):
        raise NotImplementedError

    async def invoke(self, prompt: str, **kwargs: Any):
        raise NotImplementedError


class RecordingMemory(InMemoryConversation):
    """Captures the three ContextVars visible at `add_turn` time."""

    def __init__(self):
        super().__init__()
        self.seen: List[tuple] = []

    async def add_turn(self, user_id, session_id, turn, chatbot_id=None, **kw):
        self.seen.append(
            (
                user_id,
                session_id,
                current_user_id.get(),
                current_session_id.get(),
                current_memory_key_id.get(),
            )
        )
        await super().add_turn(user_id, session_id, turn, chatbot_id=chatbot_id, **kw)


@pytest.fixture
async def bot_with_recording_memory():
    """A configured ``BaseBot`` wired to a stub client + recording memory."""
    client = _StubClient()
    bot = BaseBot(
        name="bind-after-defaulting-probe",
        llm=client,
        memory_type="memory",
        injection_detection=False,
    )
    await bot.configure()
    mem = RecordingMemory()
    bot.conversation_memory = mem
    return bot, mem


@pytest.mark.parametrize("entry", ["conversation", "invoke", "ask", "ask_stream"])
@pytest.mark.asyncio
async def test_bind_after_defaulting(bot_with_recording_memory, entry):
    bot, mem = bot_with_recording_memory
    call = getattr(bot, entry)
    if entry == "ask_stream":
        async for _ in call("hello", use_vector_context=False):
            pass
    else:
        await call("hello", use_vector_context=False)

    assert len(mem.seen) == 1
    (user_id, session_id, cv_user, cv_session, cv_key), = mem.seen
    assert cv_user == user_id == "anonymous"
    assert cv_session == session_id
    assert cv_key == bot.memory_key_id
    assert current_user_id.get() is None
    assert current_session_id.get() is None
    assert current_memory_key_id.get() is None
