"""Tests for JIRA_WORKFLOW_LAYER (FEAT-138 TASK-944)."""
import pytest
from parrot.bots.prompts.domain_layers import JIRA_WORKFLOW_LAYER
from parrot.bots.prompts.layers import LayerPriority, PromptLayer, RenderPhase


def test_jira_workflow_layer_metadata():
    assert isinstance(JIRA_WORKFLOW_LAYER, PromptLayer)
    assert JIRA_WORKFLOW_LAYER.name == "jira_workflow"
    assert JIRA_WORKFLOW_LAYER.phase == RenderPhase.CONFIGURE
    assert int(JIRA_WORKFLOW_LAYER.priority) > int(LayerPriority.PRE_INSTRUCTIONS)
    assert int(JIRA_WORKFLOW_LAYER.priority) < int(LayerPriority.SECURITY)


def test_jira_workflow_layer_renders():
    rendered = JIRA_WORKFLOW_LAYER.render({})
    assert rendered is not None
    assert "<jira_workflow>" in rendered
    assert "</jira_workflow>" in rendered


@pytest.mark.parametrize("section_keyword", [
    "default posture",
    "fresh-turn",
    "cancellation",
    "mandatory human",
    "daily standup",
    "mid-day",
    "assignment intake",
    "end-of-day",
    "escalation",
])
def test_jira_workflow_layer_covers_section(section_keyword):
    rendered = JIRA_WORKFLOW_LAYER.render({}).lower()
    assert section_keyword in rendered, (
        f"Section '{section_keyword}' missing from JIRA_WORKFLOW_LAYER"
    )


def test_jira_workflow_layer_is_english_only():
    rendered = JIRA_WORKFLOW_LAYER.render({})
    forbidden = [
        "Operación",
        "Sin respuesta",
        "¿Aceptas",
        "Mil disculpas",
        "No encontré",
        "Hubo un error consultando",
    ]
    for phrase in forbidden:
        assert phrase not in rendered, f"non-English / sentinel leak: {phrase!r}"
