"""Bedrock Converse history shape (FEAT-524, TASK-2813).

Spec §4 M5 row ``test_bedrock_format_history``. Bedrock's Converse API uses
``{"role", "content": [{"text": ...}]}`` rather than the Anthropic-style
``{"type": "text", "text": ...}`` blocks the base class emits, so
``BedrockConverseClient`` overrides ``_format_history`` — and only that.
"""

from __future__ import annotations

import inspect

from parrot.clients.base import AbstractClient
from parrot.clients.amazon.bedrock import BedrockConverseClient
from parrot.memory.render import HistoryMessage


def _client() -> BedrockConverseClient:
    """A BedrockConverseClient without running ``__init__`` (no AWS session)."""
    return BedrockConverseClient.__new__(BedrockConverseClient)


def test_bedrock_format_history():
    """History renders as Converse ``{"text": ...}`` content blocks."""
    client = _client()

    messages = client._format_history([HistoryMessage("user", "q"), HistoryMessage("assistant", "a")])

    assert messages == [
        {"role": "user", "content": [{"text": "q"}]},
        {"role": "assistant", "content": [{"text": "a"}]},
    ]


def test_bedrock_overrides_base_format_history():
    """The override is real — not accidentally inheriting the base shape."""
    assert BedrockConverseClient._format_history is not AbstractClient._format_history

    base_shape = AbstractClient._format_history(_client(), [HistoryMessage("user", "q")])
    assert base_shape == [{"role": "user", "content": [{"type": "text", "text": "q"}]}]


def test_bedrock_format_history_empty():
    """Empty history renders to an empty list."""
    assert _client()._format_history(()) == []


def test_bedrock_build_messages_is_uniformly_converse_shaped():
    """History and the current turn share one shape before ``_to_bedrock_messages``.

    ``_prepare_messages`` was already overridden to Converse shape; adding the
    matching ``_format_history`` override is what keeps the whole list uniform.
    """
    client = _client()

    messages = client._build_messages("q2", None, [HistoryMessage("user", "q1")])

    assert [m["role"] for m in messages] == ["user", "user"]
    for message in messages:
        for block in message["content"]:
            assert set(block) == {"text"}, block
    assert messages[-1]["content"][0]["text"] == "q2"


def test_bedrock_ask_signature_is_memoryless():
    """``ask``/``ask_stream`` take ``history`` and no ids."""
    for name in ("ask", "ask_stream"):
        parameters = inspect.signature(getattr(BedrockConverseClient, name)).parameters
        assert "history" in parameters, name
        assert "user_id" not in parameters, name
        assert "session_id" not in parameters, name
