"""Tests for JIRA_GROUNDING_LAYER (FEAT-138 TASK-945)."""
from parrot.bots.prompts.domain_layers import JIRA_GROUNDING_LAYER
from parrot.bots.prompts.layers import LayerPriority, PromptLayer, RenderPhase


def test_jira_grounding_layer_metadata():
    assert isinstance(JIRA_GROUNDING_LAYER, PromptLayer)
    assert JIRA_GROUNDING_LAYER.name == "jira_grounding"
    assert JIRA_GROUNDING_LAYER.phase == RenderPhase.CONFIGURE
    assert int(JIRA_GROUNDING_LAYER.priority) == int(LayerPriority.BEHAVIOR) - 5


def test_jira_grounding_layer_contains_sentinel_phrases():
    rendered = JIRA_GROUNDING_LAYER.render({})
    assert "No results found for" in rendered
    assert "Jira lookup failed" in rendered


def test_jira_grounding_layer_load_bearing_rules_in_first_paragraph():
    rendered = JIRA_GROUNDING_LAYER.render({})
    first_paragraph = rendered.split("\n\n", 1)[0].lower()
    assert "fabricate" in first_paragraph or "fabrication" in first_paragraph
    assert "no results found" in first_paragraph
    assert "jira lookup failed" in first_paragraph


def test_jira_grounding_layer_is_english_only():
    rendered = JIRA_GROUNDING_LAYER.render({})
    forbidden = ["No encontré", "Hubo un error", "disculpa", "consultando"]
    for phrase in forbidden:
        assert phrase not in rendered
