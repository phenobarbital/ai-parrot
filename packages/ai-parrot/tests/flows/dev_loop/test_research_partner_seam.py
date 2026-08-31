"""Unit tests for the ResearchNode <-> ComplementaryResearchCoordinator seam
(FEAT-482 Module 5).

Mirrors ``test_research.py``'s fixture shape (mocked Jira toolkit +
mocked dispatcher, no real Jira/Claude calls) plus a scripted fake
coordinator. Symmetrical to ``test_ideation_partner_seam.py`` (D1: one
shared mechanism, not a fork).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from parrot.flows.dev_flow.research_partner import (
    ComplementaryFindings,
    ResearchFindings,
)
from parrot.flows.dev_loop import (
    BugBrief,
    FlowtaskCriterion,
    ResearchOutput,
    ShellCriterion,
)
from parrot.flows.dev_loop.nodes.research import ResearchNode


class _FakeCoordinator:
    """Stand-in for ComplementaryResearchCoordinator — never raises."""

    def __init__(self, result: ComplementaryFindings | None = None):
        self._result = result
        self.calls: list[dict[str, Any]] = []

    async def research(self, **kwargs: Any) -> ComplementaryFindings | None:
        self.calls.append(kwargs)
        return self._result


def _findings(rendered: str = "# The partner found something relevant"):
    return ComplementaryFindings(
        backend="gpt",
        model="gpt-5.6-sol",
        findings=ResearchFindings(summary="A relevant precedent exists."),
        document_path="sdd/proposals/ops-1.research.md",
        rendered=rendered,
        duration_ms=42.0,
    )


@pytest.fixture
def good_brief() -> BugBrief:
    return BugBrief(
        summary="customer sync drops the last row",
        affected_component="etl/customers/sync.yaml",
        log_sources=[],
        acceptance_criteria=[
            FlowtaskCriterion(name="run", task_path="etl/customers/sync.yaml"),
            ShellCriterion(name="lint", command="ruff check ."),
        ],
        escalation_assignee="557058:abc",
        reporter="557058:def",
    )


@pytest.fixture
def research_out_fixture(tmp_path) -> ResearchOutput:
    return ResearchOutput(
        jira_issue_key="OPS-1",
        spec_path="sdd/specs/x.spec.md",
        feat_id="FEAT-130",
        branch_name="feat-130-fix-customer-sync",
        worktree_path=str(tmp_path / "feat-130-fix-customer-sync"),
        log_excerpts=[],
    )


def _make_jira() -> MagicMock:
    jira = MagicMock()
    jira.jira_create_issue = AsyncMock(return_value={"key": "OPS-1"})
    jira.jira_add_comment = AsyncMock(return_value={"id": "c1"})
    jira.jira_search_issues = AsyncMock(return_value={"status": "empty"})
    jira.jira_get_issue = AsyncMock(return_value={"status": "error"})
    jira.jira_find_user = AsyncMock(
        return_value={
            "found": True,
            "matches": [
                {"accountId": "557058:resolved", "emailAddress": "reporter@example.com"}
            ],
        }
    )
    return jira


def _make_node(
    research_out_fixture,
    monkeypatch,
    tmp_path,
    *,
    coordinator: _FakeCoordinator | None = None,
) -> tuple[ResearchNode, MagicMock]:
    monkeypatch.setattr(
        "parrot.flows.dev_loop.nodes.research.conf.WORKTREE_BASE_PATH",
        str(tmp_path),
    )
    jira = _make_jira()
    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(return_value=research_out_fixture)
    node = ResearchNode(
        dispatcher=dispatcher,
        jira_toolkit=jira,
        log_toolkits={},
        coordinator=coordinator,
    )
    return node, dispatcher


class TestResearchNodePartnerSeam:
    async def test_unchanged_when_coordinator_none(
        self, good_brief, research_out_fixture, monkeypatch, tmp_path
    ):
        """GUARD: dispatch payload byte-identical (same object!) to pre-feature."""
        node, dispatcher = _make_node(research_out_fixture, monkeypatch, tmp_path)

        await node.execute(ctx={"run_id": "r1", "bug_brief": good_brief})

        sent_brief = dispatcher.dispatch.call_args.kwargs["brief"]
        # No wiki/graph-memory/partner context => no model_copy at all —
        # the exact same brief object reaches the dispatcher.
        assert sent_brief is good_brief

    async def test_findings_reach_dispatch_payload(
        self, good_brief, research_out_fixture, monkeypatch, tmp_path
    ):
        """Injected coordinator's findings appear in the sdd-research payload."""
        coordinator = _FakeCoordinator(result=_findings())
        node, dispatcher = _make_node(
            research_out_fixture, monkeypatch, tmp_path, coordinator=coordinator
        )

        await node.execute(ctx={"run_id": "r1", "bug_brief": good_brief})

        sent_brief = dispatcher.dispatch.call_args.kwargs["brief"]
        assert "## Complementary research findings" in sent_brief.description
        assert "The partner found something relevant" in sent_brief.description
        # The ORIGINAL brief (used for the Jira description) is untouched.
        assert good_brief.description == ""
        # The coordinator saw the resolved Jira issue key as its slug.
        assert len(coordinator.calls) == 1
        assert coordinator.calls[0]["slug"] == "ops-1"

    async def test_jira_created_before_dispatch_still_holds(
        self, good_brief, research_out_fixture, monkeypatch, tmp_path
    ):
        """Existing ordering guarantee is not disturbed by a wired coordinator."""
        coordinator = _FakeCoordinator(result=_findings())
        node, _dispatcher = _make_node(
            research_out_fixture, monkeypatch, tmp_path, coordinator=coordinator
        )
        call_order: list[str] = []

        async def _jira(**_kwargs):
            call_order.append("jira")
            return {"key": "OPS-1"}

        async def _research(**_kwargs):
            call_order.append("partner")
            return coordinator._result

        async def _dispatch(**_kwargs):
            call_order.append("dispatch")
            return research_out_fixture

        node._jira.jira_create_issue = AsyncMock(side_effect=_jira)
        coordinator.research = AsyncMock(side_effect=_research)
        node._dispatcher.dispatch = AsyncMock(side_effect=_dispatch)

        await node.execute(ctx={"run_id": "r1", "bug_brief": good_brief})

        assert call_order == ["jira", "partner", "dispatch"]

    async def test_degraded_partner_does_not_fail_run(
        self, good_brief, research_out_fixture, monkeypatch, tmp_path
    ):
        """Coordinator returns None => research proceeds single-agent."""
        coordinator = _FakeCoordinator(result=None)
        node, dispatcher = _make_node(
            research_out_fixture, monkeypatch, tmp_path, coordinator=coordinator
        )

        result = await node.execute(ctx={"run_id": "r1", "bug_brief": good_brief})

        assert isinstance(result, ResearchOutput)
        sent_brief = dispatcher.dispatch.call_args.kwargs["brief"]
        assert sent_brief is good_brief
        assert len(coordinator.calls) == 1

    async def test_slash_command_allowed_tools_unchanged(
        self, good_brief, research_out_fixture, monkeypatch, tmp_path
    ):
        """SlashCommand allowed-tools list unchanged with a coordinator wired in."""
        coordinator = _FakeCoordinator(result=_findings())
        node, dispatcher = _make_node(
            research_out_fixture, monkeypatch, tmp_path, coordinator=coordinator
        )

        await node.execute(ctx={"run_id": "r1", "bug_brief": good_brief})

        profile = dispatcher.dispatch.call_args.kwargs["profile"]
        assert profile.allowed_tools == ["Read", "Grep", "Glob", "Bash", "Write", "SlashCommand"]
