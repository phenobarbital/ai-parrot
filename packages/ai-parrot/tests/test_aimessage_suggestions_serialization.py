"""AIMessage omits an empty ``suggestions`` key when serialized (FEAT-752 follow-up)."""
from parrot.models.responses import AIMessage
from parrot.models.basic import CompletionUsage
from parrot.models.suggestions import Suggestion


def _msg(**kw) -> AIMessage:
    return AIMessage(input="q", output="a", model="m", provider="openai", usage=CompletionUsage(), **kw)


def test_empty_suggestions_omitted():
    assert "suggestions" not in _msg().to_dict()
    assert "suggestions" not in _msg().model_dump()


def test_populated_suggestions_kept_and_roundtrip():
    chip = Suggestion(label="more", prompt="more?")
    m = _msg(suggestions=[chip])
    assert m.to_dict()["suggestions"]
