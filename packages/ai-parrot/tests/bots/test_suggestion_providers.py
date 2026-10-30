"""Tests for the built-in deterministic suggestion providers (FEAT-752, TASK-4798)."""

from pathlib import Path

import pytest

from parrot.bots.suggestions import SuggestionContext
from parrot.bots.suggestions import engine as engine_mod
from parrot.bots.suggestions.providers import (
    ExplainSuggestionProvider,
    PresentationSuggestionProvider,
    SkillSuggestionProvider,
    has_tabular_data,
)
from parrot.models import AIMessage
from parrot.models.basic import CompletionUsage
from parrot.models.outputs import OutputMode
from parrot.skills.models import SkillDefinition, SkillSource, SkillSuggestion
from parrot.skills.tenancy import enter_active_skill_scope, exit_active_skill_scope, set_active_skill


@pytest.fixture
def ai_message_with_table() -> AIMessage:
    return AIMessage(
        input="q",
        output="text",
        data=[{"month": "Sep", "sales": 10}, {"month": "Oct", "sales": 12}],
        model="fake",
        provider="fake",
        usage=CompletionUsage(),
        output_mode=OutputMode.DEFAULT,
    )


@pytest.fixture
def ai_message_no_data() -> AIMessage:
    return AIMessage(input="q", output="text", model="fake", provider="fake", usage=CompletionUsage())


class BotWithFollowup:
    async def followup(self, *a, **k):
        return None


def _ctx(msg, bot, mode=OutputMode.DEFAULT):
    return SuggestionContext(question="q", response=msg, output_mode=mode, bot=bot)


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


async def test_skill_provider_emits_only_turn_skill(ai_message_with_table):
    token = enter_active_skill_scope()
    try:
        provider = SkillSuggestionProvider(None)
        assert await provider.suggest(_ctx(ai_message_with_table, None)) == []

        skill = _skill(
            [
                SkillSuggestion(label="Kpi", prompt="show kpi", output_mode="card"),
                SkillSuggestion(label="Bad", prompt="bad mode", output_mode="bogus"),
                SkillSuggestion(label="Why", prompt="why did it change?"),
            ]
        )
        set_active_skill(skill)
        set_active_skill(None)  # what create_system_prompt does

        chips = await provider.suggest(_ctx(ai_message_with_table, None))
        assert [c.label for c in chips] == ["Kpi", "Why"]  # only the invalid chip is dropped
        assert chips[0].kind == "presentation" and chips[0].output_mode == "card"
        assert chips[1].kind == "followup" and chips[1].output_mode is None
        assert all(c.source == "skill" for c in chips)
    finally:
        exit_active_skill_scope(token)


async def test_skill_provider_skill_without_suggestions(ai_message_with_table):
    token = enter_active_skill_scope()
    try:
        set_active_skill(_skill([]))
        assert await SkillSuggestionProvider(None).suggest(_ctx(ai_message_with_table, None)) == []
    finally:
        exit_active_skill_scope(token)


async def test_presentation_provider_rules(ai_message_with_table, ai_message_no_data, monkeypatch):
    provider = PresentationSuggestionProvider(None)

    # no tabular data -> no chips
    assert await provider.suggest(_ctx(ai_message_no_data, None)) == []

    # all modes, fixed order table -> chart -> KPI
    chips = await provider.suggest(_ctx(ai_message_with_table, None))
    assert [c.label for c in chips] == ["View as table", "View as chart", "View as KPI"]
    assert all(c.kind == "presentation" and c.source == "provider" for c in chips)
    assert [c.output_mode for c in chips] == ["structured_table", "structured_chart", "card"]

    # the current mode is excluded
    chips = await provider.suggest(_ctx(ai_message_with_table, None, mode=OutputMode.STRUCTURED_TABLE))
    assert [c.label for c in chips] == ["View as chart", "View as KPI"]

    # the response's own mode is excluded too
    ai_message_with_table.output_mode = OutputMode.STRUCTURED_CHART
    chips = await provider.suggest(_ctx(ai_message_with_table, None))
    assert [c.label for c in chips] == ["View as table", "View as KPI"]
    ai_message_with_table.output_mode = OutputMode.DEFAULT

    # a mode without a registered renderer is excluded
    real_get_renderer = engine_mod.get_renderer

    def fake_get_renderer(mode):
        if mode == OutputMode.CARD:
            raise ValueError("no renderer")
        return real_get_renderer(mode)

    monkeypatch.setattr(engine_mod, "get_renderer", fake_get_renderer)
    chips = await provider.suggest(_ctx(ai_message_with_table, None))
    assert [c.label for c in chips] == ["View as table", "View as chart"]


async def test_presentation_provider_mode_priority(ai_message_with_table):
    class Bot:
        presentation_modes = ["structured_chart"]

    # bot attribute restricts the defaults
    chips = await PresentationSuggestionProvider(Bot()).suggest(_ctx(ai_message_with_table, None))
    assert [c.label for c in chips] == ["View as chart"]

    # the constructor argument wins over the bot attribute
    provider = PresentationSuggestionProvider(Bot(), modes=[OutputMode.STRUCTURED_TABLE])
    chips = await provider.suggest(_ctx(ai_message_with_table, None))
    assert [c.label for c in chips] == ["View as table"]

    # unknown mode values are ignored, never raised
    provider = PresentationSuggestionProvider(None, modes=["nope", OutputMode.CARD])
    chips = await provider.suggest(_ctx(ai_message_with_table, None))
    assert [c.label for c in chips] == ["View as KPI"]


async def test_explain_provider_requires_data_and_followup(ai_message_with_table, ai_message_no_data):
    assert await ExplainSuggestionProvider(object()).suggest(_ctx(ai_message_with_table, None)) == []

    bot = BotWithFollowup()
    assert await ExplainSuggestionProvider(bot).suggest(_ctx(ai_message_no_data, bot)) == []

    chips = await ExplainSuggestionProvider(bot).suggest(_ctx(ai_message_with_table, bot))
    assert len(chips) == 1
    assert chips[0].action == "explain"
    assert chips[0].kind == "action"
    assert chips[0].source == "provider"


def test_has_tabular_data():
    def msg(data):
        return AIMessage(input="q", output="a", data=data, model="fake", provider="fake", usage=CompletionUsage())

    assert has_tabular_data(msg(None)) is False
    assert has_tabular_data(msg([])) is False
    assert has_tabular_data(msg("x")) is False
    assert has_tabular_data(msg([1, 2])) is False
    assert has_tabular_data(msg([{"a": 1}, 2])) is False
    assert has_tabular_data(msg([{"a": 1}])) is True


def test_has_tabular_data_dataframe_like():
    class Frame:
        def __init__(self, empty):
            self.empty = empty

        def to_dict(self):
            return {}

        def to_string(self):
            return ""

    def msg(data):
        return AIMessage(input="q", output="a", data=data, model="fake", provider="fake", usage=CompletionUsage())

    assert has_tabular_data(msg(Frame(empty=False))) is True
    assert has_tabular_data(msg(Frame(empty=True))) is False
