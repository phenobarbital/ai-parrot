"""Unit tests for parrot.flows.dev_loop.nodes.deployment_handoff (TASK-884)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.flows.dev_loop import (
    BugBrief,
    DevelopmentOutput,
    FlowtaskCriterion,
    QAReport,
    ResearchOutput,
)
from parrot.flows.dev_loop.nodes.deployment_handoff import (
    DeploymentHandoffNode,
)


@pytest.fixture
def ctx() -> dict:
    return {
        "run_id": "r1",
        "research_output": ResearchOutput(
            jira_issue_key="OPS-1",
            spec_path="sdd/specs/x.spec.md",
            feat_id="FEAT-130",
            branch_name="feat-130-fix",
            worktree_path="/tmp/feat-130-fix",
            log_excerpts=[],
        ),
        "bug_brief": BugBrief(
            summary="customer sync drops the last row",
            affected_component="etl/customers/sync.yaml",
            log_sources=[],
            acceptance_criteria=[
                FlowtaskCriterion(name="run", task_path="x.yaml"),
            ],
            escalation_assignee="a",
            reporter="b",
        ),
        "development_output": DevelopmentOutput(
            files_changed=["a.py"],
            commit_shas=["abc"],
            summary="done",
        ),
        "qa_report": QAReport(
            passed=True, criterion_results=[], lint_passed=True
        ),
    }


@pytest.fixture
def jira() -> MagicMock:
    j = MagicMock()
    j.jira_transition_issue = AsyncMock(return_value={"ok": True})
    j.jira_add_comment = AsyncMock(return_value={"id": "c1"})
    return j


def _build_node(jira, **kwargs) -> DeploymentHandoffNode:
    return DeploymentHandoffNode(jira_toolkit=jira, **kwargs)


# ---------------------------------------------------------------------------
# git push helper — patched in every test
# ---------------------------------------------------------------------------


async def _success_push(self, branch, cwd):
    return None


async def _failing_push(self, branch, cwd):
    raise RuntimeError("git push: permission denied")


# ---------------------------------------------------------------------------
# Happy path with retry-once
# ---------------------------------------------------------------------------


class TestRetriesPrOnce:
    @pytest.mark.asyncio
    async def test_first_pr_502_then_succeeds(self, ctx, jira, monkeypatch):
        monkeypatch.setattr(
            DeploymentHandoffNode, "_push_branch", _success_push
        )
        # Force HTTP fallback (no gh).
        monkeypatch.setattr(
            "parrot.flows.dev_loop.nodes.deployment_handoff.shutil.which",
            lambda *a, **kw: None,
        )

        calls: list[int] = []

        async def _fake_pr(self, branch, title, body):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("502 bad gateway")
            return "https://github.com/x/y/pull/1"

        monkeypatch.setattr(
            DeploymentHandoffNode, "_create_pr_via_rest", _fake_pr
        )
        # Speed up the retry sleep.
        async def _instant_sleep(delay):
            return None

        monkeypatch.setattr(
            "parrot.flows.dev_loop.nodes.deployment_handoff.asyncio.sleep",
            _instant_sleep,
        )

        node = _build_node(jira)
        result = await node.execute(prompt="", ctx=ctx)
        assert result["status"] == "ready_to_deploy"
        assert result["pr_url"] == "https://github.com/x/y/pull/1"
        assert len(calls) == 2
        jira.jira_transition_issue.assert_awaited_once()
        jira.jira_add_comment.assert_awaited_once()


# ---------------------------------------------------------------------------
# Final failure → blocked
# ---------------------------------------------------------------------------


class TestFinalPrFailure:
    @pytest.mark.asyncio
    async def test_pr_fails_twice_marks_blocked(
        self, ctx, jira, monkeypatch
    ):
        monkeypatch.setattr(
            DeploymentHandoffNode, "_push_branch", _success_push
        )
        monkeypatch.setattr(
            "parrot.flows.dev_loop.nodes.deployment_handoff.shutil.which",
            lambda *a, **kw: None,
        )

        async def _always_fail(self, branch, title, body):
            raise RuntimeError("API unavailable")

        monkeypatch.setattr(
            DeploymentHandoffNode, "_create_pr_via_rest", _always_fail
        )

        async def _instant_sleep(delay):
            return None

        monkeypatch.setattr(
            "parrot.flows.dev_loop.nodes.deployment_handoff.asyncio.sleep",
            _instant_sleep,
        )

        node = _build_node(jira)
        result = await node.execute(prompt="", ctx=ctx)
        assert result["status"] == "blocked"
        # First call -> Deployment Blocked transition (jira call inside
        # _mark_blocked); second jira_add_comment also called there.
        jira.jira_transition_issue.assert_awaited_once()
        jira.jira_add_comment.assert_awaited_once()


# ---------------------------------------------------------------------------
# Push failure short-circuits
# ---------------------------------------------------------------------------


class TestPushFailureBlocks:
    @pytest.mark.asyncio
    async def test_push_failure_marks_blocked_without_pr(
        self, ctx, jira, monkeypatch
    ):
        monkeypatch.setattr(
            DeploymentHandoffNode, "_push_branch", _failing_push
        )

        async def _should_not_be_called(self, branch, title, body):
            raise AssertionError("should not be called")

        monkeypatch.setattr(
            DeploymentHandoffNode,
            "_create_pr_via_rest",
            _should_not_be_called,
        )
        node = _build_node(jira)
        result = await node.execute(prompt="", ctx=ctx)
        assert result["status"] == "blocked"
        assert "push" in result["error"]


# ---------------------------------------------------------------------------
# Title / body formatting
# ---------------------------------------------------------------------------


class TestPRBody:
    def test_title_includes_feat_id_and_summary(self, ctx):
        node = _build_node(MagicMock())
        title = node._build_title(
            ctx["bug_brief"], ctx["research_output"]
        )
        assert title.startswith("FEAT-130:")
        assert "customer sync" in title.lower()

    def test_body_includes_spec_and_jira(self, ctx):
        node = _build_node(MagicMock())
        body = node._build_body(
            ctx["research_output"],
            ctx["development_output"],
            ctx["qa_report"],
        )
        assert "OPS-1" in body
        assert "sdd/specs/x.spec.md" in body
