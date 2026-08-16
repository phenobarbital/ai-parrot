"""Tests for wiring WhatIfToolkit into an agent.

Registering six tools is only half the integration: without its usage
instructions the model sees terse docstrings and no hint that
``describe_scenario`` chains into ``add_actions`` and ``simulate``.

Injection used to be attempted through ``agent.add_system_prompt()`` alone,
behind a silent ``hasattr`` guard. PandasAgent does not define that method, so
the instructions were dropped without a word. Worse, the obvious workarounds
do not work either for a builder-driven bot: it renders from PromptLayers and
never reads ``system_prompt_template``. These tests pin each mechanism and the
reporting that tells injection apart from silent failure.
"""
import logging

import pandas as pd
from parrot_tools.whatif_toolkit import (
    WHATIF_PROMPT_LAYER,
    WHATIF_TOOLKIT_SYSTEM_PROMPT,
    inject_whatif_system_prompt,
    integrate_whatif_toolkit,
)


class ExplicitApiAgent:
    """Agent exposing a dedicated add_system_prompt() hook."""

    def __init__(self) -> None:
        self.added: list = []

    def add_system_prompt(self, prompt: str) -> None:
        """Record the injected prompt."""
        self.added.append(prompt)


class FakeBuilder:
    """Duck-typed stand-in for PromptBuilder."""

    def __init__(self) -> None:
        self.layers: list = []

    @property
    def layer_names(self) -> list:
        """Names of the layers added so far."""
        return [layer.name for layer in self.layers]

    def add(self, layer) -> "FakeBuilder":
        """Append a layer."""
        self.layers.append(layer)
        return self


class BuilderAgent:
    """Agent that renders from a composable prompt builder."""

    def __init__(self) -> None:
        self.prompt_builder = FakeBuilder()
        # Present but unused: a builder-driven bot never renders from it.
        self.system_prompt_template = "BASE"


class LegacyAgent:
    """Agent with only the legacy template."""

    def __init__(self) -> None:
        self.system_prompt_template = "BASE"


class BareAgent:
    """Agent exposing no way to extend its system prompt."""


# ── mechanism selection ──────────────────────────────────────────────────


def test_uses_explicit_api_when_available():
    """A dedicated hook wins over the other mechanisms."""
    agent = ExplicitApiAgent()

    assert inject_whatif_system_prompt(agent) == "add_system_prompt"
    assert agent.added == [WHATIF_TOOLKIT_SYSTEM_PROMPT]


def test_uses_prompt_builder_when_present():
    """A builder-driven agent gets a layer, not a template append."""
    agent = BuilderAgent()

    assert inject_whatif_system_prompt(agent) == "prompt_builder"
    assert agent.prompt_builder.layer_names == [WHATIF_PROMPT_LAYER]
    assert WHATIF_TOOLKIT_SYSTEM_PROMPT in agent.prompt_builder.layers[0].template
    # The legacy template is where a builder-driven bot would NOT look.
    assert agent.system_prompt_template == "BASE"


def test_falls_back_to_legacy_template():
    """Agents without a builder still get the instructions."""
    agent = LegacyAgent()

    assert inject_whatif_system_prompt(agent) == "system_prompt_template"
    assert WHATIF_TOOLKIT_SYSTEM_PROMPT in agent.system_prompt_template
    assert agent.system_prompt_template.startswith("BASE")


def test_reports_failure_instead_of_staying_silent():
    """An agent with no mechanism returns None rather than pretending."""
    assert inject_whatif_system_prompt(BareAgent()) is None


# ── idempotency ──────────────────────────────────────────────────────────


def test_builder_injection_is_idempotent():
    """Integrating twice must not stack duplicate layers."""
    agent = BuilderAgent()

    inject_whatif_system_prompt(agent)
    inject_whatif_system_prompt(agent)

    assert agent.prompt_builder.layer_names == [WHATIF_PROMPT_LAYER]


def test_legacy_injection_is_idempotent():
    """The template must not accumulate copies of the same block."""
    agent = LegacyAgent()

    inject_whatif_system_prompt(agent)
    inject_whatif_system_prompt(agent)

    assert agent.system_prompt_template.count("What-If Scenario Analysis Toolkit") == 1


def test_custom_prompt_is_respected():
    """Callers can inject their own text (e.g. a routing policy)."""
    agent = LegacyAgent()

    inject_whatif_system_prompt(agent, "CUSTOM ROUTING RULE")

    assert "CUSTOM ROUTING RULE" in agent.system_prompt_template


# ── the integration helper ───────────────────────────────────────────────


class ToolManager:
    """Minimal tool manager recording registrations."""

    def __init__(self) -> None:
        self.registered: list = []

    def register(self, tool) -> None:
        """Record a registered tool."""
        self.registered.append(tool)


class HostAgent:
    """Builder-driven agent with a tool manager and a dataset."""

    def __init__(self) -> None:
        self.tool_manager = ToolManager()
        self.prompt_builder = FakeBuilder()
        self.dataframes = {"clients": pd.DataFrame({"a": [1]})}


def test_integrate_registers_tools_and_injects_prompt():
    """The one-call helper must do both halves of the wiring."""
    agent = HostAgent()

    toolkit = integrate_whatif_toolkit(agent)

    names = sorted(tool.name for tool in agent.tool_manager.registered)
    assert names == [
        "add_actions",
        "compare_scenarios",
        "describe_scenario",
        "quick_impact",
        "set_constraints",
        "simulate",
    ]
    assert agent.prompt_builder.layer_names == [WHATIF_PROMPT_LAYER]
    assert toolkit._parent_agent is agent


def test_integrate_warns_when_it_cannot_inject(caplog):
    """A toolkit that looks wired up but is not must say so."""

    class NoPromptAgent:
        """Agent with tools but nowhere to put instructions."""

        def __init__(self) -> None:
            self.tool_manager = ToolManager()

    with caplog.at_level(logging.WARNING):
        integrate_whatif_toolkit(NoPromptAgent())

    assert any(
        "could not inject its system prompt" in record.message
        for record in caplog.records
    )
