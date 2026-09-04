"""Google history shape (FEAT-524, TASK-2815).

Spec §4 M5 row ``test_google_format_history``. The Google SDK's
``chats.create(history=...)`` takes typed ``UserContent`` / ``ModelContent``
objects rather than dicts, so ``GoogleGenAIClient`` overrides
``_format_history``. Before FEAT-524 that mapping was hand-inlined at six
separate call sites across ``client.py``, ``analysis.py`` and
``generation.py`` — this test pins the single shared implementation.
"""

from __future__ import annotations

import inspect

import pytest

from parrot.clients.base import AbstractClient
from parrot.memory.render import HistoryMessage

pytest.importorskip("google.genai", reason="google-genai SDK not installed")

from google.genai.types import ModelContent, UserContent  # noqa: E402

from parrot.clients.google.client import GoogleGenAIClient  # noqa: E402


def _client() -> GoogleGenAIClient:
    """A GoogleGenAIClient without running ``__init__`` (no credentials)."""
    return GoogleGenAIClient.__new__(GoogleGenAIClient)


def test_google_format_history():
    """User turns map to ``UserContent``, assistant turns to ``ModelContent``."""
    rendered = _client()._format_history([HistoryMessage("user", "q"), HistoryMessage("assistant", "a")])

    assert len(rendered) == 2
    assert isinstance(rendered[0], UserContent)
    assert isinstance(rendered[1], ModelContent)
    assert rendered[0].parts[0].text == "q"
    assert rendered[1].parts[0].text == "a"


def test_google_format_history_preserves_order():
    """Multi-turn history keeps its chronological order."""
    rendered = _client()._format_history(
        [
            HistoryMessage("user", "q1"),
            HistoryMessage("assistant", "a1"),
            HistoryMessage("user", "q2"),
            HistoryMessage("assistant", "a2"),
        ]
    )

    assert [p.parts[0].text for p in rendered] == ["q1", "a1", "q2", "a2"]
    assert [type(p).__name__ for p in rendered] == [
        "UserContent",
        "ModelContent",
        "UserContent",
        "ModelContent",
    ]


def test_google_format_history_empty():
    """Empty / ``None`` history renders to an empty list."""
    client = _client()

    assert client._format_history(()) == []
    assert client._format_history(None) == []


def test_google_format_history_skips_blank_content():
    """Blank text is dropped — the SDK rejects contentless parts."""
    rendered = _client()._format_history([HistoryMessage("user", "   "), HistoryMessage("assistant", "a")])

    assert len(rendered) == 1
    assert isinstance(rendered[0], ModelContent)


def test_google_overrides_base_format_history():
    """The override is real, and differs from the base dict shape."""
    assert GoogleGenAIClient._format_history is not AbstractClient._format_history

    base = AbstractClient._format_history(_client(), [HistoryMessage("user", "q")])
    assert base == [{"role": "user", "content": [{"type": "text", "text": "q"}]}]


def test_google_dict_messages_stays_dict_shaped():
    """``_dict_messages`` must NOT return typed Content — ``resume()`` needs dicts.

    ``resume()`` rebuilds its chat from ``state["messages"]`` by calling
    ``msg.get("role")`` on each entry, so mixing SDK objects into that
    accumulator would raise ``AttributeError`` on the first resumed tool call.
    """
    messages = _client()._dict_messages("q2", None, [HistoryMessage("user", "q1")])

    assert all(isinstance(m, dict) for m in messages), messages
    assert [m["role"] for m in messages] == ["user", "user"]
    assert messages[-1]["content"][0]["text"] == "q2"
    # Every entry answers .get("role") — the exact call resume() makes.
    assert [m.get("role") for m in messages] == ["user", "user"]


def test_google_ask_signature_is_memoryless():
    """``ask``/``ask_stream`` take ``history``, and no ids or ``stateless``."""
    for name in ("ask", "ask_stream"):
        parameters = inspect.signature(getattr(GoogleGenAIClient, name)).parameters
        assert "history" in parameters, name
        assert "user_id" not in parameters, name
        assert "session_id" not in parameters, name
        assert "stateless" not in parameters, name
