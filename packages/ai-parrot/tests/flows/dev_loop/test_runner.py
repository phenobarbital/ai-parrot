"""Tests for DevLoopRunner (FLOW_MAX_CONCURRENT_RUNS) and the end-to-end
dev-loop run path on the new AgentsFlow engine (mocked dispatcher/Jira).

Covers spec G5's orchestrator half (run-level semaphore) and the FEAT-132
routing semantics executed for real by the engine's OR-join scheduler:
happy path (failure_handler skipped), QA-failure path (handoff skipped),
and hard-error path (downstream skipped, failure_handler fired via
on_error).
"""

from __future__ import annotations

import asyncio
from typing import Any, List
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.bots.flows.core.result import FlowResult
from parrot.bots.flows.core.types import FlowStatus
from parrot.flows.dev_loop import (
    BugBrief,
    DevLoopRunner,
    QAReport,
    ResearchOutput,
    ShellCriterion,
    WorkBrief,
    build_dev_loop_flow,
)
from parrot.flows.dev_loop.models import DevelopmentOutput
from parrot.flows.dev_loop.nodes.deployment_handoff import (
    DeploymentHandoffNode,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def brief() -> BugBrief:
    return BugBrief(
        summary="Customer sync drops the last row",
        affected_component="etl/customers/sync.yaml",
        log_sources=[],
        acceptance_criteria=[
            ShellCriterion(name="lint", command="ruff check ."),
        ],
        escalation_assignee="557058:abc",
        reporter="557058:def",
    )


def _research_output(tmp_path) -> ResearchOutput:
    return ResearchOutput(
        jira_issue_key="OPS-1",
        spec_path="sdd/specs/x.spec.md",
        feat_id="FEAT-130",
        branch_name="feat-130-fix",
        worktree_path=str(tmp_path / "feat-130-fix"),
        log_excerpts=[],
    )


@pytest.fixture
def mock_jira():
    j = MagicMock()
    j.jira_create_issue = AsyncMock(return_value={"key": "OPS-1"})
    j.jira_get_issue = AsyncMock(return_value={"status": "error"})
    j.jira_search_issues = AsyncMock(return_value={"status": "empty"})
    j.jira_transition_issue = AsyncMock(return_value={"ok": True})
    j.jira_transition_to = AsyncMock(return_value={"ok": True})
    j.jira_add_comment = AsyncMock(return_value={"id": "c1"})
    j.jira_assign_issue = AsyncMock(return_value={"ok": True})
    return j


def _dispatcher_returning(research_out, qa_passed: bool = True, fail_node: str = ""):
    """Dispatcher mock that answers per output_model; optionally raises."""

    async def dispatch(*, brief, profile, output_model, run_id, node_id, cwd, session_host=None):
        if fail_node and node_id == fail_node:
            raise RuntimeError(f"dispatch blew up in {node_id}")
        if output_model is ResearchOutput:
            return research_out
        if output_model is DevelopmentOutput:
            return DevelopmentOutput(
                files_changed=["x.py"],
                commit_shas=["abc123"],
                summary="implemented the fix",
            )
        if output_model is QAReport:
            return QAReport(
                passed=qa_passed, criterion_results=[], lint_passed=qa_passed
            )
        raise AssertionError(f"unexpected output_model {output_model}")

    d = MagicMock()
    d.dispatch = AsyncMock(side_effect=dispatch)
    return d


@pytest.fixture
def patch_handoff(monkeypatch):
    """Neutralize git push / PR creation at class level (frozen models)."""
    monkeypatch.setattr(
        DeploymentHandoffNode, "_push_branch", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        DeploymentHandoffNode,
        "_create_pr",
        AsyncMock(return_value="https://github.com/x/y/pull/1"),
    )


@pytest.fixture
def patch_worktree_base(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "parrot.flows.dev_loop.nodes.research.conf.WORKTREE_BASE_PATH",
        str(tmp_path),
    )
    return tmp_path


def _build_flow(dispatcher, jira):
    return build_dev_loop_flow(
        dispatcher=dispatcher,
        jira_toolkit=jira,
        log_toolkits={},
        redis_url="redis://localhost:6399/9",  # never connected in tests
        publish_flow_events=False,
    )


# ---------------------------------------------------------------------------
# End-to-end paths on the real engine
# ---------------------------------------------------------------------------


class TestEndToEndPaths:
    @pytest.mark.asyncio
    async def test_happy_path_skips_failure_handler(
        self, brief, mock_jira, patch_handoff, patch_worktree_base
    ):
        dispatcher = _dispatcher_returning(_research_output(patch_worktree_base))
        flow = _build_flow(dispatcher, mock_jira)
        runner = DevLoopRunner(flow, max_concurrent_runs=2)

        result: FlowResult = await runner.run(brief, run_id="run-happy")

        assert result.status == FlowStatus.COMPLETED
        executed = set(result.responses)
        # FEAT-250 G7: the success path now terminates at the close node.
        assert executed == {
            "intent_classifier", "bug_intake", "research",
            "development", "qa", "deployment_handoff", "close",
        }
        assert "failure_handler" not in executed
        # The handoff result (PR info) lives in the per-node responses; the
        # flow's terminal is now the close node.
        handoff_resp = result.responses["deployment_handoff"]
        assert handoff_resp["status"] == "ready_to_deploy"
        assert handoff_resp["pr_url"] == "https://github.com/x/y/pull/1"
        assert result.responses["close"]["status"] == "closed"
        # Jira moved to Ready to Deploy (via the workflow-path walker).
        mock_jira.jira_transition_to.assert_awaited()

    @pytest.mark.asyncio
    async def test_qa_failure_routes_to_failure_handler(
        self, brief, mock_jira, patch_handoff, patch_worktree_base
    ):
        dispatcher = _dispatcher_returning(
            _research_output(patch_worktree_base), qa_passed=False
        )
        flow = _build_flow(dispatcher, mock_jira)
        runner = DevLoopRunner(flow, max_concurrent_runs=2)

        result = await runner.run(brief, run_id="run-qafail")

        executed = set(result.responses)
        assert "failure_handler" in executed
        assert "deployment_handoff" not in executed
        assert "close" not in executed
        assert result.responses["failure_handler"]["status"] == "escalated"
        # FailureHandler derived the qa_failed context from shared state.
        bodies = [
            c.kwargs["body"]
            for c in mock_jira.jira_add_comment.call_args_list
        ]
        assert any("QA failed" in b for b in bodies)

    @pytest.mark.asyncio
    async def test_hard_error_routes_to_failure_handler(
        self, brief, mock_jira, patch_handoff, patch_worktree_base
    ):
        dispatcher = _dispatcher_returning(
            _research_output(patch_worktree_base), fail_node="development"
        )
        flow = _build_flow(dispatcher, mock_jira)
        runner = DevLoopRunner(flow, max_concurrent_runs=2)

        result = await runner.run(brief, run_id="run-deverr")

        executed = set(result.responses)
        assert "failure_handler" in executed
        assert "qa" not in executed
        assert "deployment_handoff" not in executed
        assert "development" in result.errors
        bodies = [
            c.kwargs["body"]
            for c in mock_jira.jira_add_comment.call_args_list
        ]
        assert any("development" in b and "RuntimeError" in b for b in bodies)

    @pytest.mark.asyncio
    async def test_non_bug_kind_skips_bug_intake(
        self, mock_jira, patch_handoff, patch_worktree_base
    ):
        enhancement = WorkBrief(
            kind="enhancement",
            summary="Add dark mode",
            affected_component="frontend/reporting",
            acceptance_criteria=[
                ShellCriterion(name="lint", command="ruff check .")
            ],
            escalation_assignee="oncall@example.com",
            reporter="reporter@example.com",
        )
        dispatcher = _dispatcher_returning(_research_output(patch_worktree_base))
        flow = _build_flow(dispatcher, mock_jira)
        runner = DevLoopRunner(flow, max_concurrent_runs=2)

        result = await runner.run(enhancement, run_id="run-enh")

        executed = set(result.responses)
        assert "bug_intake" not in executed
        assert "research" in executed
        assert result.status == FlowStatus.COMPLETED


# ---------------------------------------------------------------------------
# Runner semantics
# ---------------------------------------------------------------------------


class _SlowFlow:
    """run_flow stub that records concurrency and blocks on an event."""

    def __init__(self) -> None:
        self.concurrent = 0
        self.max_seen = 0
        self.release = asyncio.Event()

    async def run_flow(self, ctx, **kwargs) -> FlowResult:
        self.concurrent += 1
        self.max_seen = max(self.max_seen, self.concurrent)
        try:
            await self.release.wait()
        finally:
            self.concurrent -= 1
        return FlowResult(output=ctx.shared_data["run_id"], status=FlowStatus.COMPLETED)


class TestRunnerSemaphore:
    @pytest.mark.asyncio
    async def test_caps_concurrent_runs(self, brief):
        slow = _SlowFlow()
        runner = DevLoopRunner(slow, max_concurrent_runs=2)  # type: ignore[arg-type]

        tasks: List[asyncio.Task] = [
            asyncio.create_task(runner.run(brief, run_id=f"r{i}"))
            for i in range(4)
        ]
        await asyncio.sleep(0.05)
        assert slow.max_seen == 2
        assert len(runner.active_runs) == 2

        slow.release.set()
        results = await asyncio.gather(*tasks)
        assert {r.output for r in results} == {"r0", "r1", "r2", "r3"}
        assert slow.max_seen == 2
        assert runner.active_runs == set()

    @pytest.mark.asyncio
    async def test_default_cap_comes_from_conf(self):
        from parrot import conf

        runner = DevLoopRunner(MagicMock())
        assert runner.max_concurrent_runs == conf.FLOW_MAX_CONCURRENT_RUNS

    @pytest.mark.asyncio
    async def test_mints_run_id_and_seeds_shared_data(self, brief):
        captured: dict[str, Any] = {}

        class _Probe:
            async def run_flow(self, ctx, **kwargs) -> FlowResult:
                captured["ctx"] = ctx
                return FlowResult(output="ok", status=FlowStatus.COMPLETED)

        runner = DevLoopRunner(_Probe())  # type: ignore[arg-type]
        await runner.run(brief)

        ctx = captured["ctx"]
        assert ctx.shared_data["bug_brief"] is brief
        assert ctx.shared_data["work_brief"] is brief
        assert ctx.shared_data["run_id"].startswith("run-")
        assert ctx.initial_task == brief.summary
