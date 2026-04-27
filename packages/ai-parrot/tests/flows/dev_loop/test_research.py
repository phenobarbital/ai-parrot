"""Unit tests for parrot.flows.dev_loop.nodes.research (TASK-881)."""

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
from parrot.flows.dev_loop.nodes.research import ResearchNode


@pytest.fixture
def good_brief() -> BugBrief:
    return BugBrief(
        summary="customer sync drops the last row",
        affected_component="etl/customers/sync.yaml",
        log_sources=[],
        acceptance_criteria=[
            FlowtaskCriterion(
                name="run", task_path="etl/customers/sync.yaml"
            ),
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


@pytest.fixture
def node(research_out_fixture, monkeypatch, tmp_path):
    # Pin WORKTREE_BASE_PATH to a tmp dir so the duplicate-worktree
    # safety check has a stable target.
    monkeypatch.setattr(
        "parrot.flows.dev_loop.nodes.research.conf.WORKTREE_BASE_PATH",
        str(tmp_path),
    )

    jira = MagicMock()
    jira.jira_create_issue = AsyncMock(return_value={"key": "OPS-1"})

    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(return_value=research_out_fixture)

    return ResearchNode(
        dispatcher=dispatcher,
        jira_toolkit=jira,
        log_toolkits={
            "cloudwatch": AsyncMock(),
            "elasticsearch": AsyncMock(),
        },
    )


class TestExecutionOrder:
    @pytest.mark.asyncio
    async def test_creates_jira_then_dispatches(self, node, good_brief):
        call_order = []

        async def _jira(**_kwargs):
            call_order.append("jira")
            return {"key": "OPS-1"}

        async def _dispatch(**_kwargs):
            call_order.append("dispatch")
            return ResearchOutput(
                jira_issue_key="OPS-1",
                spec_path="x",
                feat_id="FEAT-1",
                branch_name="feat-1-some-novel-slug",
                worktree_path="/tmp/feat-1-some-novel-slug",
            )

        node._jira.jira_create_issue = AsyncMock(side_effect=_jira)
        node._dispatcher.dispatch = AsyncMock(side_effect=_dispatch)

        await node.execute(
            prompt="",
            ctx={"run_id": "r1", "bug_brief": good_brief},
        )
        assert call_order == ["jira", "dispatch"]


class TestReturnValue:
    @pytest.mark.asyncio
    async def test_returns_research_output(self, node, good_brief, tmp_path):
        # Override branch_name so the duplicate-worktree check passes
        node._dispatcher.dispatch = AsyncMock(
            return_value=ResearchOutput(
                jira_issue_key="OPS-2",
                spec_path="sdd/specs/x.spec.md",
                feat_id="FEAT-130",
                branch_name="feat-130-novel-branch",
                worktree_path=str(tmp_path / "feat-130-novel-branch"),
                log_excerpts=[],
            )
        )
        result = await node.execute(
            prompt="",
            ctx={"run_id": "r1", "bug_brief": good_brief},
        )
        assert isinstance(result, ResearchOutput)
        assert result.feat_id == "FEAT-130"


class TestDuplicateWorktree:
    @pytest.mark.asyncio
    async def test_existing_worktree_raises(
        self, node, good_brief, tmp_path
    ):
        # Pre-create the directory the dispatcher's output points at.
        existing = tmp_path / "feat-130-fix-customer-sync"
        existing.mkdir(parents=True)
        with pytest.raises(RuntimeError, match="already exists"):
            await node.execute(
                prompt="",
                ctx={"run_id": "r1", "bug_brief": good_brief},
            )


class TestDispatcherErrorPropagates:
    @pytest.mark.asyncio
    async def test_validation_error_propagates(self, node, good_brief):
        from parrot.flows.dev_loop import DispatchOutputValidationError

        node._dispatcher.dispatch = AsyncMock(
            side_effect=DispatchOutputValidationError(
                "bad payload", raw_payload="{}"
            )
        )
        with pytest.raises(DispatchOutputValidationError):
            await node.execute(
                prompt="",
                ctx={"run_id": "r1", "bug_brief": good_brief},
            )
