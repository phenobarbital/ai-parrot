"""Regression tests for AgentCrew.ask() user-prompt construction.

Covers the bug where ``crew_result.output`` (surfaced as
``crew_summary['final_output']``) is a list/dict rather than a string, which
made ``"\\n".join(prompt_parts)`` raise
``TypeError: sequence item N: expected str instance, list found``.
"""
import re
from datetime import date

import pytest

from parrot.bots.flows.crew import AgentCrew
from parrot.bots.prompts.builder import PromptBuilder


# Gemini function-name contract: start with a letter/underscore, then only
# [a-zA-Z0-9_.:-], max length 128.
_GEMINI_NAME_RE = re.compile(r"[a-zA-Z_][a-zA-Z0-9_.:-]{0,127}\Z")


class _FakeLegacyAgent:
    """Minimal stand-in for a builder-less (legacy template) agent."""

    def __init__(self):
        self._prompt_builder = None
        self.system_prompt = ""


class _FakeBuilderAgent:
    """Minimal stand-in for a composable-builder agent (crew default)."""

    def __init__(self):
        self._prompt_builder = PromptBuilder.agent()
        self.system_prompt = ""


class TestApplyDefinitionPrompt:
    """The definition's system_prompt + a current-date block must reach the
    rendered prompt. Regression for crew agents ignoring their custom prompt
    (builder path) and never knowing the current year.
    """

    def test_temporal_text_has_current_year(self):
        text = AgentCrew._temporal_grounding_text()
        assert str(date.today().year) in text
        assert date.today().isoformat() in text

    def test_builder_agent_gets_identity_and_temporal_layers(self):
        agent = _FakeBuilderAgent()
        AgentCrew._apply_definition_prompt(agent, "You compare competitors.")
        identity = agent._prompt_builder.get("identity")
        temporal = agent._prompt_builder.get("temporal_context")
        assert identity is not None
        assert "You compare competitors." in identity.template
        assert temporal is not None
        assert str(date.today().year) in temporal.template

    def test_builder_agent_temporal_only_without_system_prompt(self):
        agent = _FakeBuilderAgent()
        AgentCrew._apply_definition_prompt(agent, None)
        # Identity is left as the canned default layer; temporal is still added.
        assert agent._prompt_builder.get("temporal_context") is not None

    def test_legacy_agent_appends_temporal_to_template(self):
        agent = _FakeLegacyAgent()
        AgentCrew._apply_definition_prompt(agent, "You find prices.")
        assert "You find prices." in agent.system_prompt
        assert "temporal_context" in agent.system_prompt
        assert str(date.today().year) in agent.system_prompt

    def test_legacy_agent_temporal_only_without_system_prompt(self):
        agent = _FakeLegacyAgent()
        AgentCrew._apply_definition_prompt(agent, None)
        assert "temporal_context" in agent.system_prompt


class TestSanitizeToolName:
    """Regression for the Gemini 400 INVALID_ARGUMENT on agent-tool names.

    ``ask()`` registers each agent as ``agent_<agent_id>``. When an agent id
    came from the crew builder UI it could contain spaces or symbols, which
    Gemini rejects with::

        GenerateContentRequest.tools[0].function_declarations[N].name:
        Invalid function name.
    """

    def test_valid_name_passthrough(self):
        assert AgentCrew._sanitize_tool_name("agent_valid_name") == "agent_valid_name"

    def test_allowed_symbols_preserved(self):
        # dashes, dots and colons are valid Gemini identifier chars.
        assert (
            AgentCrew._sanitize_tool_name("agent_with-dash.and:colon")
            == "agent_with-dash.and:colon"
        )

    def test_space_replaced(self):
        assert AgentCrew._sanitize_tool_name("agent_Company Research") == "agent_Company_Research"

    @pytest.mark.parametrize(
        "raw",
        [
            "agent_Company Research",
            "agent_news_&_rss",
            "agent_site (news) editor",
            "agent_email@host",
            "agent_naïve/name",
        ],
    )
    def test_output_always_gemini_valid(self, raw):
        assert _GEMINI_NAME_RE.fullmatch(AgentCrew._sanitize_tool_name(raw))

    def test_leading_non_letter_gets_underscore(self):
        out = AgentCrew._sanitize_tool_name("123agent")
        assert out.startswith("_")
        assert _GEMINI_NAME_RE.fullmatch(out)

    def test_length_capped_at_128(self):
        assert len(AgentCrew._sanitize_tool_name("agent_" + "x" * 200)) == 128


def _bare_crew() -> AgentCrew:
    """Return an AgentCrew instance without running its heavy __init__.

    ``_build_ask_user_prompt`` only reads its ``context`` argument and the
    static ``_coerce_prompt_text`` helper, so we bypass construction.
    """
    return object.__new__(AgentCrew)


class TestCoercePromptText:
    def test_str_passthrough(self):
        assert AgentCrew._coerce_prompt_text("hello") == "hello"

    def test_list_joined_with_newlines(self):
        assert AgentCrew._coerce_prompt_text(["a", "b", "c"]) == "a\nb\nc"

    def test_tuple_joined(self):
        assert AgentCrew._coerce_prompt_text(("x", "y")) == "x\ny"

    def test_nested_list(self):
        assert AgentCrew._coerce_prompt_text(["a", ["b", "c"]]) == "a\nb\nc"

    def test_non_string_scalar_stringified(self):
        assert AgentCrew._coerce_prompt_text(42) == "42"


class TestBuildAskUserPrompt:
    def test_list_final_output_does_not_raise(self):
        """A list final_output must not blow up the join (the reported bug)."""
        crew = _bare_crew()
        context = {
            "semantic_matches": [],
            "crew_summary": {"final_output": ["sic code 5731", "Best Buy Co."]},
        }
        prompt = crew._build_ask_user_prompt("sic code of best buy?", context)
        assert isinstance(prompt, str)
        assert "sic code 5731" in prompt
        assert "Best Buy Co." in prompt
        assert "# Final Crew Output" in prompt

    def test_string_final_output_still_works(self):
        crew = _bare_crew()
        context = {
            "semantic_matches": [],
            "crew_summary": {"final_output": "plain answer"},
        }
        prompt = crew._build_ask_user_prompt("q?", context)
        assert "plain answer" in prompt

    def test_list_relevant_content_in_semantic_match(self):
        crew = _bare_crew()
        context = {
            "semantic_matches": [
                {
                    "agent_name": "Researcher",
                    "similarity_score": 0.9,
                    "task_executed": "lookup",
                    "execution_time": 1.5,
                    "relevant_content": ["line one", "line two"],
                }
            ],
            "crew_summary": {},
        }
        prompt = crew._build_ask_user_prompt("q?", context)
        assert isinstance(prompt, str)
        assert "line one" in prompt
        assert "line two" in prompt
