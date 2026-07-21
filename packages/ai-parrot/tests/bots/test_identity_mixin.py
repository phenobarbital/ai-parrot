"""Unit tests for IdentityMixin (FEAT-321).

Mirrors the pattern used by test_abstractbot_integration.py: extract the
REAL, unbound AbstractBot._configure_prompt_builder / _build_prompt methods
and mix them into a minimal fake base class, so IdentityMixin is exercised
against the actual framework logic it delegates to (via super()) rather
than a hand-rolled stand-in.
"""
import sys
from unittest.mock import MagicMock

import pytest

from parrot.bots.mixins import IdentityMixin
from parrot.bots.prompts.builder import PromptBuilder
from parrot.bots.prompts.layers import PromptLayer, RenderPhase
from parrot.bots.prompts.presets import get_preset

_RealAbstractBot = sys.modules["parrot.bots.abstract"].AbstractBot
_configure_prompt_builder = _RealAbstractBot._configure_prompt_builder
_build_prompt = _RealAbstractBot._build_prompt

DEFAULT_ROLE = "helpful AI assistant"


class FakeBase:
    """Minimal stand-in exposing the AbstractBot seams IdentityMixin needs."""

    _configure_prompt_builder = _configure_prompt_builder
    _build_prompt = _build_prompt

    role = None
    goal = None
    capabilities = None
    backstory = None
    rationale = None

    def __init__(self, *, name="TestBot", prompt_preset=None, prompt_builder=None, **kwargs):
        self.name = name
        self.role = kwargs.get("role") or getattr(self, "role", None) or DEFAULT_ROLE
        self.goal = kwargs.get("goal") or getattr(self, "goal", None) or ""
        self.capabilities = (
            kwargs.get("capabilities") or getattr(self, "capabilities", None) or ""
        )
        self.backstory = kwargs.get("backstory") or getattr(self, "backstory", None) or ""
        self.rationale = kwargs.get("rationale") or getattr(self, "rationale", None) or ""
        self.pre_instructions = kwargs.get("pre_instructions", [])
        self.enable_tools = kwargs.get("enable_tools", False)
        self.tool_manager = MagicMock()
        self.tool_manager.tool_count.return_value = 0
        self.logger = MagicMock()
        self._prompt_caching = False
        self._prompt_builder = None
        if prompt_builder is not None:
            self._prompt_builder = prompt_builder
        elif prompt_preset:
            self._prompt_builder = get_preset(prompt_preset)


@pytest.fixture
def identity_dir(tmp_path):
    for f, text in {
        "role": "a test analyst",
        "goal": "answer questions",
        "capabilities": "- do X\n- do Y",
        "backstory": "context here",
        "rationale": "be concise",
    }.items():
        (tmp_path / f"{f}.md").write_text(text, encoding="utf-8")
    return tmp_path


def make_agent_class(identity_dir_path, enable=True, role_class_attr=None):
    attrs = {"enable_identity": enable, "identity_dir": identity_dir_path}
    if role_class_attr is not None:
        attrs["role"] = role_class_attr
    return type("Agent", (IdentityMixin, FakeBase), attrs)


class TestFieldInjection:
    def test_mixin_injects_fields(self, identity_dir):
        Agent = make_agent_class(identity_dir)
        agent = Agent(prompt_preset="default")
        assert agent.role == "a test analyst"
        assert agent.goal == "answer questions"
        assert agent.capabilities == "- do X\n- do Y"
        assert agent.backstory == "context here"
        assert agent.rationale == "be concise"

    def test_kwarg_wins_over_file(self, identity_dir):
        Agent = make_agent_class(identity_dir)
        agent = Agent(prompt_preset="default", role="explicit kwarg role")
        assert agent.role == "explicit kwarg role"
        # Non-overridden fields still come from the file.
        assert agent.goal == "answer questions"

    def test_file_beats_class_attribute(self, identity_dir):
        Agent = make_agent_class(identity_dir, role_class_attr="class-level default")
        agent = Agent(prompt_preset="default")
        assert agent.role == "a test analyst"

    def test_disabled_flag_inert(self, identity_dir):
        Agent = make_agent_class(identity_dir, enable=False)
        agent = Agent(prompt_preset="default")
        assert agent.role == DEFAULT_ROLE
        assert agent._identity_fields is None
        assert not hasattr(agent, "_identity_init_snapshot")


class TestHotReload:
    @pytest.mark.asyncio
    async def test_reload_on_mtime_change(self, identity_dir):
        Agent = make_agent_class(identity_dir)
        agent = Agent(prompt_preset="default")
        await agent._configure_identity()
        first = agent._build_prompt()
        assert "context here" in first

        import os
        f = identity_dir / "backstory.md"
        f.write_text("brand new backstory content", encoding="utf-8")
        os.utime(f, (f.stat().st_atime, f.stat().st_mtime + 5))

        second = agent._build_prompt()
        assert "brand new backstory content" in second
        assert "context here" not in second

    @pytest.mark.asyncio
    async def test_no_reload_when_unchanged(self, identity_dir):
        Agent = make_agent_class(identity_dir)
        agent = Agent(prompt_preset="default")
        await agent._configure_identity()
        agent._build_prompt()
        builder_after_first = agent._prompt_builder
        agent._build_prompt()
        assert agent._prompt_builder is builder_after_first

    @pytest.mark.asyncio
    async def test_swap_carries_transient_layers(self, identity_dir):
        Agent = make_agent_class(identity_dir)
        agent = Agent(prompt_preset="default")
        await agent._configure_identity()

        skill_layer = PromptLayer(
            name="skill_active",
            priority=90,
            template="SKILL BODY",
            phase=RenderPhase.REQUEST,
        )
        agent._prompt_builder.add(skill_layer)

        import os
        f = identity_dir / "backstory.md"
        f.write_text("updated for swap test", encoding="utf-8")
        os.utime(f, (f.stat().st_atime, f.stat().st_mtime + 5))

        agent._build_prompt()
        assert agent._prompt_builder.get("skill_active") is not None

    @pytest.mark.asyncio
    async def test_dynamic_values_resolve(self, identity_dir):
        (identity_dir / "backstory.md").write_text(
            "Today is $current_date", encoding="utf-8"
        )
        Agent = make_agent_class(identity_dir)
        agent = Agent(prompt_preset="default")
        await agent._configure_identity()
        prompt = agent._build_prompt()
        assert "$current_date" not in prompt


class TestNonAdopter:
    def test_non_adopter_prompt_unchanged(self, identity_dir):
        class PlainAgent(FakeBase):
            pass

        class MixedAgentDisabled(IdentityMixin, FakeBase):
            enable_identity = False

        common_kwargs = dict(
            prompt_builder=PromptBuilder.default(),
            role="helpful assistant",
            goal="help users",
            backstory="Expert in AI",
            rationale="Be concise",
        )
        plain = PlainAgent(**common_kwargs)
        mixed = MixedAgentDisabled(**common_kwargs)

        plain_prompt = plain._build_prompt()
        mixed_prompt = mixed._build_prompt()
        assert plain_prompt == mixed_prompt
        assert "<capabilities>" not in plain_prompt
        assert "<capabilities>" not in mixed_prompt
