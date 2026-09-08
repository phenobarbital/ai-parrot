"""Unit tests for ``ConversationTurn`` attribution (FEAT-524, TASK-2809).

Covers the ``chatbot_id`` field round-trip (including legacy records written
before the field existed) and the canonical ``from_ai_message`` constructor —
spec §2 "Data Models", §4 M2 rows.
"""

from __future__ import annotations

from parrot.memory import ConversationHistory, ConversationTurn
from parrot.models import AIMessage
from parrot.models.responses import CompletionUsage, ToolCall


def _turn(chatbot_id: str | None = None) -> ConversationTurn:
    """A minimal turn with an optional owning agent."""
    return ConversationTurn(
        turn_id="t1",
        user_id="u",
        user_message="q",
        assistant_response="a",
        chatbot_id=chatbot_id,
    )


def test_chatbot_id_defaults_to_none():
    """Existing positional construction keeps working; the field is last."""
    turn = ConversationTurn("t1", "u", "q", "a")

    assert turn.chatbot_id is None


def test_turn_chatbot_id_roundtrip():
    """``to_dict``/``from_dict`` carry ``chatbot_id``."""
    turn = _turn(chatbot_id="X")

    assert turn.to_dict()["chatbot_id"] == "X"
    assert ConversationTurn.from_dict(turn.to_dict()).chatbot_id == "X"


def test_turn_legacy_dict_without_chatbot_id():
    """A record written before FEAT-524 still deserializes, with ``None``."""
    legacy = {k: v for k, v in _turn("X").to_dict().items() if k != "chatbot_id"}

    assert ConversationTurn.from_dict(legacy).chatbot_id is None


def test_history_roundtrip_preserves_turn_attribution():
    """Attribution survives a full ``ConversationHistory`` round-trip."""
    history = ConversationHistory(session_id="s", user_id="u", chatbot_id="X")
    history.add_turn(_turn("X"))

    restored = ConversationHistory.from_dict(history.to_dict())

    assert restored.chatbot_id == "X"
    assert restored.turns[0].chatbot_id == "X"


def _ai_message(**overrides) -> AIMessage:
    """A canned ``AIMessage`` as a client would return it."""
    defaults = dict(
        input="q",
        output="the answer",
        model="stub-model",
        provider="stub-provider",
        usage=CompletionUsage(),
        finish_reason="stop",
        response_time=1.25,
        turn_id="turn-from-response",
    )
    defaults.update(overrides)
    return AIMessage(**defaults)


def test_from_ai_message_metadata_shape():
    """The canonical metadata keys are always present, and only those."""
    turn = ConversationTurn.from_ai_message(
        user_message="q",
        response=_ai_message(),
        user_id="u",
        chatbot_id="bot-a",
    )

    assert set(turn.metadata) == {
        "model",
        "provider",
        "usage",
        "finish_reason",
        "response_time",
    }
    assert turn.metadata["model"] == "stub-model"
    assert turn.metadata["provider"] == "stub-provider"
    assert turn.metadata["finish_reason"] == "stop"
    assert turn.metadata["response_time"] == 1.25
    # ``usage`` is serialized to a plain dict so every backend can persist it.
    assert isinstance(turn.metadata["usage"], dict)


def test_from_ai_message_core_fields():
    """User/assistant text, ids and attribution come from the right places."""
    turn = ConversationTurn.from_ai_message(
        user_message="q",
        response=_ai_message(),
        user_id="u",
        chatbot_id="bot-a",
        context_used="ctx",
    )

    assert turn.user_id == "u"
    assert turn.user_message == "q"
    assert turn.assistant_response == "the answer"
    assert turn.chatbot_id == "bot-a"
    assert turn.context_used == "ctx"
    assert turn.turn_id == "turn-from-response"


def test_from_ai_message_tools_used():
    """``tools_used`` is derived from the response's tool calls."""
    response = _ai_message(
        tool_calls=[
            ToolCall(id="1", name="search", arguments={}),
            ToolCall(id="2", name="calc", arguments={}),
        ]
    )

    turn = ConversationTurn.from_ai_message(user_message="q", response=response, user_id="u", chatbot_id="bot-a")

    assert turn.tools_used == ["search", "calc"]


def test_from_ai_message_no_tool_calls():
    """No tool calls ⇒ an empty list, never ``None``."""
    turn = ConversationTurn.from_ai_message(user_message="q", response=_ai_message(), user_id="u", chatbot_id="bot-a")

    assert turn.tools_used == []


def test_from_ai_message_explicit_turn_id_wins():
    """An explicit ``turn_id`` overrides the response's."""
    turn = ConversationTurn.from_ai_message(
        user_message="q",
        response=_ai_message(),
        user_id="u",
        chatbot_id="bot-a",
        turn_id="explicit",
    )

    assert turn.turn_id == "explicit"


def test_from_ai_message_generates_turn_id_when_absent():
    """With no id anywhere, a uuid4 is minted rather than storing ``None``."""
    turn = ConversationTurn.from_ai_message(
        user_message="q",
        response=_ai_message(turn_id=None),
        user_id="u",
        chatbot_id="bot-a",
    )

    assert turn.turn_id
    assert turn.turn_id != "turn-from-response"


def test_from_ai_message_assistant_text_override():
    """The streaming partial-save path can supply the accumulated text.

    ``ask_stream`` persists whatever text it accumulated when the stream dies
    mid-flight; that text — not the synthesized ``AIMessage`` — is
    authoritative (spec §7 "Streaming partial save").
    """
    turn = ConversationTurn.from_ai_message(
        user_message="q",
        response=_ai_message(),
        user_id="u",
        chatbot_id="bot-a",
        assistant_text="partial text so far",
    )

    assert turn.assistant_response == "partial text so far"


def test_from_ai_message_empty_assistant_text_override_is_honoured():
    """An explicit empty override is respected — it is not 'falsy, use response'."""
    turn = ConversationTurn.from_ai_message(
        user_message="q",
        response=_ai_message(),
        user_id="u",
        chatbot_id="bot-a",
        assistant_text="",
    )

    assert turn.assistant_response == ""


def test_from_ai_message_result_is_persistable():
    """The produced turn survives ``to_dict``/``from_dict`` unchanged."""
    turn = ConversationTurn.from_ai_message(user_message="q", response=_ai_message(), user_id="u", chatbot_id="bot-a")

    restored = ConversationTurn.from_dict(turn.to_dict())

    assert restored.chatbot_id == "bot-a"
    assert restored.assistant_response == "the answer"
    assert restored.metadata["model"] == "stub-model"


def test_get_messages_for_api_removed():
    """The provider-aware renderer is gone; ``render_history`` replaces it."""
    assert not hasattr(ConversationHistory, "get_messages_for_api")
