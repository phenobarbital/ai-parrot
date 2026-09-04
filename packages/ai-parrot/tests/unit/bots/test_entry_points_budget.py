"""Unit tests for FEAT-525 bot entry points switched to render_context_history."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from parrot.bots.base import BaseBot
from parrot.bots.chatbot import Chatbot
from parrot.clients.base import AbstractClient
from parrot.memory import InMemoryConversation, render_history
from parrot.memory.abstract import ConversationTurn
from parrot.memory.compaction.models import CompactionCommit
from parrot.models import AIMessage
from parrot.models.responses import CompletionUsage


class _RecordingClient(AbstractClient):
    """Offline stub client recording the ``history=``/``system_prompt=`` per call."""

    client_type = "stub"
    supported_models = ["stub"]

    def __init__(self, reply: str = "ok", **kwargs: Any) -> None:
        kwargs.setdefault("model", "stub")
        super().__init__(**kwargs)
        self.reply = reply
        self.calls: List[Dict[str, Any]] = []

    async def get_client(self) -> "_RecordingClient":
        return self

    async def _ensure_client(self) -> "_RecordingClient":
        return self

    async def ask(self, prompt: str, model: Optional[str] = None, **kwargs: Any) -> AIMessage:
        self.calls.append({"prompt": prompt, "history": list(kwargs.get("history") or ()), "system_prompt": kwargs.get("system_prompt")})
        return AIMessage(
            input=prompt,
            output=self.reply,
            model="stub",
            provider="stub",
            usage=CompletionUsage(input_tokens=10, output_tokens=2),
            turn_id=str(uuid.uuid4()),
        )

    async def ask_stream(self, prompt: str, **kwargs: Any):
        self.calls.append({"prompt": prompt, "history": list(kwargs.get("history") or ()), "system_prompt": kwargs.get("system_prompt")})
        yield self.reply

    async def resume(self, session_id: str, user_input: str, state: Dict[str, Any]):
        raise NotImplementedError

    async def invoke(self, prompt: str, **kwargs: Any):
        raise NotImplementedError


class _FailingStreamClient(_RecordingClient):
    """Yields partial text then raises mid-stream."""

    async def ask_stream(self, prompt: str, **kwargs: Any):
        self.calls.append({"prompt": prompt, "history": list(kwargs.get("history") or ()), "system_prompt": kwargs.get("system_prompt")})
        yield "par"
        yield "tial"
        raise RuntimeError("stream died")


class _SpyMemory(InMemoryConversation):
    """Records every `add_turn` call's kwargs, then delegates to the real template method."""

    def __init__(self) -> None:
        super().__init__()
        self.add_turn_calls: List[Dict[str, Any]] = []

    async def add_turn(self, user_id, session_id, turn, chatbot_id=None, *, compaction=None):
        self.add_turn_calls.append(
            {"user_id": user_id, "session_id": session_id, "turn": turn, "chatbot_id": chatbot_id, "compaction": compaction}
        )
        await super().add_turn(user_id, session_id, turn, chatbot_id=chatbot_id, compaction=compaction)


async def _make_bot(*, client=None, memory=None, **bot_kwargs):
    client = client or _RecordingClient()
    mem = memory if memory is not None else InMemoryConversation()
    bot = BaseBot(
        name=bot_kwargs.pop("name", "entry-points-probe"),
        llm=client,
        memory_type="memory",
        injection_detection=False,
        **bot_kwargs,
    )
    # A real `configure()` pass sets up self._llm (required for
    # ask/ask_stream/invoke/conversation to actually call the client) —
    # then swap in the test's own memory and re-register the recovery tool
    # against it.
    await bot.configure()
    bot.conversation_memory = mem
    bot._register_recovery_tool()
    return bot, client, mem


async def _seeded_history(mem, chatbot_id, user_id, session_id, *, turns=5):
    await mem.create_history(user_id, session_id, chatbot_id=chatbot_id)
    for i in range(turns):
        turn = ConversationTurn(
            turn_id=f"seed-{i}", user_id=user_id, user_message=f"q{i}", assistant_response=f"a{i}", chatbot_id=chatbot_id
        )
        await mem.add_turn(user_id, session_id, turn, chatbot_id=chatbot_id)


async def _run_entry(bot: BaseBot, entry: str, question: str, *, user_id: str, session_id: str):
    method = getattr(bot, entry)
    if entry == "ask_stream":
        async for _ in method(question, user_id=user_id, session_id=session_id, use_vector_context=False):
            pass
    else:
        await method(question, user_id=user_id, session_id=session_id, use_vector_context=False)


@pytest.mark.parametrize("entry", ["conversation", "invoke", "ask", "ask_stream"])
@pytest.mark.parametrize("mode", ["kwarg_false", "env", "default_text_only"])
async def test_kill_switch_byte_equality(entry, mode, monkeypatch):
    kwargs = {"context_budget": False} if mode == "kwarg_false" else {}
    if mode == "env":
        monkeypatch.setenv("PARROT_COMPACTION_DISABLED", "1")
    bot, client, mem = await _make_bot(**kwargs)
    await _seeded_history(mem, bot.memory_key_id, "u", "s", turns=5)

    # Snapshot BEFORE the round: the round's own save mutates the same
    # history object the client already saw when it was called.
    history_before = await mem.get_history("u", "s", chatbot_id=bot.memory_key_id)
    expected = render_history(history_before, max_turns=30, current_chatbot_id=bot.memory_key_id)

    await _run_entry(bot, entry, "hello", user_id="u", session_id="s")

    assert client.calls[-1]["history"] == expected


@pytest.mark.parametrize("entry", ["conversation", "invoke", "ask"])
async def test_commit_reaches_add_turn(entry):
    """conversation/invoke/ask build a CompactionCommit for the single writer.

    ask_stream is excluded here by design (spec §7 "ask_stream partial
    save on error"): its one save site always passes `compaction=None`
    (no rendered-prompt estimate to pair, whether the round completed or
    errored) — covered separately by `test_ask_stream_partial_save_no_commit`.
    """
    mem = _SpyMemory()
    bot, client, mem = await _make_bot(memory=mem)
    await _seeded_history(mem, bot.memory_key_id, "u", "s", turns=3)

    await _run_entry(bot, entry, "hello", user_id="u", session_id="s")

    calls = [c for c in mem.add_turn_calls if c["compaction"] is not None]
    assert len(calls) == 1
    commit = calls[0]["compaction"]
    assert isinstance(commit, CompactionCommit)
    assert commit.prompt_estimate > 0


async def test_ask_stream_partial_save_no_commit():
    """A stream error is caught internally (fallback AIMessage) — assert on the persisted turn, not a raised exception."""
    mem = _SpyMemory()
    bot, client, mem = await _make_bot(memory=mem, client=_FailingStreamClient())

    async for _ in bot.ask_stream("q", user_id="u", session_id="s"):
        pass

    (call,) = mem.add_turn_calls
    assert call["compaction"] is None
    assert call["turn"].assistant_response == "partial"


def test_max_context_turns_ceiling_override():
    """Chatbot._from_db("max_context_turns", default=None): DB value overrides; absent -> 30 ceiling."""
    with_override = Chatbot(
        name="ceiling-probe-with-db-value", llm=_RecordingClient(), from_database=False, injection_detection=False
    )
    fake_bot_record = SimpleNamespace(max_context_turns=12)
    with_override.max_context_turns = with_override._from_db(fake_bot_record, "max_context_turns", default=None)
    assert with_override.max_context_turns == 12
    assert with_override.context_budget.max_turns == 12

    without_override = Chatbot(
        name="ceiling-probe-no-db-value", llm=_RecordingClient(), from_database=False, injection_detection=False
    )
    fake_bot_record_absent = SimpleNamespace(max_context_turns=None)
    without_override.max_context_turns = without_override._from_db(
        fake_bot_record_absent, "max_context_turns", default=None
    )
    assert without_override.max_context_turns is None
    assert without_override.context_budget.max_turns == 30
