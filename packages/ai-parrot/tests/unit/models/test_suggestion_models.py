"""Tests for FEAT-752 follow-up suggestion models."""

import pytest
from pydantic import ValidationError

from parrot.models import AIMessage, Suggestion, SuggestionBatch
from parrot.models.basic import CompletionUsage
from parrot.models.outputs import OutputMode


def _msg(**kw) -> AIMessage:
    return AIMessage(input="q", output="a", model="fake", provider="fake", usage=CompletionUsage(), **kw)


def test_suggestion_label_max_40():
    """Labels at the schema boundary validate correctly."""
    Suggestion(label="x" * 40, prompt="p")
    with pytest.raises(ValidationError):
        Suggestion(label="x" * 41, prompt="p")


def test_suggestion_strips_and_rejects_blank():
    """Suggestion text is normalized before validation."""
    assert Suggestion(label="  a   b ", prompt="p").label == "a b"
    with pytest.raises(ValidationError):
        Suggestion(label="   ", prompt="p")


def test_suggestion_action_requires_kind_action():
    """Actions must use the action kind and an allowed action id."""
    with pytest.raises(ValidationError):
        Suggestion(label="Explain", prompt="p", action="explain")
    with pytest.raises(ValidationError):
        Suggestion(label="Explain", prompt="p", kind="action")
    with pytest.raises(ValidationError):
        Suggestion(label="Other", prompt="p", kind="action", action="other")
    suggestion = Suggestion(label="Explain", prompt="p", kind="action", action="explain")
    assert suggestion.action == "explain"


def test_suggestion_batch_max_four():
    """The LLM batch cannot exceed four chips."""
    suggestion = Suggestion(label="Follow up", prompt="p")
    with pytest.raises(ValidationError):
        SuggestionBatch(suggestions=[suggestion] * 5)


def test_aimessage_suggestions_default_empty_and_roundtrip():
    """AI messages preserve suggestion chips through serialization and rendering."""
    assert _msg().suggestions == []
    message = _msg(
        suggestions=[
            Suggestion(
                label="View as table",
                prompt="p",
                output_mode=OutputMode.STRUCTURED_TABLE,
                kind="presentation",
            )
        ]
    )
    dumped = message.model_dump()
    assert dumped["suggestions"][0]["output_mode"] == "structured_table"
    assert AIMessage(**dumped).suggestions == message.suggestions

    class Formatter:
        """Minimal formatter used to exercise AIMessage.render_as."""

        def format(self, mode, source, **kwargs):
            """Return the original source for this preservation test."""
            return source

    assert message.render_as(OutputMode.MARKDOWN, Formatter()).suggestions == message.suggestions
