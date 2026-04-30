"""Unit tests for parrot.flows.dev_loop.nodes.research (TASK-881, TASK-900)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.flows.dev_loop import (
    BugBrief,
    FlowtaskCriterion,
    LogSource,
    ResearchOutput,
    ShellCriterion,
    WorkBrief,
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
    jira.jira_add_comment = AsyncMock(return_value={"id": "c1"})

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


@pytest.fixture
def sample_kwargs() -> dict:
    """Minimal WorkBrief keyword args (no acceptance_criteria)."""
    return {
        "summary": "Customer sync drops the last row when input has >1000 rows",
        "affected_component": "etl/customers/sync.yaml",
        "log_sources": [],
        "escalation_assignee": "oncall@example.com",
        "reporter": "reporter@example.com",
    }


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


# ---------------------------------------------------------------------------
# TASK-900 — issuetype routing + plan-summary comment
# ---------------------------------------------------------------------------


class TestIssueTypeRouting:
    """FEAT-132: jira_create_issue receives the correct issuetype per kind."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("kind, expected", [
        ("bug", "Bug"),
        ("enhancement", "Story"),
        ("new_feature", "New Feature"),
    ])
    async def test_issuetype_per_kind(
        self, node: ResearchNode, sample_kwargs: dict, kind: str, expected: str,
    ):
        """Each work kind maps to the correct Jira issuetype."""
        brief = WorkBrief(
            kind=kind,
            **sample_kwargs,
            acceptance_criteria=[
                ShellCriterion(name="r", command="ruff check ."),
            ],
        )
        node._jira.jira_create_issue = AsyncMock(return_value={"key": "X-1"})
        node._jira.jira_add_comment = AsyncMock(return_value={})
        await node.execute("", {"bug_brief": brief, "run_id": "r1"})
        kwargs = node._jira.jira_create_issue.call_args.kwargs
        assert kwargs["issuetype"] == expected


class TestPlanSummaryOnCreate:
    """FEAT-132: plan-summary comment is posted on the new-ticket path."""

    @pytest.mark.asyncio
    async def test_plan_comment_posted_on_create(
        self, node: ResearchNode, good_brief: BugBrief
    ):
        """When a new ticket is created, a 'Plan for run-' comment is posted."""
        node._jira.jira_search_issues = AsyncMock(return_value={"issues": []})
        node._jira.jira_create_issue = AsyncMock(return_value={"key": "NAV-1"})
        node._jira.jira_add_comment = AsyncMock(return_value={})
        # Stub the plan client so no network call is made.
        fake_response = MagicMock(response="Step 1.\nStep 2.")
        node._plan_client = MagicMock()
        node._plan_client.ask = AsyncMock(return_value=fake_response)
        await node.execute("", {"bug_brief": good_brief, "run_id": "r2"})
        bodies = [
            c.kwargs["body"]
            for c in node._jira.jira_add_comment.call_args_list
        ]
        assert any(b.startswith("Plan for run-r2") for b in bodies)

    @pytest.mark.asyncio
    async def test_plan_comment_body_includes_llm_output(
        self, node: ResearchNode, good_brief: BugBrief
    ):
        """The comment body includes the LLM-generated plan text."""
        node._jira.jira_create_issue = AsyncMock(return_value={"key": "NAV-1"})
        node._jira.jira_add_comment = AsyncMock(return_value={})
        fake_response = MagicMock(response="Fix the ETL pipeline.")
        node._plan_client = MagicMock()
        node._plan_client.ask = AsyncMock(return_value=fake_response)
        await node.execute("", {"bug_brief": good_brief, "run_id": "r2"})
        bodies = [
            c.kwargs["body"]
            for c in node._jira.jira_add_comment.call_args_list
        ]
        plan_bodies = [b for b in bodies if b.startswith("Plan for run-r2")]
        assert plan_bodies
        assert "Fix the ETL pipeline." in plan_bodies[0]


class TestPlanSummaryNotOnReuse:
    """FEAT-132: no plan-summary comment on the reuse (re-trigger) path."""

    @pytest.mark.asyncio
    async def test_no_plan_comment_when_reused(
        self, node: ResearchNode, good_brief: BugBrief
    ):
        """On the reuse path, only the re-triggered comment is posted."""
        brief = good_brief.model_copy(update={"existing_issue_key": "NAV-99"})
        node._jira.jira_get_issue = AsyncMock(return_value={"key": "NAV-99"})
        node._jira.jira_create_issue = AsyncMock(
            side_effect=AssertionError("jira_create_issue must not be called on reuse")
        )
        node._jira.jira_add_comment = AsyncMock(return_value={})
        await node.execute("", {"bug_brief": brief, "run_id": "r3"})
        bodies = [
            c.kwargs["body"]
            for c in node._jira.jira_add_comment.call_args_list
        ]
        # No "Plan for run-" comment on the reuse path.
        assert not any(b.startswith("Plan for run-") for b in bodies)


class TestPlanSummaryFallback:
    """FEAT-132: LLM failure falls back to a deterministic stub."""

    @pytest.mark.asyncio
    async def test_falls_back_to_stub_on_llm_error(
        self, node: ResearchNode, good_brief: BugBrief
    ):
        """When the plan LLM raises, a deterministic stub is posted instead."""
        node._jira.jira_create_issue = AsyncMock(return_value={"key": "NAV-2"})
        node._jira.jira_add_comment = AsyncMock(return_value={})
        node._plan_client = MagicMock()
        node._plan_client.ask = AsyncMock(side_effect=RuntimeError("llm-error"))
        await node.execute("", {"bug_brief": good_brief, "run_id": "r4"})
        bodies = [
            c.kwargs["body"]
            for c in node._jira.jira_add_comment.call_args_list
        ]
        # The comment is still posted; the stub body starts with "Plan for run-".
        assert any("Plan for run-r4" in b for b in bodies)
