"""Shared fixtures for the dev-loop test suite (TASK-888)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.flows.dev_loop import (
    BugBrief,
    FlowtaskCriterion,
    LogSource,
    ResearchOutput,
    ShellCriterion,
)


@pytest.fixture
def sample_bug_brief() -> BugBrief:
    """Canonical happy-path bug brief used across the suite."""
    return BugBrief(
        summary=(
            "Customer sync flowtask drops the last row when the input "
            "has >1000 records"
        ),
        affected_component="etl/customers/sync.yaml",
        log_sources=[
            LogSource(
                kind="cloudwatch",
                locator="/etl/prod/customers",
                time_window_minutes=120,
            )
        ],
        acceptance_criteria=[
            FlowtaskCriterion(
                name="customers-sync-passes",
                task_path="etl/customers/sync.yaml",
                expected_exit_code=0,
            ),
            ShellCriterion(name="lint-clean", command="ruff check ."),
        ],
        escalation_assignee="557058:abc",
        reporter="557058:def",
    )


@pytest.fixture
def sample_research_output() -> ResearchOutput:
    """Canonical research output used by Development / QA / Handoff tests."""
    return ResearchOutput(
        jira_issue_key="OPS-1",
        spec_path="sdd/specs/x.spec.md",
        feat_id="FEAT-130",
        branch_name="feat-130-fix-customer-sync",
        worktree_path="/abs/.claude/worktrees/feat-130-fix-customer-sync",
        log_excerpts=[],
    )


@pytest.fixture
def fake_dispatch_messages():
    """Mimic ``ClaudeAgentClient.ask_stream`` output without the SDK.

    Returns three duck-typed messages: two ``_AssistantMessage``
    fragments concatenating into a valid ``ResearchOutput`` JSON, plus
    a final ``_ResultMessage``. No ``claude_agent_sdk`` import is
    triggered.
    """

    class _AssistantMessage:
        def __init__(self, content):
            self.content = content

    class _TextBlock:
        def __init__(self, text):
            self.text = text

    class _ResultMessage:
        def __init__(self, **kw):
            self.subtype = kw.get("subtype", "success")
            self.num_turns = kw.get("num_turns", 1)
            self.total_cost_usd = kw.get("total_cost_usd", 0.0)
            self.content = []

    return [
        _AssistantMessage(
            content=[
                _TextBlock(
                    text=(
                        '{"jira_issue_key":"OPS-1",'
                        '"spec_path":"sdd/specs/x.spec.md",'
                    )
                )
            ]
        ),
        _AssistantMessage(
            content=[
                _TextBlock(
                    text=(
                        '"feat_id":"FEAT-130",'
                        '"branch_name":"feat-130-fix",'
                        '"worktree_path":'
                        '"/abs/.claude/worktrees/feat-130-fix",'
                        '"log_excerpts":[]}'
                    )
                )
            ]
        ),
        _ResultMessage(),
    ]


@pytest.fixture
def mock_jira():
    """A pre-wired ``JiraToolkit`` mock for node tests."""
    j = MagicMock()
    j.jira_create_issue = AsyncMock(return_value={"key": "OPS-1"})
    j.jira_transition_issue = AsyncMock(return_value={"ok": True})
    j.jira_add_comment = AsyncMock(return_value={"id": "c1"})
    j.jira_assign_issue = AsyncMock(return_value={"ok": True})
    return j


@pytest.fixture
def mock_dispatcher():
    """A pre-wired ``ClaudeCodeDispatcher`` mock for node tests."""
    d = MagicMock()
    d.dispatch = AsyncMock()
    return d
