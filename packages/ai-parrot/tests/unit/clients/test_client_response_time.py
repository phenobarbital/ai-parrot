"""Regression tests: provider clients set ``AIMessage.response_time`` in ``ask()``.

The real ``ask()`` bodies need live SDK objects, so the clients are checked
structurally: the method must compute the elapsed time once, feed it to
``_emit_after_call(duration_ms=...)`` and to ``response_time`` (seconds).
"""

import re
from pathlib import Path

import pytest

from parrot.memory.abstract import ConversationTurn
from parrot.models.responses import AIMessage, CompletionUsage

_SRC = next(p for p in Path(__file__).resolve().parents if (p / "ai-parrot" / "src").is_dir())

_CLIENT_FILES = {
    "google": "ai-parrot-client-google/src/parrot/clients/google/client.py",
    "anthropic": "ai-parrot-client-anthropic/src/parrot/clients/anthropic/client.py",
    "openai_base": "ai-parrot/src/parrot/clients/openai_base.py",
    "openai": "ai-parrot-client-openai/src/parrot/clients/openai/client.py",
    "groq": "ai-parrot-client-groq/src/parrot/clients/groq/client.py",
    "bedrock": "ai-parrot-client-amazon/src/parrot/clients/amazon/bedrock.py",
}


@pytest.mark.parametrize("name", sorted(_CLIENT_FILES))
def test_ask_sets_response_time_from_emitted_duration(name: str) -> None:
    """The elapsed value is computed once and shared by response_time and duration_ms."""
    path = _SRC / _CLIENT_FILES[name]
    if not path.exists():
        pytest.skip(f"{name} client not present in this checkout")
    text = path.read_text()
    match = re.search(
        r"(?P<var>_lc_\w*duration_ms) = \(.*\) \* 1000\n"
        r"\s+if ai_message\.response_time is None:\n"
        r"\s+ai_message\.response_time = (?P=var) / 1000\n"
        r"\s+await self\._emit_after_call\((?:.|\n)*?duration_ms=(?P=var),",
        text,
    )
    assert match is not None, f"{name}: ask() does not set response_time from duration_ms"


def test_turn_from_message_carries_response_time() -> None:
    """A message with response_time yields a non-null turn metadata value."""
    message = AIMessage(
        input="hi",
        output="hello",
        model="m",
        provider="p",
        usage=CompletionUsage(),
        response_time=0.25,
    )
    turn = ConversationTurn.from_ai_message(user_message="hi", response=message, user_id="u", chatbot_id="bot")
    assert turn.metadata["response_time"] == pytest.approx(0.25)
    assert message.response_time >= 0
