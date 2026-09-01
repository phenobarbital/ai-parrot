"""Dev Loop per-run checkpoint lifecycle (TASK-2626).

Covers: registered dev-loop result types round-trip through
``FlowStateSerializer`` (mirroring the process-wide registration added to
``models/__init__.py``), ``TaskScheduler`` excluding already-``done`` tasks
after a restart (existing on-disk-index behavior — confirmed unaffected),
node-granular single-agent recovery (an interrupted ``development`` reruns
whole; completed upstream nodes do not redispatch), and
``DevLoopRunner.run(run_id=...)`` end-to-end through the real engine with a
fake in-memory ``CheckpointStore``.

Reuses the mocked-dispatcher/Jira/worktree-base fixture recipe already
proven by ``test_runner.py``'s end-to-end suite (same dev-loop topology,
same mocking strategy) rather than inventing a new one.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from parrot import conf
from parrot.bots.flows.core.checkpoint import (
    CheckpointStore,
    FlowCheckpoint,
    FlowStateSerializer,
)
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
from parrot.flows.dev_loop.models import DevelopmentOutput, PlannerOutput
from parrot.flows.dev_loop.nodes.deployment_handoff import DeploymentHandoffNode
from parrot.flows.dev_loop.task_scheduler import TaskScheduler

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


# ---------------------------------------------------------------------------
# Registered type round-trip (spec test table: Modules 1/4)
# ---------------------------------------------------------------------------


def test_registered_dev_models_round_trip() -> None:
    """Importing parrot.flows.dev_loop.models registers every routed result type."""
    serializer = FlowStateSerializer()
    instances = [
        WorkBrief(
            summary="x" * 12,
            affected_component="a",
            acceptance_criteria=[ShellCriterion(name="l", command="true")],
            escalation_assignee="e",
            reporter="r",
        ),
        ResearchOutput(
            jira_issue_key="OPS-1",
            spec_path="s",
            feat_id="FEAT-1",
            branch_name="b",
            worktree_path="/tmp/w",
        ),
        PlannerOutput(
            spec_path="s",
            task_index_path="t",
            feat_id="FEAT-1",
            branch_name="feat-1-x",
            worktree_path="/tmp/w",
        ),
        DevelopmentOutput(files_changed=["a.py"], commit_shas=["abc"], summary="done"),
    ]
    for instance in instances:
        data, lossy = serializer.encode_with_meta(instance)
        assert not lossy, f"{type(instance).__name__} degraded to lossy repr"
        restored = serializer.decode(data)
        # Qualname equality, not `is`/exact identity: a test suite that
        # runs earlier in the SAME session (test_lazy_import.py) may have
        # deliberately reloaded parrot.flows.dev_loop.models to verify
        # import purity, producing a distinct-but-equivalent class object
        # under the same registered tag. What round-trip fidelity actually
        # promises is "the right type", not "the exact class object this
        # test file happened to import at collection time".
        assert type(restored).__qualname__ == type(instance).__qualname__
        assert type(restored).__module__ == type(instance).__module__


# ---------------------------------------------------------------------------
# TaskScheduler excludes done tasks after restart (existing on-disk behavior)
# ---------------------------------------------------------------------------


def test_scheduler_excludes_done_tasks_after_restart(tmp_path) -> None:
    """spec §7: 'task index truth is on disk' — a restart rereads it fresh.

    This task deliberately does NOT modify TaskScheduler/development.py
    (both build a fresh TaskScheduler from disk on every dispatch already)
    — this test confirms that existing, already-correct behavior stays
    intact and is what pool recovery relies on.
    """
    index_path = tmp_path / "index.json"
    index_path.write_text(
        json.dumps(
            {
                "tasks": [
                    {"id": "TASK-1", "title": "a", "status": "done", "depends_on": []},
                    {"id": "TASK-2", "title": "b", "status": "done", "depends_on": ["TASK-1"]},
                    {"id": "TASK-3", "title": "c", "status": "pending", "depends_on": ["TASK-2"]},
                    {"id": "TASK-4", "title": "d", "status": "pending", "depends_on": []},
                    {"id": "TASK-5", "title": "e", "status": "pending", "depends_on": ["TASK-4"]},
                ]
            }
        )
    )

    scheduler = TaskScheduler.from_index_file(index_path)
    assert scheduler is not None

    wave_ids = {t.id for t in scheduler.next_wave()}
    # The two already-"done" tasks must never be offered for (re-)dispatch;
    # TASK-3's dependency (TASK-2) is already done, so it IS dispatchable;
    # TASK-4 has no deps and is dispatchable; TASK-5 depends on TASK-4
    # (not yet done) so it is NOT in this wave.
    assert "TASK-1" not in wave_ids
    assert "TASK-2" not in wave_ids
    assert wave_ids == {"TASK-3", "TASK-4"}


# ---------------------------------------------------------------------------
# End-to-end: node-granular recovery through the real engine
# ---------------------------------------------------------------------------


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
    monkeypatch.setattr(DeploymentHandoffNode, "_push_branch", AsyncMock(return_value=None))
    monkeypatch.setattr(DeploymentHandoffNode, "_create_pr", AsyncMock(return_value="https://github.com/x/y/pull/1"))
    # test_single_agent_recovery_is_node_granular materializes a REAL git
    # worktree (for TASK-2625's artifact-validation guard on resume) with
    # no `origin` remote configured — assert_base_is_clean's own,
    # unrelated FEAT-466 guard would otherwise refuse to fetch origin/main
    # from it. Not what this test suite exercises; neutralized like the
    # two mocks above.
    #
    # Resolved via sys.modules[...] directly, NOT a dotted monkeypatch
    # string: test_lazy_import.py deletes and re-imports every
    # parrot.flows.dev_loop.* module (then restores sys.modules), and a
    # dotted string resolves through parent-package attribute chains —
    # surgery that can leave a parent package's attribute pointing at a
    # module object sys.modules no longer holds, silently patching an
    # orphaned object instead of the live one (same pitfall the top-level
    # conftest.py's _stub_pr_summary_enrichment fixture already documents
    # and works around for feature_handoff/deployment_handoff).
    monkeypatch.setattr(
        sys.modules["parrot.flows.dev_loop.nodes.deployment_handoff"],
        "assert_base_is_clean",
        AsyncMock(return_value=None),
    )


@pytest.fixture
def patch_worktree_base(tmp_path, monkeypatch):
    monkeypatch.setattr("parrot.flows.dev_loop.nodes.research.conf.WORKTREE_BASE_PATH", str(tmp_path))
    return tmp_path


def _research_output(tmp_path) -> ResearchOutput:
    return ResearchOutput(
        jira_issue_key="OPS-1",
        spec_path="sdd/specs/x.spec.md",
        feat_id="FEAT-130",
        branch_name="feat-130-fix",
        worktree_path=str(tmp_path / "feat-130-fix"),
        log_excerpts=[],
    )


def _materialize_real_worktree(research_out: ResearchOutput) -> None:
    """Turn ``research_out.worktree_path`` into a REAL ``git worktree add``.

    A resumed run's ``research_output`` goes through recovered-artifact
    validation (TASK-2625: worktree registered on the expected branch +
    referenced spec file exists). Call this AFTER the "process 1" run
    completes — mimicking what the real ``sdd-research`` subagent does on
    disk (outside this test's mocked dispatcher) during that first run —
    never BEFORE it: ``ResearchNode`` itself guards against a
    pre-existing, already-registered path at dispatch time
    (``_ensure_worktree_safe``) and would treat it as stale.
    """
    import subprocess

    def _git(repo, *args: str) -> None:
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)

    worktree_path = Path(research_out.worktree_path)
    repo = worktree_path.parent / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / "f.txt").write_text("x")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "init")

    _git(repo, "worktree", "add", "-b", research_out.branch_name, str(worktree_path))
    spec_dir = worktree_path / "sdd" / "specs"
    spec_dir.mkdir(parents=True)
    (spec_dir / "x.spec.md").write_text("# spec\n")


def _counting_dispatcher(research_out, *, calls: dict, fail_development: bool = False, qa_passed: bool = True):
    """Like test_runner.py's ``_dispatcher_returning`` but with call counters.

    ``calls`` accumulates counts by ``output_model.__name__`` across
    however many dispatcher instances a test builds — pass the SAME dict
    to each dispatcher built for the "same run_id, different process"
    scenario so the counters span both.
    """

    async def dispatch(*, brief, profile, output_model, run_id, node_id, cwd, session_host=None):
        calls[output_model.__name__] = calls.get(output_model.__name__, 0) + 1
        if output_model is ResearchOutput:
            return research_out
        if output_model is DevelopmentOutput:
            if fail_development:
                raise RuntimeError("dispatch blew up in development")
            return DevelopmentOutput(files_changed=["x.py"], commit_shas=["abc123"], summary="implemented the fix")
        if output_model is QAReport:
            return QAReport(
                passed=qa_passed,
                criterion_results=[],
                lint_passed=qa_passed,
                attempt=1 if qa_passed else int(conf.DEV_LOOP_QA_MAX_RETRIES),
            )
        raise AssertionError(f"unexpected output_model {output_model}")

    d = MagicMock()
    d.dispatch = AsyncMock(side_effect=dispatch)
    return d


def _dev_loop_flow_kwargs(dispatcher, jira) -> dict[str, Any]:
    return {
        "dispatcher": dispatcher,
        "jira_toolkit": jira,
        "log_toolkits": {},
        "redis_url": "redis://localhost:6399/9",  # never connected in tests
        "publish_flow_events": False,
    }


async def test_single_agent_recovery_is_node_granular(brief, mock_jira, patch_handoff, patch_worktree_base) -> None:
    """Interrupted single-agent development reruns whole node (at-least-once);
    completed upstream (research) is never redispatched."""
    fake_store = FakeCheckpointStore()
    calls: dict = {}
    research_out = _research_output(patch_worktree_base)
    # BugIntakeNode._enrich() mutates `brief.description` in place during
    # run 1 — a genuinely separate "process 2" would re-supply its OWN
    # pristine copy of the brief (from wherever it originally stored the
    # request), never the first process's in-memory enriched object.
    # Snapshot it here, before run 1 executes, so "process 2" below gets
    # exactly that: the same INPUT the checkpoint's fingerprint was
    # computed from, not an artifact of reusing one Python object across
    # a simulated process boundary in this test.
    pristine_brief = brief.model_copy(deep=True)

    # "Process 1": development blows up (the simulated crash).
    dispatcher1 = _counting_dispatcher(research_out, calls=calls, fail_development=True)
    kwargs1 = _dev_loop_flow_kwargs(dispatcher1, mock_jira)
    flow1 = build_dev_loop_flow(**kwargs1)
    runner1 = DevLoopRunner(flow1, max_concurrent_runs=2, checkpoint_store=fake_store, dev_loop_flow_kwargs=kwargs1)
    result1 = await runner1.run(brief, run_id="run-recover-1")

    assert "development" in result1.errors
    assert calls.get("ResearchOutput") == 1
    assert calls.get("DevelopmentOutput") == 1  # the crashed attempt

    # The real sdd-research subagent creates the worktree on disk during
    # research's dispatch — simulated here, AFTER run 1 (never before:
    # ResearchNode's own guard treats a pre-existing registered path as
    # stale at dispatch time).
    _materialize_real_worktree(research_out)

    # "Process 2": a fresh runner/flow, SAME run_id + pristine brief, development now succeeds.
    dispatcher2 = _counting_dispatcher(research_out, calls=calls, fail_development=False)
    kwargs2 = _dev_loop_flow_kwargs(dispatcher2, mock_jira)
    flow2 = build_dev_loop_flow(**kwargs2)
    runner2 = DevLoopRunner(flow2, max_concurrent_runs=2, checkpoint_store=fake_store, dev_loop_flow_kwargs=kwargs2)
    result2 = await runner2.run(pristine_brief, run_id="run-recover-1")

    assert result2.status == FlowStatus.COMPLETED
    # research was already checkpointed as complete — never redispatched.
    assert calls.get("ResearchOutput") == 1
    # development reran WHOLE (node-granular at-least-once) — not restored.
    assert calls.get("DevelopmentOutput") == 2
    executed = set(result2.responses)
    assert "development" in executed
    assert "qa" in executed
    assert "deployment_handoff" in executed
    assert "close" in executed


async def test_completed_research_not_redispatched_on_matching_resume(
    brief, mock_jira, patch_handoff, patch_worktree_base
) -> None:
    """A fully-completed run's checkpoint, resumed with the SAME run_id and
    input, never redispatches ANY node — the whole run restores."""
    fake_store = FakeCheckpointStore()
    calls: dict = {}
    research_out = _research_output(patch_worktree_base)
    # See test_single_agent_recovery_is_node_granular's comment: BugIntakeNode
    # mutates `brief.description` in place — snapshot before run 1 so
    # "process 2" gets the pristine input the checkpoint's fingerprint was
    # actually computed from.
    pristine_brief = brief.model_copy(deep=True)

    dispatcher1 = _counting_dispatcher(research_out, calls=calls)
    kwargs1 = _dev_loop_flow_kwargs(dispatcher1, mock_jira)
    flow1 = build_dev_loop_flow(**kwargs1)
    runner1 = DevLoopRunner(flow1, max_concurrent_runs=2, checkpoint_store=fake_store, dev_loop_flow_kwargs=kwargs1)
    result1 = await runner1.run(brief, run_id="run-full-resume")
    assert result1.status == FlowStatus.COMPLETED
    assert calls.get("ResearchOutput") == 1
    assert calls.get("DevelopmentOutput") == 1

    # Simulated on-disk artifact from the (mocked) research dispatch —
    # see test_single_agent_recovery_is_node_granular's comment.
    _materialize_real_worktree(research_out)

    dispatcher2 = _counting_dispatcher(research_out, calls=calls)
    kwargs2 = _dev_loop_flow_kwargs(dispatcher2, mock_jira)
    flow2 = build_dev_loop_flow(**kwargs2)
    runner2 = DevLoopRunner(flow2, max_concurrent_runs=2, checkpoint_store=fake_store, dev_loop_flow_kwargs=kwargs2)
    result2 = await runner2.run(pristine_brief, run_id="run-full-resume")

    assert result2.status == FlowStatus.COMPLETED
    # Nothing new dispatched — the whole run restored from the checkpoint.
    assert calls.get("ResearchOutput") == 1
    assert calls.get("DevelopmentOutput") == 1


async def test_run_id_omitted_is_plain_fresh_run(mock_jira, patch_handoff, patch_worktree_base) -> None:
    """No run_id -> auto-generated -> never routes through recovery at all
    (spec §8 OQ1), even when checkpoint_store/dev_loop_flow_kwargs are set."""
    fake_store = FakeCheckpointStore()
    brief = BugBrief(
        summary="Customer sync drops the last row",
        affected_component="etl/customers/sync.yaml",
        acceptance_criteria=[ShellCriterion(name="lint", command="ruff check .")],
        escalation_assignee="a",
        reporter="b",
    )
    calls: dict = {}
    research_out = _research_output(patch_worktree_base)
    dispatcher = _counting_dispatcher(research_out, calls=calls)
    kwargs = _dev_loop_flow_kwargs(dispatcher, mock_jira)
    flow = build_dev_loop_flow(**kwargs)
    runner = DevLoopRunner(flow, max_concurrent_runs=2, checkpoint_store=fake_store, dev_loop_flow_kwargs=kwargs)

    result = await runner.run(brief)  # no run_id

    assert result.status == FlowStatus.COMPLETED
    # A fresh run every time — no checkpoint was ever consulted/written
    # for a specific stable identity (nothing to assert on fake_store
    # beyond "did not raise"); the point is the recovery path was skipped.


# ---------------------------------------------------------------------------
# FEAT-490 TASK-2685: per-run flow-kwargs overrides seam
# ---------------------------------------------------------------------------


def test_run_without_overrides_is_byte_identical(mock_jira) -> None:
    """``_dev_loop_flow_factory()`` with no overrides builds with exactly
    today's kwargs — the bug flow must not notice this change at all."""
    captured: list[dict] = []

    def fake_build_dev_loop_flow(**kwargs):
        captured.append(kwargs)
        return MagicMock()

    # Patch the exact globals dict `_dev_loop_flow_factory`'s code executes
    # against — NOT a dotted monkeypatch string. Same pitfall this file's
    # `patch_handoff` fixture already documents: test_lazy_import.py can
    # leave `DevLoopRunner` bound to a module object `sys.modules` no
    # longer resolves to, so a string-path patch can silently land on an
    # orphaned module while the live method keeps calling the real thing.
    target_globals = DevLoopRunner._dev_loop_flow_factory.__globals__
    original = target_globals["build_dev_loop_flow"]
    target_globals["build_dev_loop_flow"] = fake_build_dev_loop_flow
    try:
        dispatcher = MagicMock()
        kwargs = _dev_loop_flow_kwargs(dispatcher, mock_jira)
        runner = DevLoopRunner(MagicMock(), dev_loop_flow_kwargs=kwargs)

        factory = runner._dev_loop_flow_factory()
        factory(None)
    finally:
        target_globals["build_dev_loop_flow"] = original

    assert len(captured) == 1
    for key, value in kwargs.items():
        assert captured[0][key] == value
    assert captured[0]["checkpoint"] is True
    assert captured[0]["checkpoint_required"] is True


def test_overrides_reach_the_flow_factory(mock_jira) -> None:
    """A supplied override appears in the kwargs ``build_dev_loop_flow`` is
    called with."""
    captured: list[dict] = []

    def fake_build_dev_loop_flow(**kwargs):
        captured.append(kwargs)
        return MagicMock()

    # See test_run_without_overrides_is_byte_identical for why this patches
    # the method's own __globals__ rather than a dotted monkeypatch string.
    target_globals = DevLoopRunner._dev_loop_flow_factory.__globals__
    original = target_globals["build_dev_loop_flow"]
    target_globals["build_dev_loop_flow"] = fake_build_dev_loop_flow
    try:
        dispatcher = MagicMock()
        kwargs = _dev_loop_flow_kwargs(dispatcher, mock_jira)
        runner = DevLoopRunner(MagicMock(), dev_loop_flow_kwargs=kwargs)

        factory = runner._dev_loop_flow_factory({"redis_url": "redis://override:6399/0"})
        factory(None)
    finally:
        target_globals["build_dev_loop_flow"] = original

    assert captured[0]["redis_url"] == "redis://override:6399/0"
    # Everything else is unaffected.
    assert captured[0]["dispatcher"] is dispatcher


def test_overrides_are_not_stored_on_the_instance(mock_jira) -> None:
    """Inspect the runner after building a factory with overrides: no
    per-run kwargs left behind on ``self``."""
    dispatcher = MagicMock()
    kwargs = _dev_loop_flow_kwargs(dispatcher, mock_jira)
    runner = DevLoopRunner(MagicMock(), dev_loop_flow_kwargs=kwargs)

    runner._dev_loop_flow_factory({"redis_url": "redis://override:6399/0"})

    # The instance's own kwargs dict is untouched — no override key leaked in.
    assert runner._dev_loop_flow_kwargs == kwargs
    assert runner._dev_loop_flow_kwargs["redis_url"] == kwargs["redis_url"]
    assert not hasattr(runner, "_current_flow_kwargs")
    assert not hasattr(runner, "_flow_kwargs_overrides")


def test_concurrent_runs_do_not_leak_overrides(mock_jira) -> None:
    """Two interleaved runs with different overrides each build with theirs."""
    dispatcher = MagicMock()
    kwargs = _dev_loop_flow_kwargs(dispatcher, mock_jira)
    runner = DevLoopRunner(MagicMock(), dev_loop_flow_kwargs=kwargs)

    captured: list[dict] = []

    def fake_build_dev_loop_flow(**built_kwargs):
        captured.append(built_kwargs)
        return MagicMock()

    # See test_run_without_overrides_is_byte_identical for why this patches
    # the method's own __globals__ rather than the (possibly orphaned)
    # module object reachable through a fresh `import ... as` statement.
    target_globals = DevLoopRunner._dev_loop_flow_factory.__globals__
    original = target_globals["build_dev_loop_flow"]
    target_globals["build_dev_loop_flow"] = fake_build_dev_loop_flow
    try:
        # Two closures built back-to-back, simulating two concurrent runs
        # with distinct per-run overrides — neither must see the other's.
        factory_a = runner._dev_loop_flow_factory({"redis_url": "redis://a:6399/0"})
        factory_b = runner._dev_loop_flow_factory({"redis_url": "redis://b:6399/0"})
        factory_a(None)
        factory_b(None)
    finally:
        target_globals["build_dev_loop_flow"] = original

    assert captured[0]["redis_url"] == "redis://a:6399/0"
    assert captured[1]["redis_url"] == "redis://b:6399/0"


# ---------------------------------------------------------------------------
# FEAT-490 TASK-2691: per-run plan threaded through the ops runner
# ---------------------------------------------------------------------------


class _StubOpsFlow:
    """Completes immediately, recording the context it was handed —
    avoids driving the real eight-node graph (already exhaustively
    covered elsewhere in this suite) for a test about the SEAM."""

    def __init__(self) -> None:
        self.contexts: list = []
        self._run_id_holder: dict = {}

    async def run_flow(self, ctx, **kwargs) -> FlowResult:
        self.contexts.append(ctx)
        return FlowResult(output=ctx.shared_data["run_id"], status=FlowStatus.COMPLETED)


async def test_dev_loop_runner_threads_a_per_run_plan(brief, mock_jira) -> None:
    """Spec §3 Module 8: an ops embedder passes a per-run DevFlowModelPlan
    through the SAME generic overrides mapping TASK-2685 added — no typed
    `model_plan` parameter is added to `DevLoopRunner.run()` itself (spec
    §8 Q5) — and it reaches `build_dev_loop_flow` (TASK-2690's new kwarg)
    end to end through the public `run()` API."""
    captured: list[dict] = []

    def fake_build_dev_loop_flow(**kwargs):
        captured.append(kwargs)
        return _StubOpsFlow()

    target_globals = DevLoopRunner._dev_loop_flow_factory.__globals__
    original = target_globals["build_dev_loop_flow"]
    target_globals["build_dev_loop_flow"] = fake_build_dev_loop_flow
    try:
        dispatcher = MagicMock()
        kwargs = _dev_loop_flow_kwargs(dispatcher, mock_jira)
        runner = DevLoopRunner(MagicMock(), dev_loop_flow_kwargs=kwargs)
        sentinel_plan = object()
        result = await runner.run(
            brief,
            run_id="run-ops-plan",
            flow_kwargs_overrides={"model_plan": sentinel_plan},
        )
    finally:
        target_globals["build_dev_loop_flow"] = original

    assert result.status == FlowStatus.COMPLETED
    assert len(captured) == 1
    assert captured[0]["model_plan"] is sentinel_plan


async def test_ops_path_without_a_plan_is_byte_identical(brief, mock_jira) -> None:
    """No `flow_kwargs_overrides` -> `build_dev_loop_flow` receives exactly
    today's kwargs, with no `model_plan` key at all."""
    captured: list[dict] = []

    def fake_build_dev_loop_flow(**kwargs):
        captured.append(kwargs)
        return _StubOpsFlow()

    target_globals = DevLoopRunner._dev_loop_flow_factory.__globals__
    original = target_globals["build_dev_loop_flow"]
    target_globals["build_dev_loop_flow"] = fake_build_dev_loop_flow
    try:
        dispatcher = MagicMock()
        kwargs = _dev_loop_flow_kwargs(dispatcher, mock_jira)
        runner = DevLoopRunner(MagicMock(), dev_loop_flow_kwargs=kwargs)
        result = await runner.run(brief, run_id="run-ops-no-plan")
    finally:
        target_globals["build_dev_loop_flow"] = original

    assert result.status == FlowStatus.COMPLETED
    assert len(captured) == 1
    assert "model_plan" not in captured[0]
    for key, value in kwargs.items():
        assert captured[0][key] == value


async def test_no_per_run_plan_state_leaks_across_concurrent_ops_runs(brief, mock_jira) -> None:
    """No per-run state on the instance; concurrent runs stay isolated —
    two sequential `run()` calls with different plans each build with
    their own, and the instance's own kwargs are never mutated."""
    captured: list[dict] = []

    def fake_build_dev_loop_flow(**kwargs):
        captured.append(kwargs)
        return _StubOpsFlow()

    target_globals = DevLoopRunner._dev_loop_flow_factory.__globals__
    original = target_globals["build_dev_loop_flow"]
    target_globals["build_dev_loop_flow"] = fake_build_dev_loop_flow
    try:
        dispatcher = MagicMock()
        kwargs = _dev_loop_flow_kwargs(dispatcher, mock_jira)
        runner = DevLoopRunner(MagicMock(), dev_loop_flow_kwargs=kwargs)
        plan_a, plan_b = object(), object()
        await runner.run(
            brief.model_copy(deep=True),
            run_id="run-ops-a",
            flow_kwargs_overrides={"model_plan": plan_a},
        )
        assert "model_plan" not in runner._dev_loop_flow_kwargs
        await runner.run(
            brief.model_copy(deep=True),
            run_id="run-ops-b",
            flow_kwargs_overrides={"model_plan": plan_b},
        )
    finally:
        target_globals["build_dev_loop_flow"] = original

    assert captured[0]["model_plan"] is plan_a
    assert captured[1]["model_plan"] is plan_b
    assert "model_plan" not in runner._dev_loop_flow_kwargs


# ---------------------------------------------------------------------------
# FEAT-490 post-review fix: overrides must NOT reach a RESUMED run's rebuild
# ---------------------------------------------------------------------------
#
# CRITICAL bug found by adversarial review after all 8 FEAT-490 tasks were
# implemented: `AgentsFlow.resume()` (bots/flows/flow/flow.py) calls the
# SAME `flow_factory` closure DevCheckpointCoordinator.prepare() uses for a
# fresh build — `flow_factory(checkpoint.definition)`, never `None` — to
# rebuild the topology of every not-yet-completed node on a RESUMED run.
# The original `_dev_loop_flow_factory(overrides)` merged `overrides` into
# `kwargs` unconditionally, BEFORE returning the closure — so a per-run
# override (e.g. a differing `model_plan`) silently reached a resumed run's
# rebuild too, contradicting the resume rule (spec §8 Q1) every other test
# in this suite exercises only through a MOCKED `prepare()`/`_checkpoint_
# coordinator` (which never invokes the real closure with a non-None
# definition, so the mocks alone could never have caught this). Fixed by
# moving the merge INSIDE the closure, gated on `_definition is None` — the
# only signal `prepare()`/`resume()` give the closure for "is this call
# fresh or resuming." These tests drive the closure with BOTH shapes
# directly, the same signal the real coordinator/`AgentsFlow.resume()` use.


def test_overrides_apply_on_the_fresh_definition_none_call(mock_jira) -> None:
    """`factory(None)` — the cache-miss/fresh signal — still applies
    overrides (regression guard: the fix must not disable the fresh path)."""
    captured: list[dict] = []

    def fake_build_dev_loop_flow(**kwargs):
        captured.append(kwargs)
        return MagicMock()

    dispatcher = MagicMock()
    kwargs = _dev_loop_flow_kwargs(dispatcher, mock_jira)
    runner = DevLoopRunner(MagicMock(), dev_loop_flow_kwargs=kwargs)

    target_globals = DevLoopRunner._dev_loop_flow_factory.__globals__
    original = target_globals["build_dev_loop_flow"]
    target_globals["build_dev_loop_flow"] = fake_build_dev_loop_flow
    try:
        factory = runner._dev_loop_flow_factory({"redis_url": "redis://override:6399/0"})
        factory(None)
    finally:
        target_globals["build_dev_loop_flow"] = original

    assert captured[0]["redis_url"] == "redis://override:6399/0"


def test_overrides_do_not_reach_a_resumed_rebuild(mock_jira) -> None:
    """`factory(<a real definition, i.e. what AgentsFlow.resume() passes>)`
    — the exact call shape `AgentsFlow.resume()` uses at
    `bots/flows/flow/flow.py:1556` (`flow_factory(checkpoint.definition)`)
    — must build with ONLY the construction-time kwargs. This is the
    precise regression guard for the bug: before the fix, this assertion
    failed (the override reached the resumed rebuild too)."""
    captured: list[dict] = []

    def fake_build_dev_loop_flow(**kwargs):
        captured.append(kwargs)
        return MagicMock()

    dispatcher = MagicMock()
    kwargs = _dev_loop_flow_kwargs(dispatcher, mock_jira)
    runner = DevLoopRunner(MagicMock(), dev_loop_flow_kwargs=kwargs)

    target_globals = DevLoopRunner._dev_loop_flow_factory.__globals__
    original = target_globals["build_dev_loop_flow"]
    target_globals["build_dev_loop_flow"] = fake_build_dev_loop_flow
    try:
        factory = runner._dev_loop_flow_factory({"redis_url": "redis://should-not-apply:6399/0"})
        # A stand-in for `checkpoint.definition` — any non-None object is
        # the correct signal; AgentsFlow.resume() never passes None here.
        sentinel_definition = object()
        factory(sentinel_definition)
    finally:
        target_globals["build_dev_loop_flow"] = original

    assert captured[0]["redis_url"] == kwargs["redis_url"]
    assert captured[0]["redis_url"] != "redis://should-not-apply:6399/0"


def test_same_closure_applies_overrides_only_to_its_fresh_call(mock_jira) -> None:
    """A single closure instance, called first fresh then as-if-resuming —
    mirrors `prepare()` calling the SAME closure it built once per `run()`
    invocation. Only the `_definition is None` call sees the override."""
    captured: list[dict] = []

    def fake_build_dev_loop_flow(**kwargs):
        captured.append(kwargs)
        return MagicMock()

    dispatcher = MagicMock()
    kwargs = _dev_loop_flow_kwargs(dispatcher, mock_jira)
    runner = DevLoopRunner(MagicMock(), dev_loop_flow_kwargs=kwargs)

    target_globals = DevLoopRunner._dev_loop_flow_factory.__globals__
    original = target_globals["build_dev_loop_flow"]
    target_globals["build_dev_loop_flow"] = fake_build_dev_loop_flow
    try:
        factory = runner._dev_loop_flow_factory({"redis_url": "redis://per-run:6399/0"})
        factory(None)
        factory(object())
    finally:
        target_globals["build_dev_loop_flow"] = original

    assert captured[0]["redis_url"] == "redis://per-run:6399/0"
    assert captured[1]["redis_url"] == kwargs["redis_url"]
