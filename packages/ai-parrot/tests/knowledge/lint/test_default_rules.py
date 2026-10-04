"""Tests for the default lint rule pack selection (TASK-4019)."""

from parrot.knowledge.lint.models import LintOptions
from parrot.knowledge.lint.packs import default_rules


def test_default_rules_no_llm() -> None:
    """Default selection includes deterministic rules but excludes the LLM rule."""
    ids = {rule.rule_id for rule in default_rules(LintOptions())}

    assert "broken-link" in ids
    assert "asymmetric-related" in ids
    assert "contradiction-llm" not in ids
