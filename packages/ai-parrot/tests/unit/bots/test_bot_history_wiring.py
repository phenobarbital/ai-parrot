"""Bot-side history wiring (FEAT-524, TASK-2816).

Spec §4 M6 rows. These tests assert the closed loop: every ``BaseBot`` entry
point reads history under the ``(memory_key_id, user, session)`` key, renders it
with :func:`~parrot.memory.render_history`, hands it to the client as
``history=`` (and no ids), and persists exactly one turn through
``AbstractBot.save_conversation_turn``.
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

import pytest

from parrot.bots.base import BaseBot
from parrot.clients.base import AbstractClient
from parrot.memory import ConversationTurn, InMemoryConversation
from parrot.models import AIMessage
from parrot.models.responses import CompletionUsage


class RecordingClient(AbstractClient):
    """Offline stub that records every kwarg each call received."""

    client_type = "recording"
    supported_models = ["stub"]

    def __init__(self, reply: str = "canned-reply", **kwargs: Any) -> None:
        kwargs.setdefault("model", "stub")
        super().__init__(**kwargs)
        self.calls: List[Dict[str, Any]] = []
        self.reply = reply

    async def get_client(self) -> "RecordingClient":
        return self

    async def _ensure_client(self) -> "RecordingClient":
        return self

    def _response(self, prompt: str) -> AIMessage:
        return AIMessage(
            input=prompt,
            output=self.reply,
            model="stub",
            provider="stub",
            usage=CompletionUsage(),
            turn_id=str(uuid.uuid4()),
        )

    async def ask(self, prompt: str, model: Optional[str] = None, **kwargs: Any) -> AIMessage:
        self.calls.append({"method": "ask", "prompt": prompt, **kwargs})
        return self._response(prompt)

    async def ask_stream(self, prompt: str, **kwargs: Any):
        self.calls.append({"method": "ask_stream", "prompt": prompt, **kwargs})
        yield self.reply
        yield self._response(prompt)

    async def resume(self, session_id: str, user_input: str, state: Dict[str, Any]):
        raise NotImplementedError

    async def invoke(self, prompt: str, **kwargs: Any):
        raise NotImplementedError


class RecordingMemory(InMemoryConversation):
    """In-memory store that records the ``chatbot_id`` of every keyed call."""

    def __init__(self) -> None:
        super().__init__()
        self.keys: List[tuple[str, Any]] = []

    async def get_history(self, user_id, session_id, chatbot_id=None):
        self.keys.append(("get_history", chatbot_id))
        return await super().get_history(user_id, session_id, chatbot_id)

    async def create_history(self, user_id, session_id, metadata=None, chatbot_id=None):
        self.keys.append(("create_history", chatbot_id))
        return await super().create_history(user_id, session_id, metadata, chatbot_id)

    async def add_turn(self, user_id, session_id, turn, chatbot_id=None):
        self.keys.append(("add_turn", chatbot_id))
        return await super().add_turn(user_id, session_id, turn, chatbot_id)


async def _make_bot(**bot_kwargs: Any) -> BaseBot:
    """A configured ``BaseBot`` with a recording client and recording memory."""
    client = RecordingClient()
    bot = BaseBot(
        name="wiring-probe",
        llm=client,
        memory_type="memory",
        injection_detection=False,
        **bot_kwargs,
    )
    await bot.configure()
    bot.conversation_memory = RecordingMemory()
    return bot


@pytest.fixture
async def bot() -> BaseBot:
    return await _make_bot()


# ---------------------------------------------------------------------------
# llm_kwargs carry history, not ids
# ---------------------------------------------------------------------------


async def test_ask_passes_history_and_no_ids(bot: BaseBot):
    """``ask`` sends ``history=`` and neither ``user_id`` nor ``session_id``."""
    await bot.ask("q", user_id="u", session_id="s", use_vector_context=False)

    call = bot.get_client().calls[-1]
    assert "history" in call
    assert "user_id" not in call
    assert "session_id" not in call


async def test_conversation_passes_history_and_no_ids(bot: BaseBot):
    """Same contract on the ``conversation`` entry point."""
    await bot.conversation("q", user_id="u", session_id="s", use_vector_context=False)

    call = bot.get_client().calls[-1]
    assert "history" in call
    assert "user_id" not in call and "session_id" not in call


async def test_invoke_passes_history_and_no_ids(bot: BaseBot):
    """Same contract on the ``invoke`` entry point."""
    await bot.invoke("q", user_id="u", session_id="s", use_vector_context=False)

    call = bot.get_client().calls[-1]
    assert "history" in call
    assert "user_id" not in call and "session_id" not in call


async def test_ask_stream_passes_history_and_no_ids(bot: BaseBot):
    """Same contract on the ``ask_stream`` entry point."""
    async for _ in bot.ask_stream("q", user_id="u", session_id="s", use_vector_context=False):
        pass

    call = bot.get_client().calls[-1]
    assert "history" in call
    assert "user_id" not in call and "session_id" not in call


async def test_second_round_history_carries_first_round(bot: BaseBot):
    """The rendered history handed to the client holds the prior turn."""
    await bot.ask("round-one", user_id="u", session_id="s", use_vector_context=False)
    await bot.ask("round-two", user_id="u", session_id="s", use_vector_context=False)

    history = bot.get_client().calls[-1]["history"]

    assert [m.role for m in history] == ["user", "assistant"]
    assert history[0].content == "round-one"
    assert history[1].content == "canned-reply"
    assert all(m.chatbot_id == bot.memory_key_id for m in history)


# ---------------------------------------------------------------------------
# every read and write is keyed by memory_key_id
# ---------------------------------------------------------------------------


async def test_basebot_reads_history_with_key_id(bot: BaseBot):
    """No bot code path touches memory without ``chatbot_id``."""
    await bot.ask("q", user_id="u", session_id="s", use_vector_context=False)

    keys = bot.conversation_memory.keys
    assert keys, "memory was never touched"
    assert all(chatbot_id == bot.memory_key_id for _, chatbot_id in keys), keys


async def test_turn_stored_under_memory_key_id(bot: BaseBot):
    """The persisted turn is retrievable under the agent-segmented key."""
    await bot.ask("q", user_id="u", session_id="s", use_vector_context=False)

    history = await bot.conversation_memory.get_history(
        "u", "s", chatbot_id=bot.memory_key_id
    )
    assert len(history.turns) == 1
    assert history.turns[0].chatbot_id == bot.memory_key_id


async def test_two_agents_same_session_are_isolated():
    """Two agents sharing (user, session) get two independent histories."""
    memory = InMemoryConversation()
    first, second = await _make_bot(), await _make_bot()
    first.name = "agent-a"
    second.name = "agent-b"
    first.conversation_memory = memory
    second.conversation_memory = memory

    await first.ask("to-a", user_id="u", session_id="s", use_vector_context=False)
    await second.ask("to-b", user_id="u", session_id="s", use_vector_context=False)

    history_a = await memory.get_history("u", "s", chatbot_id="agent-a")
    history_b = await memory.get_history("u", "s", chatbot_id="agent-b")
    assert [t.user_message for t in history_a.turns] == ["to-a"]
    assert [t.user_message for t in history_b.turns] == ["to-b"]


# ---------------------------------------------------------------------------
# exactly one turn per round, on every entry point
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("entry_point", ["ask", "conversation", "invoke"])
async def test_one_turn_per_round(entry_point: str):
    """Two rounds through any entry point leave exactly two turns."""
    bot = await _make_bot()
    method = getattr(bot, entry_point)

    await method("q1", user_id="u", session_id="s", use_vector_context=False)
    await method("q2", user_id="u", session_id="s", use_vector_context=False)

    history = await bot.conversation_memory.get_history(
        "u", "s", chatbot_id=bot.memory_key_id
    )
    assert len(history.turns) == 2


async def test_ask_stream_persists_one_turn():
    """A completed stream persists exactly one turn."""
    bot = await _make_bot()

    async for _ in bot.ask_stream("q", user_id="u", session_id="s", use_vector_context=False):
        pass

    history = await bot.conversation_memory.get_history(
        "u", "s", chatbot_id=bot.memory_key_id
    )
    assert len(history.turns) == 1
    assert history.turns[0].chatbot_id == bot.memory_key_id


async def test_ask_stream_partial_save_on_error():
    """A mid-stream failure still persists the text already yielded.

    Spec §7 "Streaming partial save" — this behaviour predates FEAT-524 and must
    survive the move to the single writer.
    """

    class ExplodingClient(RecordingClient):
        async def ask_stream(self, prompt: str, **kwargs: Any):
            self.calls.append({"method": "ask_stream", "prompt": prompt, **kwargs})
            yield "partial text "
            raise RuntimeError("stream died")

    bot = BaseBot(
        name="wiring-probe",
        llm=ExplodingClient(),
        memory_type="memory",
        injection_detection=False,
    )
    await bot.configure()
    bot.conversation_memory = InMemoryConversation()

    chunks = []
    async for chunk in bot.ask_stream("q", user_id="u", session_id="s", use_vector_context=False):
        if isinstance(chunk, str):
            chunks.append(chunk)

    history = await bot.conversation_memory.get_history(
        "u", "s", chatbot_id=bot.memory_key_id
    )
    assert history is not None and len(history.turns) == 1
    assert "partial text" in history.turns[0].assistant_response
    assert history.turns[0].chatbot_id == bot.memory_key_id


# ---------------------------------------------------------------------------
# turn content + conversation-context metadata
# ---------------------------------------------------------------------------


async def test_persisted_turn_is_built_from_the_ai_message(bot: BaseBot):
    """The turn carries the canonical metadata shape from ``from_ai_message``."""
    await bot.ask("q", user_id="u", session_id="s", use_vector_context=False)

    turn = (
        await bot.conversation_memory.get_history("u", "s", chatbot_id=bot.memory_key_id)
    ).turns[0]

    assert turn.user_message == "q"
    assert turn.assistant_response == "canned-reply"
    assert set(turn.metadata) == {
        "model",
        "provider",
        "usage",
        "finish_reason",
        "response_time",
    }


async def test_conversation_context_info_measures_rendered_messages(bot: BaseBot):
    """``AIMessage`` context metadata is fed from the rendered message count."""
    await bot.ask("round-one", user_id="u", session_id="s", use_vector_context=False)
    response = await bot.ask(
        "round-two", user_id="u", session_id="s", use_vector_context=False
    )

    # One prior turn renders to two messages (user + assistant).
    assert response.conversation_context_length == 2
    assert response.used_conversation_history is True


async def test_first_round_reports_no_history(bot: BaseBot):
    """With nothing stored yet, the context metadata reports an empty history."""
    response = await bot.ask("q", user_id="u", session_id="s", use_vector_context=False)

    assert response.conversation_context_length == 0
    assert response.used_conversation_history is False


# ---------------------------------------------------------------------------
# ModelSwitchingMixin still writes exactly one turn
# ---------------------------------------------------------------------------


async def test_model_switching_fallback_single_turn():
    """``fallback`` retries on the secondary but still persists one turn.

    Spec §5 requires this for BOTH switch modes. It is also one of the reasons
    the client could not stay the writer: client-side persistence recorded the
    *failed* primary attempt.
    """
    from parrot.bots.mixins.model_switching import ModelSwitchingMixin

    class ExplodingClient(RecordingClient):
        async def ask(self, prompt: str, model: Optional[str] = None, **kwargs: Any):
            self.calls.append({"method": "ask", "prompt": prompt, **kwargs})
            raise RuntimeError("primary is down")

    class SwitchingBot(ModelSwitchingMixin, BaseBot):
        pass

    primary, secondary = ExplodingClient(), RecordingClient(reply="secondary")
    bot = SwitchingBot(
        name="fallback-probe",
        llm=primary,
        secondary_llm=secondary,
        model_switch_mode="fallback",
        memory_type="memory",
        injection_detection=False,
    )
    await bot.configure()
    bot.conversation_memory = InMemoryConversation()

    response = await bot.ask("q", user_id="u", session_id="s", use_vector_context=False)

    assert len(primary.calls) == 1 and len(secondary.calls) == 1
    assert response.output == "secondary"

    history = await bot.conversation_memory.get_history(
        "u", "s", chatbot_id=bot.memory_key_id
    )
    assert len(history.turns) == 1
    # The failed primary attempt is NOT recorded — only the answer that won.
    assert history.turns[0].assistant_response == "secondary"


async def test_model_switching_contrastive_single_turn():
    """``contrastive`` runs two clients but the bot still persists one turn."""
    from parrot.bots.mixins.model_switching import ModelSwitchingMixin

    class SwitchingBot(ModelSwitchingMixin, BaseBot):
        pass

    bot = SwitchingBot(
        name="switch-probe",
        llm=RecordingClient(reply="primary"),
        secondary_llm=RecordingClient(reply="secondary"),
        model_switch_mode="contrastive",
        memory_type="memory",
        injection_detection=False,
    )
    await bot.configure()
    bot.conversation_memory = InMemoryConversation()

    await bot.ask("q", user_id="u", session_id="s", use_vector_context=False)

    history = await bot.conversation_memory.get_history(
        "u", "s", chatbot_id=bot.memory_key_id
    )
    assert len(history.turns) == 1


# ---------------------------------------------------------------------------
# the single writer is genuinely single
# ---------------------------------------------------------------------------


async def test_no_bot_path_calls_add_turn_directly(bot: BaseBot):
    """Bots persist only through ``save_conversation_turn``.

    ``RecordingMemory`` logs the ``chatbot_id`` of every ``add_turn``; the single
    writer always supplies ``memory_key_id``, so a stray direct call with ``None``
    would show up here.
    """
    await bot.ask("q", user_id="u", session_id="s", use_vector_context=False)

    add_turns = [cid for name, cid in bot.conversation_memory.keys if name == "add_turn"]
    assert add_turns == [bot.memory_key_id]


def test_save_conversation_turn_rejects_foreign_turn_from_bot_code():
    """The writer's attribution guard is what makes 'single writer' enforceable."""
    import asyncio

    async def _run():
        bot = await _make_bot()
        with pytest.raises(ValueError):
            await bot.save_conversation_turn(
                "u", "s", ConversationTurn("t", "u", "q", "a", chatbot_id="someone-else")
            )

    asyncio.run(_run())
