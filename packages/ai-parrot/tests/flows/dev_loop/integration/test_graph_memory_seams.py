"""Graph-memory seam integration tests (FEAT-377 TASK-1915).

Drives the REAL ``DevLoopRunner.run()`` / ``build_dev_loop_flow()`` stack
(mocked dispatcher/Jira, no network) to prove the four wired seams:
research-context injection, close/failure write-back, and grounded
findings — plus the disabled-by-default no-op contract and a genuine
run-1-writes-back / run-2-reads-it round trip.

Harness style copied from ``test_repair_loop.py`` (FEAT-377 TASK-1911) and
``test_runner.py`` — no shared fixtures exist across test directories in
this suite, so `brief`/`mock_jira`/`patch_handoff`/`patch_worktree_base`/
`_build_flow` are duplicated locally, matching that established pattern.
"""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot import conf
from parrot.bots.flows.core.types import FlowStatus
from parrot.flows.dev_loop import (
    BugBrief,
    DevLoopRunner,
    QAReport,
    ResearchOutput,
    ShellCriterion,
    build_dev_loop_flow,
)
from parrot.flows.dev_loop.code_review import ClaudeCodeReviewDispatcher
from parrot.flows.dev_loop.graph_memory import DevLoopGraphMemory
from parrot.flows.dev_loop.models import CodeReviewVerdict, CriterionResult, DevelopmentOutput
from parrot.flows.dev_loop.nodes.deployment_handoff import DeploymentHandoffNode


@pytest.fixture
def brief() -> BugBrief:
    return BugBrief(
        summary="Customer sync drops the last row",
        affected_component="etl/customers/sync.yaml",
        log_sources=[],
        acceptance_criteria=[ShellCriterion(name="lint", command="ruff check .")],
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


@pytest.fixture
def patch_handoff(monkeypatch):
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


def _seam_dispatcher(research_out: ResearchOutput, *, cr_findings: List[str] = ()):
    """Dispatcher stub answering every output_model, capturing every
    dispatched ``brief`` for later inspection (keyed by output_model name)."""
    calls: Dict[str, List[Any]] = {
        "ResearchOutput": [], "DevelopmentOutput": [], "QAReport": [],
        "CodeReviewVerdict": [],
    }

    async def dispatch(*, brief, profile, output_model, run_id, node_id, cwd, session_host=None):
        name = output_model.__name__
        calls[name].append(brief)
        if output_model is ResearchOutput:
            return research_out
        if output_model is DevelopmentOutput:
            return DevelopmentOutput(files_changed=["x.py"], commit_shas=["sha1"], summary="ok")
        if output_model is QAReport:
            return QAReport(
                passed=True,
                criterion_results=[
                    CriterionResult(
                        name="lint", kind="shell", exit_code=0, duration_seconds=0.1,
                        stdout_tail="", stderr_tail="", passed=True,
                    )
                ],
                lint_passed=True,
            )
        if output_model is CodeReviewVerdict:
            return CodeReviewVerdict(passed=len(cr_findings) == 0, findings=list(cr_findings))
        raise AssertionError(f"unexpected output_model {output_model}")

    d = MagicMock()
    d.dispatch = AsyncMock(side_effect=dispatch)
    return d, calls


def _build_flow(dispatcher, jira, *, graph_memory=None, codereview_dispatcher=None):
    return build_dev_loop_flow(
        dispatcher=dispatcher,
        jira_toolkit=jira,
        log_toolkits={},
        redis_url="redis://localhost:6399/9",
        publish_flow_events=False,
        graph_memory=graph_memory,
        codereview_dispatcher=codereview_dispatcher,
    )


# ---------------------------------------------------------------------------
# Disabled-by-default no-op
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_graph_memory_disabled_noop(brief, mock_jira, patch_handoff, patch_worktree_base):
    """graph_memory=None (the default) — the flow behaves exactly like the
    pre-TASK-1914 baseline: reaches close, no graph-context text anywhere."""
    research = _research_output(patch_worktree_base)
    dispatcher, calls = _seam_dispatcher(research)
    flow = _build_flow(dispatcher, mock_jira)  # graph_memory=None
    runner = DevLoopRunner(flow, max_concurrent_runs=2)

    result = await runner.run(brief, run_id="run-noop")

    assert result.status == FlowStatus.COMPLETED
    assert "close" in set(result.responses)
    research_brief = calls["ResearchOutput"][0]
    assert "Graph memory context" not in research_brief.description


# ---------------------------------------------------------------------------
# Seam 2 — research context injection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_research_brief_contains_graph_context(
    brief, mock_jira, patch_handoff, patch_worktree_base, tmp_path, monkeypatch
):
    graph_db = tmp_path / "graph"
    graph_db.mkdir()
    monkeypatch.setattr(conf, "DEV_LOOP_GRAPH_MEMORY_PATH", str(graph_db))
    mem = await DevLoopGraphMemory.from_config()
    assert mem is not None
    # Seed the plane with a prior run whose CLAIM title matches the brief's
    # summary tokens closely enough for the retriever to find it.
    seed_report = QAReport(
        passed=True,
        criterion_results=[
            CriterionResult(
                name="customer sync drops the last row", kind="shell",
                exit_code=0, duration_seconds=0.1, stdout_tail="", stderr_tail="",
                passed=True,
            )
        ],
        lint_passed=True,
    )
    receipt = await mem.publish_run_outcome(
        "seed-run", seed_report, "succeeded", "customer sync drops the last row"
    )
    assert receipt is not None

    # A fresh facade instance (as a real second run would build) re-opens
    # the same on-disk plane and must see the seeded content.
    mem2 = await DevLoopGraphMemory.from_config()
    assert mem2 is not None

    research = _research_output(patch_worktree_base)
    dispatcher, calls = _seam_dispatcher(research)
    flow = _build_flow(dispatcher, mock_jira, graph_memory=mem2)
    runner = DevLoopRunner(flow, max_concurrent_runs=2)

    await runner.run(brief, run_id="run-with-context")

    research_brief = calls["ResearchOutput"][0]
    assert "## Graph memory context" in research_brief.description


# ---------------------------------------------------------------------------
# Seam 3 — run write-back (close + failure_handler)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_publishes_run_outcome(
    brief, mock_jira, patch_handoff, patch_worktree_base, tmp_path, monkeypatch
):
    monkeypatch.setattr(conf, "DEV_LOOP_GRAPH_MEMORY_PATH", str(tmp_path / "graph"))
    (tmp_path / "graph").mkdir()
    mem = await DevLoopGraphMemory.from_config()
    assert mem is not None

    research = _research_output(patch_worktree_base)
    dispatcher, _calls = _seam_dispatcher(research)
    flow = _build_flow(dispatcher, mock_jira, graph_memory=mem)
    runner = DevLoopRunner(flow, max_concurrent_runs=2)

    result = await runner.run(brief, run_id="run-publish")
    assert "close" in set(result.responses)

    commits = await mem._publisher.list_commits(run_id="run-publish")
    assert len(commits) == 1


@pytest.mark.asyncio
async def test_failure_handler_publishes_run_outcome(
    mock_jira, patch_handoff, patch_worktree_base, tmp_path, monkeypatch
):
    monkeypatch.setattr(conf, "DEV_LOOP_GRAPH_MEMORY_PATH", str(tmp_path / "graph"))
    (tmp_path / "graph").mkdir()
    mem = await DevLoopGraphMemory.from_config()
    assert mem is not None

    research = _research_output(patch_worktree_base)

    async def dispatch(*, brief, profile, output_model, run_id, node_id, cwd, session_host=None):
        if output_model is ResearchOutput:
            return research
        if node_id == "development":
            raise RuntimeError("boom")
        raise AssertionError("should not reach QA after a development error")

    dispatcher = MagicMock()
    dispatcher.dispatch = AsyncMock(side_effect=dispatch)
    flow = _build_flow(dispatcher, mock_jira, graph_memory=mem)
    runner = DevLoopRunner(flow, max_concurrent_runs=2)

    from parrot.flows.dev_loop.models import WorkBrief
    fail_brief = WorkBrief(
        kind="bug", summary="Customer sync drops the last row",
        affected_component="etl/x", log_sources=[],
        acceptance_criteria=[ShellCriterion(name="lint", command="ruff check .")],
        escalation_assignee="a", reporter="b",
    )
    result = await runner.run(fail_brief, run_id="run-fail-publish")
    assert "failure_handler" in set(result.responses)

    commits = await mem._publisher.list_commits(run_id="run-fail-publish")
    assert len(commits) == 1


@pytest.mark.asyncio
async def test_publish_failure_does_not_fail_close(
    brief, mock_jira, patch_handoff, patch_worktree_base, tmp_path, monkeypatch
):
    """The facade already degrade-never-fails; assert it here too, at the
    node-integration level (per the task's explicit instruction)."""
    monkeypatch.setattr(conf, "DEV_LOOP_GRAPH_MEMORY_PATH", str(tmp_path / "graph"))
    (tmp_path / "graph").mkdir()
    mem = await DevLoopGraphMemory.from_config()
    assert mem is not None

    class _BoomPublisher:
        async def publish(self, update: Any) -> Any:
            raise RuntimeError("store closed")

    mem._publisher = _BoomPublisher()

    research = _research_output(patch_worktree_base)
    dispatcher, _calls = _seam_dispatcher(research)
    flow = _build_flow(dispatcher, mock_jira, graph_memory=mem)
    runner = DevLoopRunner(flow, max_concurrent_runs=2)

    result = await runner.run(brief, run_id="run-publish-fail")

    assert result.status == FlowStatus.COMPLETED
    assert result.responses["close"]["status"] == "closed"


# ---------------------------------------------------------------------------
# Seam 4 — grounded findings
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ungrounded_findings_demoted(
    brief, mock_jira, patch_handoff, patch_worktree_base, tmp_path, monkeypatch
):
    monkeypatch.setattr(conf, "DEV_LOOP_GRAPH_MEMORY_PATH", str(tmp_path / "graph"))
    (tmp_path / "graph").mkdir()
    mem = await DevLoopGraphMemory.from_config()
    assert mem is not None

    # Force every finding to be dropped as "revise" — the review gate must
    # still pass (the only failures were ungrounded).
    async def _ground_claim(claim: str):
        from types import SimpleNamespace
        return SimpleNamespace(decision="revise")

    mem._grounding_evaluator.ground_claim = AsyncMock(side_effect=_ground_claim)

    research = _research_output(patch_worktree_base)
    dispatcher, _calls = _seam_dispatcher(
        research, cr_findings=["this looks like a real bug"],
    )
    codereview_dispatcher = ClaudeCodeReviewDispatcher(dispatcher=dispatcher)
    flow = _build_flow(
        dispatcher, mock_jira, graph_memory=mem,
        codereview_dispatcher=codereview_dispatcher,
    )
    runner = DevLoopRunner(flow, max_concurrent_runs=2)

    result = await runner.run(brief, run_id="run-ungrounded")

    assert "close" in set(result.responses)  # gate passed despite the finding
    final_report: QAReport = result.responses["qa"]
    assert final_report.code_review_passed is True
    assert final_report.code_review_findings == []
    assert "[ungrounded] this looks like a real bug" in final_report.notes


# ---------------------------------------------------------------------------
# Round trip: run 1 writes back, run 2 reads it
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_graph_memory_round_trip(
    mock_jira, patch_handoff, patch_worktree_base, tmp_path, monkeypatch
):
    graph_db = tmp_path / "graph"
    graph_db.mkdir()
    monkeypatch.setattr(conf, "DEV_LOOP_GRAPH_MEMORY_PATH", str(graph_db))

    shared_summary = "customer sync drops the last row on retry"
    brief1 = BugBrief(
        summary=shared_summary,
        affected_component="etl/customers/sync.yaml",
        log_sources=[],
        acceptance_criteria=[ShellCriterion(name="lint", command="ruff check .")],
        escalation_assignee="a", reporter="b",
    )

    # Run 1: writes back on close.
    mem1 = await DevLoopGraphMemory.from_config()
    research1 = _research_output(patch_worktree_base)
    dispatcher1, _ = _seam_dispatcher(research1)
    flow1 = _build_flow(dispatcher1, mock_jira, graph_memory=mem1)
    runner1 = DevLoopRunner(flow1, max_concurrent_runs=2)
    result1 = await runner1.run(brief1, run_id="run-1")
    assert "close" in set(result1.responses)

    # Run 2: a FRESH facade re-opening the SAME on-disk plane must see
    # run 1's RUN/CLAIM content in its research context.
    mem2 = await DevLoopGraphMemory.from_config()
    research2 = _research_output(patch_worktree_base)
    dispatcher2, calls2 = _seam_dispatcher(research2)
    flow2 = _build_flow(dispatcher2, mock_jira, graph_memory=mem2)
    runner2 = DevLoopRunner(flow2, max_concurrent_runs=2)
    await runner2.run(brief1, run_id="run-2")

    research_brief2 = calls2["ResearchOutput"][0]
    assert "## Graph memory context" in research_brief2.description
