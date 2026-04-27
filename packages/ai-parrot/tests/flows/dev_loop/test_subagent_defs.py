"""Unit tests for parrot.flows.dev_loop._subagent_defs (TASK-877)."""

from __future__ import annotations

import pytest

from parrot.flows.dev_loop._subagent_defs import load_subagent_definition


@pytest.mark.parametrize("name", ["sdd-research", "sdd-worker", "sdd-qa"])
def test_load_returns_nonempty_string(name):
    body = load_subagent_definition(name)
    assert isinstance(body, str)
    assert len(body) > 100
    # Frontmatter must be stripped — body cannot start with the YAML fence.
    assert not body.startswith("---")


def test_load_unknown_name_raises():
    with pytest.raises(ValueError):
        load_subagent_definition("sdd-whoknows")


def test_load_research_mentions_jira_and_worktree():
    """Sanity-check that the research body still reflects its mission."""
    body = load_subagent_definition("sdd-research")
    assert "Jira" in body
    assert "worktree" in body.lower()


def test_load_qa_mentions_plan_and_qareport():
    body = load_subagent_definition("sdd-qa")
    assert "plan" in body.lower()
    assert "QAReport" in body
