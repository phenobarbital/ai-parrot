"""``AbstractBot`` conversation-history ownership (FEAT-524, TASK-2811).

Covers spec §4 M3 rows: the stable per-agent key identity (``memory_key_id``),
``save_conversation_turn`` as the single writer, the removal of the
system-prompt history digest, and the fact that the bot no longer injects its
conversation memory into the LLM client.
"""

from __future__ import annotations

from typing import Any

import pytest

from parrot.bots.abstract import AbstractBot
from parrot.memory import ConversationTurn, InMemoryConversation


class _Bot(AbstractBot):
    """Minimal concrete ``AbstractBot`` — the four abstract entry points stubbed."""

    async def ask(self, *args: Any, **kwargs: Any):  # pragma: no cover - never called
        raise NotImplementedError

    async def ask_stream(self, *args: Any, **kwargs: Any):  # pragma: no cover
        raise NotImplementedError

    async def conversation(self, *args: Any, **kwargs: Any):  # pragma: no cover
        raise NotImplementedError

    async def invoke(self, *args: Any, **kwargs: Any):  # pragma: no cover
        raise NotImplementedError


def _bot(**kwargs: Any) -> _Bot:
    """Construct the stub bot with prompt-injection detection off (slow model load)."""
    kwargs.setdefault("injection_detection", False)
    return _Bot(**kwargs)


# ---------------------------------------------------------------------------
# memory_key_id
# ---------------------------------------------------------------------------


def test_memory_key_id_uses_explicit_chatbot_id():
    """An id the caller chose is stable, so it is used as the key segment."""
    assert _bot(name="x", chatbot_id="abc").memory_key_id == "abc"


def test_memory_key_id_falls_back_to_name():
    """With no explicit id the key is the bot's name, never the random uuid."""
    bot = _bot(name="x")

    assert bot.memory_key_id == "x"
    # The auto-generated id still exists, it is simply not used as a key.
    assert bot.chatbot_id != "x"


def test_memory_key_id_explicit_none_falls_back_to_name():
    """``chatbot_id=None`` is 'not configured', not 'configured as None'."""
    assert _bot(name="x", chatbot_id=None).memory_key_id == "x"


def test_memory_key_id_stable_across_restarts():
    """Two instances of the same unnamed-id bot resolve to the same key.

    This is the whole point of the ``self.name`` fallback: keying by the
    ``uuid4().hex`` default would hand every restart a brand-new history.
    """
    first, second = _bot(name="x"), _bot(name="x")

    assert first.chatbot_id != second.chatbot_id  # random default differs
    assert first.memory_key_id == second.memory_key_id == "x"


def test_memory_key_id_is_a_string():
    """Non-string explicit ids are normalised — storage keys are strings."""
    import uuid

    identifier = uuid.uuid4()
    bot = _bot(name="x", chatbot_id=identifier)

    assert bot.memory_key_id == str(identifier)
    assert isinstance(bot.memory_key_id, str)


def test_two_agents_same_session_are_isolated():
    """Different agents produce different key segments for the same session."""
    assert _bot(name="a").memory_key_id != _bot(name="b").memory_key_id


# ---------------------------------------------------------------------------
# save_conversation_turn — the single writer
# ---------------------------------------------------------------------------


@pytest.fixture
def bot_with_memory() -> _Bot:
    """A stub bot wired to a fresh ``InMemoryConversation``."""
    bot = _bot(name="x")
    bot.conversation_memory = InMemoryConversation()
    return bot


def _turn(turn_id: str, chatbot_id: str | None) -> ConversationTurn:
    """A turn attributed to ``chatbot_id``."""
    return ConversationTurn(turn_id, "u", "q", "a", chatbot_id=chatbot_id)


async def test_save_conversation_turn_keys_by_memory_key_id(bot_with_memory: _Bot):
    """The turn lands under ``[user][memory_key_id][session]``."""
    memory = bot_with_memory.conversation_memory
    await memory.create_history("u", "s", chatbot_id="x")

    await bot_with_memory.save_conversation_turn("u", "s", _turn("t1", "x"))

    history = await memory.get_history("u", "s", chatbot_id="x")
    assert len(history.turns) == 1
    assert history.turns[0].chatbot_id == "x"


async def test_save_conversation_turn_rejects_mismatched_attribution(bot_with_memory: _Bot):
    """A turn attributed to another agent must not be written here."""
    await bot_with_memory.conversation_memory.create_history("u", "s", chatbot_id="x")

    with pytest.raises(ValueError, match="does not match"):
        await bot_with_memory.save_conversation_turn("u", "s", _turn("t2", "other"))


async def test_save_conversation_turn_rejects_unattributed_turn(bot_with_memory: _Bot):
    """``chatbot_id=None`` is also a mismatch — the bot always attributes."""
    with pytest.raises(ValueError):
        await bot_with_memory.save_conversation_turn("u", "s", _turn("t3", None))


async def test_save_conversation_turn_takes_no_chatbot_id_argument():
    """The ``chatbot_id`` parameter is gone: no caller may choose the key.

    FEAT-525 adds a keyword-only ``compaction`` parameter (the bot's
    ``CompactionCommit`` for the round) — an authorized extension of this
    same signature, not a reintroduction of caller-chosen attribution.
    """
    import inspect

    parameters = inspect.signature(AbstractBot.save_conversation_turn).parameters

    assert "chatbot_id" not in parameters
    assert list(parameters) == ["self", "user_id", "session_id", "turn", "compaction"]
    assert parameters["compaction"].kind is inspect.Parameter.KEYWORD_ONLY
    assert parameters["compaction"].default is None


async def test_save_conversation_turn_without_memory_is_a_noop():
    """No configured memory ⇒ silently do nothing (unchanged behaviour)."""
    bot = _bot(name="x")
    bot.conversation_memory = None

    await bot.save_conversation_turn("u", "s", _turn("t1", "x"))


async def test_save_conversation_turn_emits_event_once(bot_with_memory: _Bot):
    """FEAT-176's ``MessageAddedEvent`` fires exactly once per persisted turn."""
    from parrot.core.events.lifecycle.events import MessageAddedEvent

    seen: list[Any] = []

    async def _listener(event):
        seen.append(event)

    bot_with_memory.events.subscribe(MessageAddedEvent, _listener)
    await bot_with_memory.conversation_memory.create_history("u", "s", chatbot_id="x")

    await bot_with_memory.save_conversation_turn("u", "s", _turn("t1", "x"))

    assert len(seen) == 1
    assert seen[0].content_length == len("q") + len("a")


async def test_save_conversation_turn_emits_no_event_on_rejection(bot_with_memory: _Bot):
    """A rejected turn must not emit an event — nothing was persisted."""
    from parrot.core.events.lifecycle.events import MessageAddedEvent

    seen: list[Any] = []

    async def _listener(event):
        seen.append(event)

    bot_with_memory.events.subscribe(MessageAddedEvent, _listener)

    with pytest.raises(ValueError):
        await bot_with_memory.save_conversation_turn("u", "s", _turn("t1", "nope"))

    assert seen == []


# ---------------------------------------------------------------------------
# read helpers key by memory_key_id
# ---------------------------------------------------------------------------


class _RecordingMemory(InMemoryConversation):
    """In-memory backend that records the ``chatbot_id`` of every call."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[str, Any]] = []

    async def get_history(self, user_id, session_id, chatbot_id=None):
        self.calls.append(("get_history", chatbot_id))
        return await super().get_history(user_id, session_id, chatbot_id)

    async def create_history(self, user_id, session_id, metadata=None, chatbot_id=None):
        self.calls.append(("create_history", chatbot_id))
        return await super().create_history(user_id, session_id, metadata, chatbot_id)

    async def clear_history(self, user_id, session_id, chatbot_id=None):
        self.calls.append(("clear_history", chatbot_id))
        return await super().clear_history(user_id, session_id, chatbot_id)

    async def delete_history(self, user_id, session_id, chatbot_id=None):
        self.calls.append(("delete_history", chatbot_id))
        return await super().delete_history(user_id, session_id, chatbot_id)


async def test_read_helpers_pass_memory_key_id():
    """Every read/clear/delete helper keys by ``memory_key_id`` by default."""
    bot = _bot(name="x")
    memory = _RecordingMemory()
    bot.conversation_memory = memory

    await bot.create_conversation_history("u", "s")
    await bot.get_conversation_history("u", "s")
    await bot.clear_conversation_history("u", "s")
    await bot.delete_conversation_history("u", "s")

    assert {call for call, _ in memory.calls} == {
        "create_history",
        "get_history",
        "clear_history",
        "delete_history",
    }
    assert all(chatbot_id == "x" for _, chatbot_id in memory.calls), memory.calls


async def test_read_helpers_honour_explicit_override():
    """An explicitly passed ``chatbot_id`` still wins (cross-agent reads)."""
    bot = _bot(name="x")
    memory = _RecordingMemory()
    bot.conversation_memory = memory

    await bot.get_conversation_history("u", "s", chatbot_id="other")

    assert memory.calls == [("get_history", "other")]


# ---------------------------------------------------------------------------
# system-prompt digest removal + memory-less client construction
# ---------------------------------------------------------------------------


def test_build_conversation_context_is_gone():
    """The history digest builder no longer exists."""
    assert not hasattr(AbstractBot, "build_conversation_context")


def test_create_system_prompt_has_no_conversation_context_kwarg():
    """The digest cannot even be passed in any more."""
    import inspect

    assert "conversation_context" not in inspect.signature(AbstractBot.create_system_prompt).parameters
    assert "conversation_context" not in inspect.signature(AbstractBot._build_prompt).parameters


async def test_system_prompt_contains_no_conversation_context_section():
    """No prompt the bot produces carries a ``## Conversation Context`` block."""
    bot = _bot(name="x")

    system_prompt = await bot.create_system_prompt(user_context="hello")

    rendered = system_prompt if isinstance(system_prompt, str) else str(system_prompt)
    assert "## Conversation Context" not in rendered


def test_create_llm_client_takes_no_conversation_memory():
    """Clients are memory-less: the bot cannot inject a store into them."""
    import inspect

    parameters = inspect.signature(AbstractBot._create_llm_client).parameters

    assert "conversation_memory" not in parameters
    assert list(parameters) == ["self", "config"]


def test_create_llm_client_does_not_inject_memory():
    """A pre-built client instance comes back without a memory assigned."""
    from parrot.bots.abstract import LLMConfig

    class _Client:
        tool_manager = None
        enable_redaction = False

    bot = _bot(name="x")
    bot.conversation_memory = InMemoryConversation()
    instance = _Client()

    returned = bot._create_llm_client(LLMConfig(provider="stub", client_instance=instance))

    assert returned is instance
    assert not hasattr(returned, "conversation_memory")
