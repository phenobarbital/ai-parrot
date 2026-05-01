"""Tests for JiraSpecialist PromptBuilder migration (FEAT-138 TASK-947)."""
import inspect
import unittest
from unittest.mock import patch

import pytest

from parrot.bots.jira_specialist import JiraSpecialist
from parrot.bots.prompts import PromptBuilder


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

def _make_specialist(**kwargs):
    """Instantiate a JiraSpecialist with all external side-effects patched."""
    with (
        patch("parrot.bots.jira_specialist.JiraToolkit"),
        patch("parrot.bots.jira_specialist.config") as mc,
        patch("redis.asyncio.from_url"),
    ):
        mc.get.return_value = "dummy"
        mc.getlist.return_value = []
        return JiraSpecialist(**kwargs)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_specialist_has_prompt_builder():
    """JiraSpecialist.__init__ must set prompt_builder to a PromptBuilder."""
    specialist = _make_specialist()
    assert isinstance(specialist.prompt_builder, PromptBuilder)


def test_specialist_layers_include_jira_layers():
    """Both jira_workflow and jira_grounding must be in the layer stack."""
    specialist = _make_specialist()
    names = specialist.prompt_builder.layer_names
    assert "jira_workflow" in names
    assert "jira_grounding" in names


def test_specialist_no_system_prompt_template_class_attr():
    """system_prompt_template must NOT be defined on JiraSpecialist class."""
    assert "system_prompt_template" not in JiraSpecialist.__dict__


def test_jira_specialist_prompt_constant_removed():
    """JIRA_SPECIALIST_PROMPT must no longer exist as a module-level symbol."""
    import parrot.bots.jira_specialist as mod
    assert not hasattr(mod, "JIRA_SPECIALIST_PROMPT")


def test_injection_threshold_preserved():
    """injection_probability_threshold default must remain 0.995."""
    specialist = _make_specialist()
    assert specialist.injection_probability_threshold == pytest.approx(0.995)


def test_subclass_inherits_layers():
    """A bare JiraSpecialist subclass must inherit both Jira layers."""
    class _Sub(JiraSpecialist):
        pass

    with (
        patch("parrot.bots.jira_specialist.JiraToolkit"),
        patch("parrot.bots.jira_specialist.config") as mc,
        patch("redis.asyncio.from_url"),
    ):
        mc.get.return_value = "dummy"
        mc.getlist.return_value = []
        sub = _Sub()

    names = sub.prompt_builder.layer_names
    assert "jira_workflow" in names
    assert "jira_grounding" in names


def test_caller_can_override_builder():
    """A caller passing prompt_builder= must use their own builder, not the default."""
    custom_builder = PromptBuilder.default()

    with (
        patch("parrot.bots.jira_specialist.JiraToolkit"),
        patch("parrot.bots.jira_specialist.config") as mc,
        patch("redis.asyncio.from_url"),
    ):
        mc.get.return_value = "dummy"
        mc.getlist.return_value = []
        specialist = JiraSpecialist(prompt_builder=custom_builder)

    assert specialist.prompt_builder is custom_builder
