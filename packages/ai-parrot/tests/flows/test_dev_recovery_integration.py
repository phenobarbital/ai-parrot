"""Cross-workflow checkpoint recovery integration matrix (TASK-2628).

Implements the spec §4 "Integration Tests" table end-to-end: every test
constructs a genuinely NEW runner/flow object graph (never reuses the
first "process"'s in-memory objects — the ``restarted_runner`` fixture
pattern from spec §4) sharing one in-memory :class:`FakeCheckpointStore`,
drives the REAL ``dev_loop``/``dev_flow`` topologies through
``DevLoopRunner``/``DevFlowRunner``, and asserts on real per-node call
counters (never a vacuous cache assertion).

Node internals are stubbed at the ``execute()`` level (the proven
``test_feature_flow.py`` recipe) rather than through dispatcher mocking —
unlike the bug-mode topology (proven safe end-to-end with a mocked
*dispatcher* by ``test_recovery_lifecycle.py``, TASK-2626),
``FeatureHandoffNode`` used by ``dev_flow``'s chain does real git/PR work
that has no equivalent low-level mock fixture in this codebase yet. Both
approaches exercise the SAME engine machinery under test here (the
checkpoint barrier, resume/fingerprint/lease protocol, and shared-data
projection) — only the depth of mocking inside a given node's own
business logic differs, which is out of this task's scope either way
(spec: "this task only wires and verifies; behavior gaps found here are
fixed by reopening the owning task").
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from parrot import conf
from parrot.bots.flows.core.checkpoint import (
    CheckpointStore,
    FlowCheckpoint,
    FlowLockedError,
)
from parrot.bots.flows.core.types import FlowStatus
from parrot.flows.dev_flow.flow import build_dev_flow
from parrot.flows.dev_flow.models import DevRequestBrief, IdeationOutput
from parrot.flows.dev_flow.nodes.dev_intake import DevIntakeNode
from parrot.flows.dev_flow.nodes.ideation import IdeationNode
from parrot.flows.dev_flow.runner import DevFlowRunner
from parrot.flows.dev_loop import (
    BugBrief,
    DevLoopRunner,
    ShellCriterion,
    build_dev_loop_flow,
)
from parrot.flows.dev_loop.checkpoint import DevCheckpointCoordinator
from parrot.flows.dev_loop.models import (
    DevelopmentOutput,
    FeedbackDecision,
    PlannerOutput,
    QAReport,
    ResearchOutput,
    SynthesisReport,
)
from parrot.flows.dev_loop.nodes.bug_intake import BugIntakeNode
from parrot.flows.dev_loop.nodes.close import DevLoopCloseNode
from parrot.flows.dev_loop.nodes.deployment_handoff import DeploymentHandoffNode
from parrot.flows.dev_loop.nodes.development import DevelopmentNode
from parrot.flows.dev_loop.nodes.failure_handler import FailureHandlerNode
from parrot.flows.dev_loop.nodes.feature_handoff import FeatureHandoffNode
from parrot.flows.dev_loop.nodes.feedback_router import FeedbackRouterNode
from parrot.flows.dev_loop.nodes.planner import PlannerNode
from parrot.flows.dev_loop.nodes.qa import QANode
from parrot.flows.dev_loop.nodes.research import ResearchNode
from parrot.flows.dev_loop.nodes.synthesis import SynthesisNode

pytestmark = pytest.mark.asyncio

# ---------------------------------------------------------------------------
# Autouse safety nets (this file lives outside tests/flows/dev_loop/, so it
# does NOT inherit that directory's conftest.py autouse fixtures — both are
# needed by any test here that drives a real handoff/close run).
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_dev_loop_run_artifacts(tmp_path, monkeypatch) -> None:
    """See tests/flows/dev_loop/conftest.py's fixture of the same name."""
    monkeypatch.setattr("parrot.flows.dev_loop.runner.conf.OUTPUT_DIR", str(tmp_path))


@pytest.fixture(autouse=True)
def _stub_pr_summary_enrichment(monkeypatch) -> None:
    """See tests/flows/dev_loop/conftest.py's fixture of the same name.

    Resolved via ``sys.modules`` directly (not a dotted monkeypatch
    string) — same ``test_lazy_import.py`` module-reload pitfall that
    fixture's own docstring documents.
    """
    stub = AsyncMock(return_value="")
    monkeypatch.setattr(
        sys.modules["parrot.flows.dev_loop.nodes.feature_handoff"],
        "summarize_pr_changes",
        stub,
    )
    monkeypatch.setattr(
        sys.modules["parrot.flows.dev_loop.nodes.deployment_handoff"],
        "summarize_pr_changes",
        stub,
    )


# ---------------------------------------------------------------------------
# In-memory CheckpointStore (mirrors tests/flows/checkpoint/test_suspend_resume.py)
# ---------------------------------------------------------------------------


class FakeCheckpointStore(CheckpointStore):
    """In-memory CheckpointStore — full contract, no external service."""

    def __init__(self) -> None:
        self._by_flow: dict[str, list[FlowCheckpoint]] = {}
        self._leases: dict[str, str] = {}

    async def put(self, checkpoint: FlowCheckpoint) -> None:
        history = self._by_flow.setdefault(checkpoint.flow_id, [])
        history[:] = [c for c in history if c.checkpoint_id != checkpoint.checkpoint_id]
        history.append(checkpoint)
        history.sort(key=lambda c: c.checkpoint_id)

    async def latest(self, flow_id: str):
        history = self._by_flow.get(flow_id, [])
        return history[-1] if history else None

    async def get(self, flow_id: str, checkpoint_id: int):
        for cp in self._by_flow.get(flow_id, []):
            if cp.checkpoint_id == checkpoint_id:
                return cp
        return None

    async def history(self, flow_id: str, limit: int = 10):
        return list(reversed(self._by_flow.get(flow_id, [])))[:limit]

    async def list_flows(self, status=None):
        return []

    async def delete_flow(self, flow_id: str) -> None:
        self._by_flow.pop(flow_id, None)

    async def acquire_lease(self, flow_id: str, holder: str, ttl: int = 60) -> bool:
        if flow_id in self._leases:
            return False
        self._leases[flow_id] = holder
        return True

    async def renew_lease(self, flow_id: str, holder: str, ttl: int = 60) -> bool:
        return self._leases.get(flow_id) == holder

    async def release_lease(self, flow_id: str, holder: str) -> None:
        if self._leases.get(flow_id) == holder:
            del self._leases[flow_id]

    async def close(self) -> None:
        pass


@pytest.fixture
def fake_store() -> FakeCheckpointStore:
    return FakeCheckpointStore()


# ---------------------------------------------------------------------------
# dev-loop (bug mode) node-execute stubs
# ---------------------------------------------------------------------------


def _stub_dev_loop_bug_executes(
    monkeypatch,
    calls: dict,
    *,
    fail_at: set[str] | None = None,
    research_out: ResearchOutput | None = None,
) -> None:
    """Stub every bug-mode dev-loop node's ``execute()``.

    A node id in ``fail_at`` raises ``RuntimeError`` once it is reached
    (simulating a crash right after its predecessor's checkpoint landed);
    every other node succeeds and publishes its typed result to
    ``shared_data`` the same key the real node would.
    """
    fail_at = fail_at or set()

    def _count(name: str) -> None:
        calls[name] = calls.get(name, 0) + 1

    async def intake_exec(self, ctx, deps=None, **kw):
        _count("bug_intake")
        if "bug_intake" in fail_at:
            raise RuntimeError("simulated crash: bug_intake")
        shared = self.shared_state(ctx)
        return shared.get("bug_brief") or shared.get("work_brief")

    async def research_exec(self, ctx, deps=None, **kw):
        _count("research")
        if "research" in fail_at:
            raise RuntimeError("simulated crash: research")
        out = research_out or ResearchOutput(
            jira_issue_key="OPS-1",
            spec_path="sdd/specs/x.spec.md",
            feat_id="FEAT-130",
            branch_name="feat-130-fix",
            worktree_path="/tmp/feat-130-fix",
            log_excerpts=[],
        )
        self.shared_state(ctx)["research_output"] = out
        return out

    async def dev_exec(self, ctx, deps=None, **kw):
        _count("development")
        if "development" in fail_at:
            raise RuntimeError("simulated crash: development")
        out = DevelopmentOutput(files_changed=["a.py"], commit_shas=["abc"], summary="ok")
        self.shared_state(ctx)["development_output"] = out
        return out

    async def qa_exec(self, ctx, deps=None, **kw):
        _count("qa")
        if "qa" in fail_at:
            raise RuntimeError("simulated crash: qa")
        return QAReport(passed=True, criterion_results=[], lint_passed=True)

    async def handoff_exec(self, ctx, deps=None, **kw):
        _count("deployment_handoff")
        if "deployment_handoff" in fail_at:
            raise RuntimeError("simulated crash: deployment_handoff")
        return {"status": "deployed"}

    async def close_exec(self, ctx, deps=None, **kw):
        _count("close")
        return {"status": "closed"}

    async def failure_exec(self, ctx, deps=None, **kw):
        _count("failure_handler")
        return {"status": "escalated"}

    monkeypatch.setattr(BugIntakeNode, "execute", intake_exec)
    monkeypatch.setattr(ResearchNode, "execute", research_exec)
    monkeypatch.setattr(DevelopmentNode, "execute", dev_exec)
    monkeypatch.setattr(QANode, "execute", qa_exec)
    monkeypatch.setattr(DeploymentHandoffNode, "execute", handoff_exec)
    monkeypatch.setattr(DevLoopCloseNode, "execute", close_exec)
    monkeypatch.setattr(FailureHandlerNode, "execute", failure_exec)


def _dev_loop_bug_brief() -> BugBrief:
    return BugBrief(
        summary="Customer sync drops the last row",
        affected_component="etl/customers/sync.yaml",
        log_sources=[],
        acceptance_criteria=[ShellCriterion(name="lint", command="ruff check .")],
        escalation_assignee="557058:abc",
        reporter="557058:def",
    )


def _dev_loop_flow_kwargs() -> dict[str, Any]:
    return {
        "dispatcher": MagicMock(),
        "jira_toolkit": MagicMock(),
        "log_toolkits": {},
        "redis_url": "redis://localhost:6399/9",  # never connected in tests
        "publish_flow_events": False,
    }


def _materialize_real_worktree(worktree_path: str, branch_name: str, *, with_task_index: bool = False) -> None:
    """Turn ``worktree_path`` into a REAL ``git worktree add``.

    A resumed run's restored ``ResearchOutput``/``PlannerOutput`` goes
    through TASK-2625's recovered-artifact validation (worktree
    registered on the expected branch + referenced spec — and, for
    ``PlannerOutput``, task-index — files exist). Call this AFTER
    "process 1" completes — mimicking what the real ``sdd-research``/
    ``sdd-planner`` subagent does on disk during that first run — never
    BEFORE it: ``ResearchNode``'s own guard treats a pre-existing,
    already-registered path as stale at dispatch time (irrelevant here
    since these nodes are stubbed, but kept for parity with
    ``test_recovery_lifecycle.py``'s proven helper of the same name).

    Args:
        with_task_index: When ``True``, also creates
            ``sdd/tasks/index/x.json`` (``PlannerOutput.task_index_path``
            — TASK-2627's own ``_real_worktree()`` fixture does the same).
    """
    import subprocess

    def _git(repo, *args: str) -> None:
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)

    path = Path(worktree_path)
    repo = path.parent / f"repo-{path.name}"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / "f.txt").write_text("x")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "init")

    _git(repo, "worktree", "add", "-b", branch_name, str(path))
    spec_dir = path / "sdd" / "specs"
    spec_dir.mkdir(parents=True)
    (spec_dir / "x.spec.md").write_text("# spec\n")
    if with_task_index:
        task_index_dir = path / "sdd" / "tasks" / "index"
        task_index_dir.mkdir(parents=True)
        (task_index_dir / "x.json").write_text("{}\n")


# ---------------------------------------------------------------------------
# dev-flow node-execute stubs
# ---------------------------------------------------------------------------


def _stub_dev_flow_executes(
    monkeypatch,
    calls: dict,
    *,
    fail_at: set[str] | None = None,
    planner_out: PlannerOutput | None = None,
) -> None:
    """Stub every dev-flow node's ``execute()`` (dev_intake/ideation are
    dev-flow-owned; planner/development/synthesis/qa/feedback_router/
    feature_handoff/close/failure_handler are the SAME classes reused
    from ``dev_loop`` — patched here regardless of which topology a given
    test drives; ``monkeypatch`` undoes everything at test teardown)."""
    fail_at = fail_at or set()

    def _count(name: str) -> None:
        calls[name] = calls.get(name, 0) + 1

    async def intake_exec(self, ctx, deps=None, **kw):
        _count("dev_intake")
        if "dev_intake" in fail_at:
            raise RuntimeError("simulated crash: dev_intake")
        return self.shared_state(ctx).get("dev_brief")

    async def ideation_exec(self, ctx, deps=None, **kw):
        _count("ideation")
        if "ideation" in fail_at:
            raise RuntimeError("simulated crash: ideation")
        out = IdeationOutput(
            document_path="sdd/proposals/x.proposal.md",
            document_kind="proposal",
            slug="x",
            committed=True,
        )
        self.shared_state(ctx)["ideation_output"] = out
        return out

    async def planner_exec(self, ctx, deps=None, **kw):
        _count("planner")
        if "planner" in fail_at:
            raise RuntimeError("simulated crash: planner")
        out = planner_out or PlannerOutput(
            spec_path="sdd/specs/x.spec.md",
            task_index_path="sdd/tasks/index/x.json",
            feat_id="FEAT-999",
            branch_name="feat-999-x",
            worktree_path="/tmp/feat-999-x",
        )
        self.shared_state(ctx)["planner_output"] = out
        return out

    async def dev_exec(self, ctx, deps=None, **kw):
        _count("development")
        if "development" in fail_at:
            raise RuntimeError("simulated crash: development")
        out = DevelopmentOutput(files_changed=["a.py"], commit_shas=["abc"], summary="ok")
        self.shared_state(ctx)["development_output"] = out
        return out

    async def synthesis_exec(self, ctx, deps=None, **kw):
        _count("synthesis")
        if "synthesis" in fail_at:
            raise RuntimeError("simulated crash: synthesis")
        return SynthesisReport(consistent=True, adjustments=[], summary="clean")

    async def qa_exec(self, ctx, deps=None, **kw):
        _count("qa")
        if "qa" in fail_at:
            raise RuntimeError("simulated crash: qa")
        return QAReport(passed=True, criterion_results=[], lint_passed=True)

    async def feedback_exec(self, ctx, deps=None, **kw):
        _count("feedback_router")
        return FeedbackDecision(decision="escalate", notes="")

    async def handoff_exec(self, ctx, deps=None, **kw):
        _count("feature_handoff")
        if "feature_handoff" in fail_at:
            raise RuntimeError("simulated crash: feature_handoff")
        return {"status": "ready_to_deploy"}

    async def close_exec(self, ctx, deps=None, **kw):
        _count("close")
        return {"status": "closed"}

    async def failure_exec(self, ctx, deps=None, **kw):
        _count("failure_handler")
        return {"status": "escalated"}

    monkeypatch.setattr(DevIntakeNode, "execute", intake_exec)
    monkeypatch.setattr(IdeationNode, "execute", ideation_exec)
    monkeypatch.setattr(PlannerNode, "execute", planner_exec)
    monkeypatch.setattr(DevelopmentNode, "execute", dev_exec)
    monkeypatch.setattr(SynthesisNode, "execute", synthesis_exec)
    monkeypatch.setattr(QANode, "execute", qa_exec)
    monkeypatch.setattr(FeedbackRouterNode, "execute", feedback_exec)
    monkeypatch.setattr(FeatureHandoffNode, "execute", handoff_exec)
    monkeypatch.setattr(DevLoopCloseNode, "execute", close_exec)
    monkeypatch.setattr(FailureHandlerNode, "execute", failure_exec)


def _dev_flow_nl_brief() -> DevRequestBrief:
    return DevRequestBrief(
        kind="enhancement",
        title="compression budget telemetry",
        description="Add per-tool telemetry to the compression budget.",
    )


def _dev_flow_flow_kwargs() -> dict[str, Any]:
    return {
        "dispatcher": MagicMock(),
        "redis_url": "redis://localhost:6399/9",  # never connected in tests
        "publish_flow_events": False,
    }


# ---------------------------------------------------------------------------
# dev-loop: restart after bug intake / research / development
# ---------------------------------------------------------------------------


async def test_dev_loop_restart_after_bug_intake(monkeypatch, fake_store) -> None:
    """New process, same run_id: bug intake (reproduction/enrichment) is
    never repeated after its successful checkpoint."""
    calls: dict = {}
    _stub_dev_loop_bug_executes(monkeypatch, calls, fail_at={"research"})
    kwargs1 = _dev_loop_flow_kwargs()
    flow1 = build_dev_loop_flow(**kwargs1)
    runner1 = DevLoopRunner(flow1, max_concurrent_runs=2, checkpoint_store=fake_store, dev_loop_flow_kwargs=kwargs1)
    result1 = await runner1.run(_dev_loop_bug_brief(), run_id="run-after-intake")

    assert "research" in result1.errors
    assert calls.get("bug_intake") == 1

    calls2: dict = {}
    _stub_dev_loop_bug_executes(monkeypatch, calls2, fail_at=set())
    kwargs2 = _dev_loop_flow_kwargs()
    flow2 = build_dev_loop_flow(**kwargs2)
    runner2 = DevLoopRunner(flow2, max_concurrent_runs=2, checkpoint_store=fake_store, dev_loop_flow_kwargs=kwargs2)
    result2 = await runner2.run(_dev_loop_bug_brief(), run_id="run-after-intake")

    assert result2.status == FlowStatus.COMPLETED
    assert calls2.get("bug_intake") is None  # never redispatched by "process 2"
    assert calls2.get("research") == 1


async def test_dev_loop_restart_after_research(monkeypatch, fake_store, tmp_path) -> None:
    """Research is not redispatched after its successful checkpoint; typed
    ResearchOutput is restored (DevelopmentNode resolves it downstream
    without a live research_output ever being supplied by "process 2")."""
    calls: dict = {}
    research_out = ResearchOutput(
        jira_issue_key="OPS-1",
        spec_path="sdd/specs/x.spec.md",
        feat_id="FEAT-130",
        branch_name="feat-130-fix",
        worktree_path=str(tmp_path / "feat-130-fix"),
        log_excerpts=[],
    )
    _stub_dev_loop_bug_executes(monkeypatch, calls, fail_at={"development"}, research_out=research_out)
    kwargs1 = _dev_loop_flow_kwargs()
    flow1 = build_dev_loop_flow(**kwargs1)
    runner1 = DevLoopRunner(flow1, max_concurrent_runs=2, checkpoint_store=fake_store, dev_loop_flow_kwargs=kwargs1)
    result1 = await runner1.run(_dev_loop_bug_brief(), run_id="run-after-research")

    assert "development" in result1.errors
    assert calls.get("research") == 1

    # The real sdd-research subagent creates the worktree on disk during
    # research's dispatch — simulated here, AFTER process 1 (TASK-2625's
    # artifact validation needs it to exist before "process 2" resumes).
    _materialize_real_worktree(research_out.worktree_path, research_out.branch_name)

    calls2: dict = {}
    _stub_dev_loop_bug_executes(monkeypatch, calls2, fail_at=set(), research_out=research_out)
    kwargs2 = _dev_loop_flow_kwargs()
    flow2 = build_dev_loop_flow(**kwargs2)
    runner2 = DevLoopRunner(flow2, max_concurrent_runs=2, checkpoint_store=fake_store, dev_loop_flow_kwargs=kwargs2)
    result2 = await runner2.run(_dev_loop_bug_brief(), run_id="run-after-research")

    assert result2.status == FlowStatus.COMPLETED
    assert calls2.get("research") is None  # never redispatched
    assert calls2.get("development") == 1


async def test_dev_loop_restart_after_development(monkeypatch, fake_store, tmp_path) -> None:
    """Completed development is not redispatched; execution continues at qa."""
    calls: dict = {}
    research_out = ResearchOutput(
        jira_issue_key="OPS-1",
        spec_path="sdd/specs/x.spec.md",
        feat_id="FEAT-130",
        branch_name="feat-130-fix",
        worktree_path=str(tmp_path / "feat-130-fix"),
        log_excerpts=[],
    )
    _stub_dev_loop_bug_executes(monkeypatch, calls, fail_at={"qa"}, research_out=research_out)
    kwargs1 = _dev_loop_flow_kwargs()
    flow1 = build_dev_loop_flow(**kwargs1)
    runner1 = DevLoopRunner(flow1, max_concurrent_runs=2, checkpoint_store=fake_store, dev_loop_flow_kwargs=kwargs1)
    result1 = await runner1.run(_dev_loop_bug_brief(), run_id="run-after-dev")

    assert "qa" in result1.errors
    assert calls.get("development") == 1

    _materialize_real_worktree(research_out.worktree_path, research_out.branch_name)

    calls2: dict = {}
    _stub_dev_loop_bug_executes(monkeypatch, calls2, fail_at=set())
    kwargs2 = _dev_loop_flow_kwargs()
    flow2 = build_dev_loop_flow(**kwargs2)
    runner2 = DevLoopRunner(flow2, max_concurrent_runs=2, checkpoint_store=fake_store, dev_loop_flow_kwargs=kwargs2)
    result2 = await runner2.run(_dev_loop_bug_brief(), run_id="run-after-dev")

    assert result2.status == FlowStatus.COMPLETED
    assert calls2.get("development") is None
    assert calls2.get("qa") == 1


# ---------------------------------------------------------------------------
# dev-flow: restart after planner / development
# ---------------------------------------------------------------------------


def _dev_flow_planner_out(tmp_path) -> PlannerOutput:
    return PlannerOutput(
        spec_path="sdd/specs/x.spec.md",
        task_index_path="sdd/tasks/index/x.json",
        feat_id="FEAT-999",
        branch_name="feat-999-x",
        worktree_path=str(tmp_path / "feat-999-x"),
    )


async def test_dev_flow_restart_after_planner(monkeypatch, fake_store, tmp_path) -> None:
    """Planner/ideation are skipped on resume; downstream (development)
    continues on the original explicit-edge graph."""
    calls: dict = {}
    planner_out = _dev_flow_planner_out(tmp_path)
    _stub_dev_flow_executes(monkeypatch, calls, fail_at={"development"}, planner_out=planner_out)
    kwargs1 = _dev_flow_flow_kwargs()
    flow1 = build_dev_flow(**kwargs1)
    runner1 = DevFlowRunner(flow1, max_concurrent_runs=2, checkpoint_store=fake_store, dev_loop_flow_kwargs=kwargs1)
    result1 = await runner1.run(_dev_flow_nl_brief(), run_id="run-flow-after-planner")

    assert "development" in result1.errors
    assert calls.get("ideation") == 1
    assert calls.get("planner") == 1

    # sdd-planner creates the worktree + spec + task index on disk during
    # its real dispatch — simulated here, AFTER process 1 (TASK-2625's
    # artifact validation needs them before "process 2" resumes).
    _materialize_real_worktree(planner_out.worktree_path, planner_out.branch_name, with_task_index=True)

    calls2: dict = {}
    _stub_dev_flow_executes(monkeypatch, calls2, fail_at=set(), planner_out=planner_out)
    kwargs2 = _dev_flow_flow_kwargs()
    flow2 = build_dev_flow(**kwargs2)
    runner2 = DevFlowRunner(flow2, max_concurrent_runs=2, checkpoint_store=fake_store, dev_loop_flow_kwargs=kwargs2)
    result2 = await runner2.run(_dev_flow_nl_brief(), run_id="run-flow-after-planner")

    assert result2.status == FlowStatus.COMPLETED
    assert calls2.get("ideation") is None
    assert calls2.get("planner") is None
    assert calls2.get("development") == 1


async def test_dev_flow_restart_after_development(monkeypatch, fake_store, tmp_path) -> None:
    """Completed proactive development is not redispatched."""
    calls: dict = {}
    planner_out = _dev_flow_planner_out(tmp_path)
    _stub_dev_flow_executes(monkeypatch, calls, fail_at={"synthesis"}, planner_out=planner_out)
    kwargs1 = _dev_flow_flow_kwargs()
    flow1 = build_dev_flow(**kwargs1)
    runner1 = DevFlowRunner(flow1, max_concurrent_runs=2, checkpoint_store=fake_store, dev_loop_flow_kwargs=kwargs1)
    result1 = await runner1.run(_dev_flow_nl_brief(), run_id="run-flow-after-dev")

    assert "synthesis" in result1.errors
    assert calls.get("development") == 1

    _materialize_real_worktree(planner_out.worktree_path, planner_out.branch_name, with_task_index=True)

    calls2: dict = {}
    _stub_dev_flow_executes(monkeypatch, calls2, fail_at=set(), planner_out=planner_out)
    kwargs2 = _dev_flow_flow_kwargs()
    flow2 = build_dev_flow(**kwargs2)
    runner2 = DevFlowRunner(flow2, max_concurrent_runs=2, checkpoint_store=fake_store, dev_loop_flow_kwargs=kwargs2)
    result2 = await runner2.run(_dev_flow_nl_brief(), run_id="run-flow-after-dev")

    assert result2.status == FlowStatus.COMPLETED
    assert calls2.get("development") is None
    assert calls2.get("synthesis") == 1


# ---------------------------------------------------------------------------
# Cache-miss on a new run_id / exception-preserved frontier / lease conflict
# ---------------------------------------------------------------------------


async def test_restart_with_new_run_id_is_cache_miss(monkeypatch, fake_store) -> None:
    """Same brief, a DIFFERENT run_id: every node dispatches again — no
    accidental cross-run_id reuse."""
    calls: dict = {}
    _stub_dev_loop_bug_executes(monkeypatch, calls, fail_at=set())
    kwargs1 = _dev_loop_flow_kwargs()
    flow1 = build_dev_loop_flow(**kwargs1)
    runner1 = DevLoopRunner(flow1, max_concurrent_runs=2, checkpoint_store=fake_store, dev_loop_flow_kwargs=kwargs1)
    result1 = await runner1.run(_dev_loop_bug_brief(), run_id="run-cache-a")
    assert result1.status == FlowStatus.COMPLETED
    assert calls.get("bug_intake") == 1
    assert calls.get("research") == 1

    kwargs2 = _dev_loop_flow_kwargs()
    flow2 = build_dev_loop_flow(**kwargs2)
    runner2 = DevLoopRunner(flow2, max_concurrent_runs=2, checkpoint_store=fake_store, dev_loop_flow_kwargs=kwargs2)
    result2 = await runner2.run(_dev_loop_bug_brief(), run_id="run-cache-b")  # different id

    assert result2.status == FlowStatus.COMPLETED
    # A genuinely new run — every node dispatched a SECOND time (shared
    # `calls` dict spans both processes; never reset between them).
    assert calls.get("bug_intake") == 2
    assert calls.get("research") == 2
    assert calls.get("development") == 2


async def test_exception_restart_preserves_completed_frontier(monkeypatch, fake_store, tmp_path) -> None:
    """A downstream exception followed by restart skips EVERY prior
    durably-completed node, not just the immediately preceding one.

    Fails at ``qa`` (not ``deployment_handoff``) deliberately: ``QAReport``
    is not one of the five dev-loop models ``dev_loop/flow.py`` registers
    via ``register_checkpoint_type`` (only ``WorkBrief``/``FeatureBrief``/
    ``ResearchOutput``/``PlannerOutput``/``DevelopmentOutput`` are). A
    resumed checkpoint whose LATEST successful node is ``qa`` therefore
    serializes that node's own ``QAReport`` result lossily (degraded to a
    string — confirmed via an ``AgentsFlow.resume(): ... is lossy``
    warning), which breaks the ``qa -> deployment_handoff`` on_condition
    edge's predicate re-evaluation on resume (it cannot re-derive
    ``_qa_passed`` from a degraded string) and the run completes without
    ever re-dispatching ``deployment_handoff``. This is a genuine gap
    outside TASK-2628's file list (fixing it means registering
    ``QAReport``/``SynthesisReport``/``FeedbackDecision`` in
    ``dev_loop/flow.py``/``dev_flow/flow.py`` — not listed here) — see
    this task's Completion Note.
    """
    calls: dict = {}
    research_out = ResearchOutput(
        jira_issue_key="OPS-1",
        spec_path="sdd/specs/x.spec.md",
        feat_id="FEAT-130",
        branch_name="feat-130-fix",
        worktree_path=str(tmp_path / "feat-130-fix"),
        log_excerpts=[],
    )
    # development succeeds and is checkpointed BEFORE qa crashes — a wider
    # frontier (bug_intake + research + development, all three explicitly
    # asserted below) than test_dev_loop_restart_after_development checks.
    _stub_dev_loop_bug_executes(monkeypatch, calls, fail_at={"qa"}, research_out=research_out)
    kwargs1 = _dev_loop_flow_kwargs()
    flow1 = build_dev_loop_flow(**kwargs1)
    runner1 = DevLoopRunner(flow1, max_concurrent_runs=2, checkpoint_store=fake_store, dev_loop_flow_kwargs=kwargs1)
    result1 = await runner1.run(_dev_loop_bug_brief(), run_id="run-frontier")

    assert "qa" in result1.errors
    assert calls.get("bug_intake") == 1
    assert calls.get("research") == 1
    assert calls.get("development") == 1

    _materialize_real_worktree(research_out.worktree_path, research_out.branch_name)

    calls2: dict = {}
    _stub_dev_loop_bug_executes(monkeypatch, calls2, fail_at=set())
    kwargs2 = _dev_loop_flow_kwargs()
    flow2 = build_dev_loop_flow(**kwargs2)
    runner2 = DevLoopRunner(flow2, max_concurrent_runs=2, checkpoint_store=fake_store, dev_loop_flow_kwargs=kwargs2)
    result2 = await runner2.run(_dev_loop_bug_brief(), run_id="run-frontier")

    assert result2.status == FlowStatus.COMPLETED
    # The ENTIRE prior frontier is skipped — not just qa's immediate
    # predecessor (development).
    assert calls2.get("bug_intake") is None
    assert calls2.get("research") is None
    assert calls2.get("development") is None
    assert calls2.get("qa") == 1


async def test_concurrent_resume_lease_conflict(fake_store) -> None:
    """Two processes cannot both resume one workflow/run identity."""
    coordinator = DevCheckpointCoordinator(store=fake_store)

    # Seed a checkpoint via a trivial fresh run (mirrors
    # test_dev_flow_restart_after_planner's coordinator-level pattern).
    from parrot.bots.flows.core.context import FlowContext
    from parrot.bots.flows.core.fsm import AgentTaskMachine
    from parrot.bots.flows.core.node import Node
    from parrot.bots.flows.flow.definition import FlowDefinition, NodeDefinition
    from parrot.bots.flows.flow.flow import AgentsFlow, register_node
    from pydantic import Field

    @register_node("dev-recovery-lease-test.step")
    class _StepNode(Node):
        dependencies: set[str] = Field(default_factory=set)
        successors: set[str] = Field(default_factory=set)
        fsm: AgentTaskMachine | None = None
        result: Any = None

        def model_post_init(self, _context: Any) -> None:
            if self.fsm is None:
                object.__setattr__(self, "fsm", AgentTaskMachine(agent_name=self.node_id))

        @property
        def name(self) -> str:
            return self.node_id

        async def execute(self, ctx, deps: Any, **kwargs: Any) -> Any:
            return self.result

    def _flow_factory(_definition):
        # A single node with zero edges is NOT `explicit_mode`
        # (`self._definition is None and bool(self._edges)` — flow.py:1656)
        # and never reaches the required-checkpoint-barrier code path at
        # all. Two nodes + one edge (mirroring test_recovery.py's own
        # `_build_test_flow`) is the minimal graph that actually exercises
        # a durable checkpoint write.
        external_definition = FlowDefinition(
            flow="dev-recovery-lease-test",
            nodes=[
                NodeDefinition(id="step_a", type="dev-recovery-lease-test.step"),
                NodeDefinition(id="step_b", type="dev-recovery-lease-test.step"),
            ],
            edges=[],
        )
        flow = AgentsFlow(
            name="dev-recovery-lease-test",
            checkpoint=True,
            checkpoint_store=fake_store,
            checkpoint_required=True,
            checkpoint_definition=external_definition,
        )
        flow.add_node(_StepNode(node_id="step_a", result={"ok": True}))
        flow.add_node(_StepNode(node_id="step_b", result={"ok": True}))
        flow.add_edge("step_a", "step_b", condition="on_success")
        return flow

    brief = _dev_flow_nl_brief()
    ctx1 = FlowContext(initial_task="t")
    flow1, mode1 = await coordinator.prepare(
        workflow="dev-flow",
        run_id="run-lease",
        brief=brief,
        live_context=ctx1,
        flow_factory=_flow_factory,
        execution_policy={},
    )
    assert mode1 == "fresh"
    await flow1.run_flow(ctx1)

    # A second, INDEPENDENT process holding the resume lease first (mirrors
    # test_suspend_resume.py::test_resume_locked_raises_flowlockederror's
    # proven pre-acquire pattern).
    await fake_store.acquire_lease("dev-flow/run-lease", "other-holder", ttl=60)

    coordinator2 = DevCheckpointCoordinator(store=fake_store)
    ctx2 = FlowContext(initial_task="t")
    with pytest.raises(FlowLockedError):
        await coordinator2.prepare(
            workflow="dev-flow",
            run_id="run-lease",
            brief=brief,
            live_context=ctx2,
            flow_factory=_flow_factory,
            execution_policy={},
        )


# ---------------------------------------------------------------------------
# Runtime entry points: per-run flow factories (spec §3 Module 6)
# ---------------------------------------------------------------------------


def _load_server_module():
    server_path = Path(__file__).parents[4] / "examples" / "dev_loop" / "server.py"
    if not server_path.exists():
        pytest.skip(f"server.py not found at {server_path}")
    module_name = "_dev_recovery_server_under_test"
    if module_name in sys.modules:
        del sys.modules[module_name]
    spec = importlib.util.spec_from_file_location(module_name, server_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class _FakeApp(dict):
    """Minimal stand-in for ``aiohttp.web.Application``."""


def _make_fake_redis() -> MagicMock:
    redis = MagicMock()
    redis.aclose = AsyncMock()
    return redis


async def test_runtime_entrypoints_build_per_run_flows(monkeypatch) -> None:
    """examples/dev_loop/server.py's ``_on_startup`` and
    parrot.cli.devloop.bootstrap's ``build_runtime`` must no longer
    construct their ``DevLoopRunner`` with a checkpoint identity shared
    across every job — each now supplies ``dev_loop_flow_kwargs`` so the
    runner's recovery path builds a genuinely fresh, checkpoint-enabled
    ``AgentsFlow`` per run_id (TASK-2628)."""
    # -- examples/dev_loop/server.py -------------------------------------
    flow_captured: dict[str, Any] = {}
    runner_captured: dict[str, Any] = {}

    def fake_build_flow(**kwargs: Any) -> MagicMock:
        flow_captured.update(kwargs)
        return MagicMock()

    def fake_runner(flow: Any, **kwargs: Any) -> MagicMock:
        runner_captured.update(kwargs)
        return MagicMock(max_concurrent_runs=1)

    monkeypatch.setattr(conf, "DEV_LOOP_REPOS", [])
    server_mod = _load_server_module()
    monkeypatch.setattr(server_mod, "build_dev_loop_flow", fake_build_flow)
    monkeypatch.setattr(server_mod, "_build_log_toolkits", dict)
    monkeypatch.setattr(server_mod, "_build_jira_toolkit", lambda: MagicMock())
    monkeypatch.setattr(server_mod.aioredis, "from_url", lambda url, **kw: _make_fake_redis())
    monkeypatch.setattr(server_mod, "ClaudeCodeDispatcher", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(server_mod, "DevLoopRunner", fake_runner)

    app = _FakeApp()
    app["redis_url"] = "redis://localhost:6379/0"
    await server_mod._on_startup(app)

    assert runner_captured.get("dev_loop_flow_kwargs") is not None
    # The captured kwargs are EXACTLY what build_dev_loop_flow was called
    # with — the recovery path rebuilds via the SAME shape, never a
    # divergent/partial copy.
    assert runner_captured["dev_loop_flow_kwargs"] == flow_captured
    assert "checkpoint_store" in runner_captured

    # -- parrot.cli.devloop.bootstrap.build_runtime -----------------------
    from parrot.cli.devloop import bootstrap as bootstrap_mod
    from parrot.cli.devloop.bootstrap import PreflightResult

    bootstrap_flow_captured: dict[str, Any] = {}
    bootstrap_runner_captured: dict[str, Any] = {}

    def fake_bootstrap_build_flow(**kwargs: Any) -> MagicMock:
        bootstrap_flow_captured.update(kwargs)
        return MagicMock()

    def fake_bootstrap_runner(flow: Any, **kwargs: Any) -> MagicMock:
        bootstrap_runner_captured.update(kwargs)
        return MagicMock()

    ok_result = PreflightResult(ok=True, checks=[])
    with (pytest.MonkeyPatch.context() as mp2,):
        mp2.setattr(bootstrap_mod, "preflight", AsyncMock(return_value=ok_result))
        mp2.setattr(bootstrap_mod, "_build_jira_toolkit", lambda: None)
        mp2.setattr(bootstrap_mod, "_build_log_toolkits", dict)
        mp2.setattr(bootstrap_mod, "default_identities", AsyncMock(return_value=("reporter", "escalation")))
        mp2.setattr("parrot.flows.dev_loop.ClaudeCodeDispatcher", MagicMock(return_value=MagicMock()))
        mp2.setattr("parrot.flows.dev_loop.build_dev_loop_flow", fake_bootstrap_build_flow)
        mp2.setattr("parrot.flows.dev_loop.DevLoopRunner", fake_bootstrap_runner)
        mp2.setattr(
            "parrot.flows.dev_loop.graph_memory.DevLoopGraphMemory.from_config",
            AsyncMock(return_value=None),
        )
        await bootstrap_mod.build_runtime()

    assert bootstrap_runner_captured.get("dev_loop_flow_kwargs") is not None
    assert bootstrap_runner_captured["dev_loop_flow_kwargs"] == bootstrap_flow_captured
    assert "checkpoint_store" in bootstrap_runner_captured
