"""Unit tests for parrot.flows.dev_loop._subagent_defs (TASK-877)."""

from __future__ import annotations

import pytest

from parrot.flows.dev_loop._subagent_defs import load_subagent_definition
from parrot.flows.dev_loop.models import (
    ClaudeCodeDispatchProfile,
    CodexCodeDispatchProfile,
    GeminiCodeDispatchProfile,
    GoogleCodingDispatchProfile,
    LLMCodeDispatchProfile,
)


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


def test_valid_names_include_sdd_coder():
    body = load_subagent_definition("sdd-coder")
    assert "DevelopmentOutput" in body and "CARDINAL RULES" in body
    assert "writer_generate" not in body and "Completion Note" not in body


def test_sdd_coder_prompt_forbids_sdd_dir():
    body = load_subagent_definition("sdd-coder")
    forbidden = body.split("## Forbidden", 1)[1].split("## ", 1)[0]
    assert "sdd/" in forbidden


@pytest.mark.parametrize(
    "cls",
    [
        LLMCodeDispatchProfile,
        GeminiCodeDispatchProfile,
        CodexCodeDispatchProfile,
        ClaudeCodeDispatchProfile,
        GoogleCodingDispatchProfile,
    ],
)
def test_subagent_literals_accept_sdd_coder(cls):
    assert cls(subagent="sdd-coder").subagent == "sdd-coder"
    assert cls().subagent == "sdd-worker"


def test_sdd_coder_repo_twin_frontmatter():
    from pathlib import Path

    agents_dir = None
    for parent in Path(__file__).resolve().parents:
        candidate = parent / ".claude" / "agents"
        if candidate.is_dir():
            agents_dir = candidate
            break
    if agents_dir is None:
        pytest.skip(
            "`.claude/agents/` not found relative to this test file — "
            "running against an installed package, not the repo checkout."
        )
    text = (agents_dir / "sdd-coder.md").read_text(encoding="utf-8")
    head = text.split("---", 2)[1]
    assert "model: haiku" in head and "Agent" not in head.split("tools:", 1)[1].splitlines()[0]
