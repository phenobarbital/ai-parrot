"""``AbstractClient`` is memory-less and takes ``history=`` (FEAT-524, TASK-2812).

Spec §3 Module 4, §4 M4 rows. The base client no longer owns, loads or writes
conversation history: it receives an already-rendered
:class:`~parrot.memory.render.HistoryMessage` sequence and only maps it onto
its provider's message shape.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any, Dict

import pytest

from parrot.clients.base import AbstractClient
from parrot.memory.render import HistoryMessage


class StubClient(AbstractClient):
    """Concrete no-network client used to exercise the base-class helpers."""

    client_type = "stub"
    supported_models = ["stub"]

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("model", "stub")
        super().__init__(**kwargs)

    async def get_client(self):  # pragma: no cover - never invoked here
        return self

    async def ask(self, prompt, model=None, **kwargs):  # pragma: no cover
        raise NotImplementedError

    async def ask_stream(self, prompt, **kwargs):  # pragma: no cover
        yield ""

    async def resume(self, session_id, user_input, state):  # pragma: no cover
        raise NotImplementedError

    async def invoke(self, prompt, **kwargs):  # pragma: no cover
        raise NotImplementedError


@pytest.fixture
def client() -> StubClient:
    """A bare stub client."""
    return StubClient()


# ---------------------------------------------------------------------------
# The memory surface is gone
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "conversation_memory",
        "_prepare_conversation_context",
        "_update_conversation_memory",
        "start_conversation",
        "get_conversation",
        "clear_conversation",
        "delete_conversation",
        "list_user_conversations",
        "_get_chatbot_key",
        "create_conversation_memory",
    ],
)
def test_client_has_no_memory_surface(name: str):
    """Every conversation-memory member was removed from the class."""
    assert not hasattr(AbstractClient, name), name


def test_client_instance_has_no_conversation_memory(client: StubClient):
    """Instances get no default store either — not even an empty one."""
    assert not hasattr(client, "conversation_memory")


def test_init_rejects_conversation_memory_kwarg():
    """``conversation_memory=`` is not silently swallowed by ``**kwargs``.

    It IS accepted by ``**kwargs`` at the signature level, but it must no
    longer become an attribute — passing it must not resurrect the old
    behaviour by accident.
    """
    parameters = inspect.signature(AbstractClient.__init__).parameters

    assert "conversation_memory" not in parameters


def test_base_module_imports_no_storage_backend():
    """``clients/base.py`` must not import any ``parrot.memory`` storage class.

    Only the leaf render type is allowed, so installing an LLM client never
    drags in Redis or aiofiles (spec §5 acceptance criteria).
    """
    source = Path(inspect.getfile(AbstractClient)).read_text(encoding="utf-8")

    for forbidden in (
        "InMemoryConversation",
        "FileConversationMemory",
        "RedisConversation",
        "ConversationMemory",
        "ConversationTurn",
    ):
        # Allowed only inside explanatory comments, never as code.
        code_lines = [
            line for line in source.splitlines()
            if forbidden in line and not line.lstrip().startswith("#")
        ]
        assert code_lines == [], (forbidden, code_lines)


# ---------------------------------------------------------------------------
# ask / ask_stream signatures
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method", ["ask", "ask_stream"])
def test_signature_has_history_and_no_ids(method: str):
    """``history`` replaces ``user_id``/``session_id`` on both entry points."""
    parameters = inspect.signature(getattr(AbstractClient, method)).parameters

    assert "history" in parameters
    assert "user_id" not in parameters
    assert "session_id" not in parameters


@pytest.mark.parametrize("method", ["ask", "ask_stream"])
def test_history_defaults_to_none(method: str):
    """History is optional — a bare client call stays memory-less."""
    assert inspect.signature(getattr(AbstractClient, method)).parameters["history"].default is None


def test_ask_has_no_stateless_parameter():
    """``stateless`` died with the helper it belonged to; do not re-add it."""
    assert "stateless" not in inspect.signature(AbstractClient.ask).parameters


# ---------------------------------------------------------------------------
# _format_history
# ---------------------------------------------------------------------------


def test_format_history_default_shape(client: StubClient):
    """Default mapping is one text content block per message, in order."""
    history = [HistoryMessage("user", "q1"), HistoryMessage("assistant", "a1")]

    assert client._format_history(history) == [
        {"role": "user", "content": [{"type": "text", "text": "q1"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "a1"}]},
    ]


def test_format_history_empty(client: StubClient):
    """An empty history formats to an empty list, not ``None``."""
    assert client._format_history(()) == []


def test_format_history_is_overridable():
    """Providers customise only ``_format_history``; ``_build_messages`` composes."""

    class ConverseClient(StubClient):
        def _format_history(self, history):
            return [{"role": m.role, "content": [{"text": m.content}]} for m in history]

    messages = ConverseClient()._build_messages("q2", None, [HistoryMessage("user", "q1")])

    assert messages[0] == {"role": "user", "content": [{"text": "q1"}]}
    # The current turn still comes from _prepare_messages, unchanged.
    assert messages[-1]["content"][0]["text"] == "q2"


# ---------------------------------------------------------------------------
# _build_messages
# ---------------------------------------------------------------------------


def test_build_messages_history_then_prompt(client: StubClient):
    """Ordering is ``[*history, current]`` — the FEAT-302 guarantee."""
    history = [HistoryMessage("user", "q1"), HistoryMessage("assistant", "a1")]

    messages = client._build_messages("q2", None, history)

    assert [m["role"] for m in messages] == ["user", "assistant", "user"]
    assert messages[-1]["content"][0]["text"] == "q2"


def test_build_messages_without_history(client: StubClient):
    """No history ⇒ just the current turn."""
    messages = client._build_messages("q", None, None)

    assert len(messages) == 1
    assert messages[0]["content"][0]["text"] == "q"


def test_build_messages_encodes_current_turn_once(client: StubClient):
    """The prompt text must appear in exactly one message."""
    history = [HistoryMessage("user", "q1"), HistoryMessage("assistant", "a1")]

    messages = client._build_messages("unique-prompt-text", None, history)

    matches = [m for m in messages if "unique-prompt-text" in str(m)]
    assert len(matches) == 1


def test_build_messages_skips_missing_file(client: StubClient, tmp_path, caplog):
    """A nonexistent attachment is logged and skipped, never raised."""
    missing = str(tmp_path / "missing.pdf")

    with caplog.at_level("ERROR"):
        messages = client._build_messages("q2", [missing], [HistoryMessage("user", "q1")])

    assert [m["role"] for m in messages] == ["user", "user"]
    # Only the text block survives — no attachment was encoded.
    assert messages[-1]["content"] == [{"type": "text", "text": "q2"}]
    assert "file does not exist" in caplog.text


def test_build_messages_keeps_existing_file(client: StubClient, tmp_path):
    """An attachment that exists is passed through to ``_prepare_messages``."""
    real = tmp_path / "note.txt"
    real.write_text("hello", encoding="utf-8")

    messages = client._build_messages("q", [str(real)], None)

    assert len(messages[-1]["content"]) == 2  # text block + encoded file


def test_existing_files_returns_none_for_empty(client: StubClient):
    """``None``/empty in, ``None`` out — ``_prepare_messages`` expects that."""
    assert client._existing_files(None) is None
    assert client._existing_files([]) is None


def test_existing_files_all_missing_returns_none(client: StubClient, tmp_path):
    """When nothing survives the filter the result is ``None``, not ``[]``."""
    assert client._existing_files([str(tmp_path / "nope.pdf")]) is None


def test_build_messages_accepts_any_sequence(client: StubClient):
    """History is typed ``Sequence`` — a tuple must work as well as a list."""
    messages = client._build_messages("q2", None, (HistoryMessage("user", "q1"),))

    assert [m["role"] for m in messages] == ["user", "user"]
