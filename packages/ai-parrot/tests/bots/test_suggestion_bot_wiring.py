"""Tests for bot wiring of follow-up suggestion chips (FEAT-752, TASK-4800)."""

import inspect
import logging
from pathlib import Path

import pytest

from parrot.models import AIMessage, Suggestion, SuggestionBatch
from parrot.models.basic import CompletionUsage
from parrot.models.outputs import OutputMode
from parrot.models.responses import InvokeResult
from parrot.skills.models import SkillDefinition, SkillSource, SkillSuggestion
from parrot.skills.tenancy import enter_active_skill_scope, exit_active_skill_scope, set_active_skill


def _base_bot_cls():
    try:
        from parrot.bots.base import BaseBot
    except Exception as exc:  # noqa: BLE001 — same guard as test_linked_surface_lifting.py:19-24
        pytest.skip(f"cannot import parrot.bots.base: {exc}")
    return BaseBot


def _bare_bot(**flags):
    """BaseBot instance without __init__: set only what the suggestion surface reads."""
    cls = _base_bot_cls()
    cls_ = type("BareBot", (cls,), {"__abstractmethods__": frozenset()})
    bot = object.__new__(cls_)
    bot.logger = logging.getLogger("test")
    bot.suggest_followups = flags.get("suggest_followups", False)
    bot.enable_suggestions = flags.get("enable_suggestions", False) or bot.suggest_followups
    bot.suggestion_timeout_s, bot.max_suggestions, bot.suggestion_model = 1.0, 6, flags.get("suggestion_model")
    bot._suggestion_engine = None
    return bot


def _msg(data=None):
    return AIMessage(input="q", output="a", data=data, model="m", provider="p", usage=CompletionUsage())


class FakeClient:
    def __init__(self, output=None, exc=None):
        self.calls, self._output, self._exc = [], output, exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def invoke(self, prompt, **kw):
        self.calls.append((prompt, kw))
        if self._exc:
            raise self._exc
        return InvokeResult(
            output=self._output, output_type=SuggestionBatch, model="fake-lite", usage=CompletionUsage()
        )

    async def ask(self, *a, **k):
        raise AssertionError("ask must not be called")


def _skill(suggestions):
    return SkillDefinition(
        name="s",
        description="d",
        triggers=["/s"],
        source=SkillSource.AUTHORED,
        template_body="b",
        token_count=1,
        file_path=Path("/tmp/s.md"),
        suggestions=suggestions,
    )


async def test_bot_attach_noop_without_optin():
    bot = _bare_bot()
    msg = await bot._attach_suggestions("q", _msg([{"a": 1}]), output_mode=OutputMode.DEFAULT)
    assert msg.suggestions == [] and "suggestions" not in (msg.metadata or {})
    assert bot._suggestion_engine is None  # engine never even built


def test_ask_and_ask_stream_attach_once():
    cls = _base_bot_cls()
    for meth, pipeline in (("ask", 'method="ask")'), ("ask_stream", 'method="ask_stream")')):
        src = inspect.getsource(getattr(cls, meth))
        assert src.count("_attach_suggestions(") == 1
        assert src.index(pipeline) < src.index("_attach_suggestions(")


def test_suggestion_lanes():
    assert _bare_bot()._suggestion_lanes() == frozenset({"skill"})
    assert _bare_bot(enable_suggestions=True)._suggestion_lanes() == frozenset({"skill", "deterministic"})
    assert _bare_bot(suggest_followups=True)._suggestion_lanes() == frozenset({"skill", "deterministic", "llm"})


async def test_deterministic_chips_without_llm():
    bot = _bare_bot(enable_suggestions=True)
    msg = await bot._attach_suggestions("q", _msg([{"a": 1}]), output_mode=OutputMode.DEFAULT)
    labels = [c.label for c in msg.suggestions]
    assert "Explain this" not in labels  # bare bot has no followup()
    assert "View as table" in labels
    assert msg.metadata["suggestions"]["providers"]["llm"]["status"] == "skipped"
    assert msg.metadata["suggestions"]["llm"] is None


async def test_bot_register_provider_prepend():
    class First:
        name = "first"
        lane = "deterministic"

        async def suggest(self, ctx):
            return [Suggestion(label="First", prompt="first")]

    bot = _bare_bot(enable_suggestions=True)
    bot.register_suggestion_provider(First(), prepend=True)
    msg = await bot._attach_suggestions("q", _msg([{"a": 1}]), output_mode=OutputMode.DEFAULT)
    assert msg.suggestions[0].label == "First"
    assert [p.name for p in bot._get_suggestion_engine().providers][:2] == ["skill", "first"]


async def test_suggestions_end_to_end_fake_client():
    client = FakeClient(output=SuggestionBatch(suggestions=[Suggestion(label="Why?", prompt="Why did it change?")]))
    bot = _bare_bot(suggest_followups=True)
    bot.get_client = lambda: client

    async def followup(*a, **k):
        return None

    bot.followup = followup

    token = enter_active_skill_scope()
    try:
        set_active_skill(_skill([SkillSuggestion(label="Skill chip", prompt="from the skill")]))
        set_active_skill(None)  # prompt build clears the active skill; the turn skill survives
        msg = await bot._attach_suggestions("q", _msg([{"a": 1}]), output_mode=OutputMode.DEFAULT)
    finally:
        exit_active_skill_scope(token)

    assert [c.label for c in msg.suggestions] == [
        "Skill chip",
        "View as table",
        "View as chart",
        "View as KPI",
        "Explain this",
        "Why?",
    ]
    assert len(client.calls) == 1
    assert msg.metadata["suggestions"]["llm"]["model"] == "fake-lite"
    assert msg.metadata["suggestions"]["count"] == 6


async def test_attach_never_raises_and_keeps_response(monkeypatch):
    bot = _bare_bot(enable_suggestions=True)

    def boom():
        raise RuntimeError("engine build failed")

    bot._get_suggestion_engine = boom
    original = _msg([{"a": 1}])
    result = await bot._attach_suggestions("q", original, output_mode=OutputMode.DEFAULT)
    assert result is original
    assert result.suggestions == []


async def test_suggestion_model_reaches_llm_provider():
    bot = _bare_bot(suggest_followups=True, suggestion_model="cheap-model")
    client = FakeClient(output=SuggestionBatch(suggestions=[Suggestion(label="Why?", prompt="Why?")]))
    bot.get_client = lambda: client
    await bot._attach_suggestions("q", _msg(None), output_mode=OutputMode.DEFAULT)
    assert client.calls[0][1]["model"] == "cheap-model"
