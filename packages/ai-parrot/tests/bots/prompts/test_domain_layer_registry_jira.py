"""Tests for Jira domain layer registry (FEAT-138 TASK-946)."""
import pytest
from parrot.bots.prompts.domain_layers import (
    JIRA_WORKFLOW_LAYER,
    JIRA_GROUNDING_LAYER,
    STRICT_GROUNDING_LAYER,
    get_domain_layer,
)


def test_jira_workflow_layer_resolves():
    assert get_domain_layer("jira_workflow") is JIRA_WORKFLOW_LAYER


def test_jira_grounding_layer_resolves():
    assert get_domain_layer("jira_grounding") is JIRA_GROUNDING_LAYER


def test_existing_layers_still_resolve():
    # Regression: new entries must not displace existing ones.
    assert get_domain_layer("strict_grounding") is STRICT_GROUNDING_LAYER
    for name in (
        "dataframe_context",
        "sql_dialect",
        "company_context",
        "crew_context",
        "knowledge_scope",
        "rag_grounding",
    ):
        assert get_domain_layer(name) is not None


def test_unknown_layer_raises():
    with pytest.raises(KeyError):
        get_domain_layer("not_a_layer")
