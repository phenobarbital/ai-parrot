"""FEAT-886 M15 — AbstractBot._load_or_hydrate_history paths (real InMemoryConversation)."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pytest

from parrot.bots.base import BaseBot
from parrot.clients.base import AbstractClient
from parrot.memory import ConversationTurn, InMemoryConversation
from parrot.memory.hydration import (
    HydrationNotReadyError,
    HydrationSource,
    HydrationUnavailableError,
    SessionDeletedError,
)
from parrot.models import AIMessage
from parrot.models.responses import CompletionUsage

T0 = datetime(2026, 11, 1, 10, tzinfo=timezone.utc)


class RecordingClient(AbstractClient):
    client_type = "recording"
    supported_models = ["stub"]

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("model", "stub")
        super().__init__(**kwargs)
        self.calls: List[Dict[str, Any]] = []

    async def get_client(self) -> "RecordingClient":
        return self

    async def _ensure_client(self) -> "RecordingClient":
        return self

    async def ask(self, prompt: str, model: Optional[str] = None, **kwargs: Any) -> AIMessage:
        self.calls.append({"prompt": prompt, **kwargs})
        return AIMessage(input=prompt, output="reply", model="stub", provider="stub", usage=CompletionUsage(),
                         turn_id=str(uuid.uuid4()))

    async def ask_stream(self, prompt: str, **kwargs: Any):
        yield "x"

    async def resume(self, *a: Any, **kw: Any):
        raise NotImplementedError

    async def invoke(self, *a: Any, **kw: Any):
        raise NotImplementedError


class ScriptedSource(HydrationSource):
    """Real HydrationSource subclass; outcomes scripted per test, every call recorded."""

    def __init__(self, turns=None, load_exc=None, deleted=(False,), guard_exc=None):
        self.turns, self.load_exc, self.guard_exc = turns, load_exc, guard_exc
        self._deleted = list(deleted)
        self.calls: list = []

    async def load_turns(self, agent_name, user_id, session_id, max_turns):
        self.calls.append(("load_turns", agent_name, max_turns))
        if self.load_exc:
            raise self.load_exc
        return self.turns

    async def is_deleted(self, agent_name, user_id, session_id):
        self.calls.append(("is_deleted", agent_name))
        if self.guard_exc:
            raise self.guard_exc
        return self._deleted.pop(0) if len(self._deleted) > 1 else self._deleted[0]

    async def max_sequence(self, agent_name, user_id, session_id):
        return 0


def _turn(tid: str, sec: int) -> ConversationTurn:
    return ConversationTurn(turn_id=tid, user_id="u", user_message=f"q{tid}", assistant_response=f"a{tid}",
                            timestamp=T0 + timedelta(seconds=sec), chatbot_id="uuid-1", sequence=sec)


async def _bot(source=None, **kw) -> BaseBot:
    bot = BaseBot(name="alpha", chatbot_id="uuid-1", llm=RecordingClient(), memory_type="memory",
                  injection_detection=False, hydration_source=source, **kw)
    await bot.configure()
    bot.conversation_memory = InMemoryConversation()
    return bot


async def test_no_source_is_todays_expression():
    bot = await _bot()
    history = await bot._load_or_hydrate_history(bot.conversation_memory, "u", "s")
    assert history.turns == []
    assert await bot.conversation_memory.get_history("u", "s", chatbot_id="uuid-1") is history


async def test_hit_does_not_consult_load_turns():
    source = ScriptedSource(turns=[_turn("x", 1)])
    bot = await _bot(source)
    await bot.conversation_memory.create_history("u", "s", chatbot_id="uuid-1")
    await bot._load_or_hydrate_history(bot.conversation_memory, "u", "s")
    assert [c[0] for c in source.calls] == ["is_deleted"]  # guard only, no window load


async def test_miss_installs_under_memory_key_while_source_is_keyed_by_name():
    source = ScriptedSource(turns=[_turn("a", 1), _turn("b", 2)])
    bot = await _bot(source)
    history = await bot._load_or_hydrate_history(bot.conversation_memory, "u", "s")
    assert [t.turn_id for t in history.turns] == ["a", "b"]
    assert history.chatbot_id == "uuid-1"
    assert ("load_turns", "alpha", 30) in source.calls  # ChatStorage key = agent NAME, budget window
    assert await bot.conversation_memory.get_history("u", "s", chatbot_id="alpha") is None


async def test_active_session_without_turns_installs_empty_history():
    bot = await _bot(ScriptedSource(turns=None))
    history = await bot._load_or_hydrate_history(bot.conversation_memory, "u", "s")
    assert history.turns == [] and "hydration" not in history.metadata


async def test_deleted_session_raises_and_creates_nothing():
    bot = await _bot(ScriptedSource(deleted=(True,)))
    with pytest.raises(SessionDeletedError):
        await bot._load_or_hydrate_history(bot.conversation_memory, "u", "s")
    assert await bot.conversation_memory.get_history("u", "s", chatbot_id="uuid-1") is None


async def test_guard_unavailable_fails_closed():
    bot = await _bot(ScriptedSource(guard_exc=RuntimeError("redis down")))
    with pytest.raises(HydrationUnavailableError):
        await bot._load_or_hydrate_history(bot.conversation_memory, "u", "s")
    assert await bot.conversation_memory.get_history("u", "s", chatbot_id="uuid-1") is None


async def test_not_ready_creates_pending_history_then_merges_on_a_later_round():
    source = ScriptedSource(load_exc=HydrationNotReadyError("backfilling"))
    bot = await _bot(source)
    first = await bot._load_or_hydrate_history(bot.conversation_memory, "u", "s")
    assert first.metadata["hydration"]["state"] == "pending"
    await bot.conversation_memory.add_turn("u", "s", _turn("live", 50), chatbot_id="uuid-1")
    source.load_exc, source.turns = None, [_turn("old1", 1), _turn("old2", 2)]
    merged = await bot._load_or_hydrate_history(bot.conversation_memory, "u", "s")
    assert [t.turn_id for t in merged.turns] == ["old1", "old2", "live"]
    assert "hydration" not in merged.metadata


async def test_delete_during_hydration_install_removes_the_installed_history():
    bot = await _bot(ScriptedSource(turns=[_turn("a", 1)], deleted=(False, True)))
    with pytest.raises(SessionDeletedError):
        await bot._load_or_hydrate_history(bot.conversation_memory, "u", "s")
    assert await bot.conversation_memory.get_history("u", "s", chatbot_id="uuid-1") is None


async def test_a_round_through_ask_uses_hydrated_history():
    source = ScriptedSource(turns=[_turn("a", 1)])
    bot = await _bot(source)
    await bot.ask("next", user_id="u", session_id="s", use_vector_context=False)
    history_arg = bot.get_client().calls[-1]["history"]
    assert any("qa" in m.content for m in history_arg)
