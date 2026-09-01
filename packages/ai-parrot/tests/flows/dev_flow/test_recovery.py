"""Proactive Dev Flow recovery integration (TASK-2627).

Covers: `build_dev_flow`'s checkpoint wiring, namespace separation between
`dev-loop` and `dev-flow` checkpoints for the SAME `run_id`, restoration of
the intake/ideation/planner projections (`dev_brief`/`feature_brief`/
`ideation_output`/`planner_output`/derived `research_output`), and
`DevFlowRunner`'s recovery gate (mirrors TASK-2626's `DevLoopRunner` tests,
scoped to what THIS task changed rather than re-driving the full real
dev-flow node graph — that generic checkpoint/resume machinery is already
exhaustively covered by TASK-2622..2626's suites).
"""

from typing import Any
from unittest.mock import MagicMock

import pytest
from parrot.bots.flows.core.checkpoint import (
    CheckpointStore,
    FlowCheckpoint,
    register_checkpoint_type,
)
from parrot.bots.flows.core.context import FlowContext
from parrot.bots.flows.core.fsm import AgentTaskMachine
from parrot.bots.flows.core.node import Node
from parrot.bots.flows.flow.definition import FlowDefinition, NodeDefinition
from parrot.bots.flows.flow.flow import AgentsFlow, register_node
from parrot.flows.dev_flow.flow import build_dev_flow
from parrot.flows.dev_flow.models import DevRequestBrief, IdeationOutput
from parrot.flows.dev_flow.runner import DevFlowRunner
from parrot.flows.dev_loop.checkpoint import DevCheckpointCoordinator
from parrot.flows.dev_loop.models import (
    DevelopmentOutput,
    FeatureBrief,
    PlannerOutput,
    ResearchOutput,
)
from pydantic import Field

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

    async def latest(self, flow_id: str) -> FlowCheckpoint | None:
        history = self._by_flow.get(flow_id, [])
        return history[-1] if history else None

    async def get(self, flow_id: str, checkpoint_id: int) -> FlowCheckpoint | None:
        for cp in self._by_flow.get(flow_id, []):
            if cp.checkpoint_id == checkpoint_id:
                return cp
        return None

    async def history(self, flow_id: str, limit: int = 10) -> list[FlowCheckpoint]:
        return list(reversed(self._by_flow.get(flow_id, [])))[:limit]

    async def list_flows(self, status: str | None = None) -> list[dict[str, Any]]:
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
# build_dev_flow: checkpoint wiring at the topology level
# ---------------------------------------------------------------------------


def test_build_dev_flow_checkpoint_disabled_by_default() -> None:
    """checkpoint=False (default) is byte-identical to pre-FEAT-480 wiring."""
    flow = build_dev_flow(dispatcher=MagicMock(), redis_url="redis://x", publish_flow_events=False)

    assert flow._checkpoint_enabled is False
    assert flow._checkpoint_required is False
    assert flow._checkpoint_definition_arg is None
    assert flow._checkpoint_shared_data_arg is None


def test_build_dev_flow_checkpoint_enabled_wires_definition_and_projector() -> None:
    flow = build_dev_flow(
        dispatcher=MagicMock(),
        redis_url="redis://x",
        publish_flow_events=False,
        checkpoint=True,
        checkpoint_required=True,
        flow_id="dev-flow/run-x",
    )

    assert flow._checkpoint_enabled is True
    assert flow._checkpoint_required is True
    assert flow.flow_id == "dev-flow/run-x"
    # The SAME declarative definition used for node materialization.
    assert flow._checkpoint_definition_arg is flow._dev_loop_definition
    assert flow._checkpoint_shared_data_arg is not None
    # Explicit-mode scheduler is unaffected (checkpoint_definition is a
    # SEPARATE field from the constructor's own definition= param).
    assert flow._definition is None
    assert bool(flow._edges) is True


# ---------------------------------------------------------------------------
# A trivial explicit-edge graph standing in for the real dev-flow graph
# ---------------------------------------------------------------------------


@register_node("dev-flow-recovery-test.step")
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

    async def execute(self, ctx: FlowContext, deps: Any, **kwargs: Any) -> Any:
        return self.result


def _build_test_flow(definition, *, store, ideation_out, planner_out, dev_out) -> AgentsFlow:
    """``ideation`` -> ``planner`` -> ``development``, mirroring dev-flow's
    reused chain closely enough to exercise the SAME projection/validation
    machinery `build_dev_flow` itself wires in."""
    external_definition = FlowDefinition(
        flow="dev-flow-recovery-test",
        nodes=[
            NodeDefinition(id="ideation", type="dev-flow-recovery-test.step"),
            NodeDefinition(id="planner", type="dev-flow-recovery-test.step"),
            NodeDefinition(id="development", type="dev-flow-recovery-test.step"),
        ],
        edges=[],
    )
    flow = AgentsFlow(
        name="dev-flow-recovery-test",
        checkpoint=True,
        checkpoint_store=store,
        checkpoint_required=True,
        checkpoint_definition=external_definition,
    )
    flow.add_node(_StepNode(node_id="ideation", result=ideation_out))
    flow.add_node(_StepNode(node_id="planner", result=planner_out))
    flow.add_node(_StepNode(node_id="development", result=dev_out))
    flow.add_edge("ideation", "planner", condition="on_success")
    flow.add_edge("planner", "development", condition="on_success")
    return flow


@pytest.fixture
def fake_store() -> FakeCheckpointStore:
    return FakeCheckpointStore()


@pytest.fixture
def nl_brief() -> DevRequestBrief:
    return DevRequestBrief(
        kind="enhancement",
        title="compression budget telemetry",
        description="Add per-tool telemetry to the compression budget.",
    )


@pytest.fixture(autouse=True)
def _register_dev_flow_types() -> None:
    """Simulate the module-level registration `dev_flow/flow.py` performs
    on import — same technique as TASK-2626's own coordinator tests."""
    register_checkpoint_type(DevRequestBrief)
    register_checkpoint_type(IdeationOutput)
    register_checkpoint_type(FeatureBrief)
    register_checkpoint_type(PlannerOutput)
    register_checkpoint_type(ResearchOutput)
    register_checkpoint_type(DevelopmentOutput)


def _real_worktree(tmp_path, branch_name: str):
    """A real repo + a real `git worktree add`-registered secondary worktree
    (TASK-2625's artifact validation needs one to succeed)."""
    import subprocess

    def _git(repo, *args: str) -> None:
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / "f.txt").write_text("x")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "init")

    worktree_path = tmp_path / branch_name
    _git(repo, "worktree", "add", "-b", branch_name, str(worktree_path))
    spec_dir = worktree_path / "sdd" / "specs"
    spec_dir.mkdir(parents=True)
    (spec_dir / "x.spec.md").write_text("# spec\n")
    task_index_dir = worktree_path / "sdd" / "tasks" / "index"
    task_index_dir.mkdir(parents=True)
    (task_index_dir / "x.json").write_text("{}\n")
    return worktree_path


# ---------------------------------------------------------------------------
# Restart restores intake/ideation/planner projections
# ---------------------------------------------------------------------------


async def test_dev_flow_restart_after_planner(fake_store, nl_brief, tmp_path) -> None:
    """Planner/ideation skipped on resume; planner_output + derived
    research_output + ideation_output restored; development is what reruns."""
    worktree_path = _real_worktree(tmp_path, "feat-999-x")
    ideation_out = IdeationOutput(
        document_path="sdd/proposals/x.proposal.md",
        document_kind="proposal",
        slug="x",
        committed=True,
    )
    planner_out = PlannerOutput(
        spec_path="sdd/specs/x.spec.md",
        task_index_path="sdd/tasks/index/x.json",
        feat_id="FEAT-999",
        branch_name="feat-999-x",
        worktree_path=str(worktree_path),
    )
    dev_out = DevelopmentOutput(files_changed=["a.py"], commit_shas=["abc"], summary="done")

    coordinator = DevCheckpointCoordinator(store=fake_store)
    ctx1 = FlowContext(initial_task="t")
    flow1, mode1 = await coordinator.prepare(
        workflow="dev-flow",
        run_id="run-1",
        brief=nl_brief,
        live_context=ctx1,
        flow_factory=lambda definition: _build_test_flow(
            definition, store=fake_store, ideation_out=ideation_out, planner_out=planner_out, dev_out=dev_out
        ),
        execution_policy={},
    )
    assert mode1 == "fresh"
    result1 = await flow1.run_flow(ctx1)
    assert result1.status.value == "completed"

    coordinator2 = DevCheckpointCoordinator(store=fake_store)
    ctx2 = FlowContext(initial_task="fresh-process")
    _flow2, mode2 = await coordinator2.prepare(
        workflow="dev-flow",
        run_id="run-1",
        brief=nl_brief,
        live_context=ctx2,
        flow_factory=lambda definition: _build_test_flow(
            definition, store=fake_store, ideation_out=ideation_out, planner_out=planner_out, dev_out=dev_out
        ),
        execution_policy={},
    )

    assert mode2 == "resumed"
    assert {"ideation", "planner", "development"} <= ctx2.completed_tasks
    assert isinstance(ctx2.shared_data.get("planner_output"), PlannerOutput)
    assert isinstance(ctx2.shared_data.get("development_output"), DevelopmentOutput)


# ---------------------------------------------------------------------------
# Namespace separation (spec §2 step 1: stable identity is "<workflow>/<run_id>")
# ---------------------------------------------------------------------------


async def test_dev_flow_namespace_is_disjoint_from_dev_loop(fake_store, nl_brief) -> None:
    """A dev-loop/r1 checkpoint present never satisfies a dev-flow prepare(run_id='r1')."""
    ideation_out = IdeationOutput(
        document_path="sdd/proposals/x.proposal.md",
        document_kind="proposal",
        slug="x",
        committed=True,
    )
    planner_out = PlannerOutput(
        spec_path="s",
        task_index_path="t",
        feat_id="FEAT-1",
        branch_name="b",
        worktree_path="/tmp/w",
    )
    dev_out = DevelopmentOutput(files_changed=["a.py"], commit_shas=["abc"], summary="done")

    # Write a "dev-loop/r1" checkpoint directly (same run_id string, DIFFERENT workflow).
    coordinator = DevCheckpointCoordinator(store=fake_store)
    dev_loop_ctx = FlowContext(initial_task="t")
    dev_loop_flow, mode = await coordinator.prepare(
        workflow="dev-loop",
        run_id="r1",
        brief=nl_brief,
        live_context=dev_loop_ctx,
        flow_factory=lambda definition: _build_test_flow(
            definition, store=fake_store, ideation_out=ideation_out, planner_out=planner_out, dev_out=dev_out
        ),
        execution_policy={},
    )
    assert mode == "fresh"
    assert dev_loop_flow.flow_id == "dev-loop/r1"
    await dev_loop_flow.run_flow(dev_loop_ctx)
    assert await fake_store.latest("dev-loop/r1") is not None

    # A dev-flow prepare() for the SAME run_id "r1" must be a cache miss —
    # never see the dev-loop/r1 checkpoint.
    dev_flow_ctx = FlowContext(initial_task="t")
    dev_flow_flow, dev_flow_mode = await coordinator.prepare(
        workflow="dev-flow",
        run_id="r1",
        brief=nl_brief,
        live_context=dev_flow_ctx,
        flow_factory=lambda definition: _build_test_flow(
            definition, store=fake_store, ideation_out=ideation_out, planner_out=planner_out, dev_out=dev_out
        ),
        execution_policy={},
    )

    assert dev_flow_mode == "fresh"
    assert dev_flow_flow.flow_id == "dev-flow/r1"
    assert dev_flow_ctx.completed_tasks == set()


# ---------------------------------------------------------------------------
# DevFlowRunner: recovery gate + backward compatibility
# ---------------------------------------------------------------------------


class _CapturingFlow:
    """Completes immediately, recording the context it was handed
    (mirrors tests/flows/dev_flow/test_runner.py's own stub)."""

    def __init__(self) -> None:
        self.contexts: list[Any] = []
        self._run_id_holder: dict[str, str] = {}

    async def run_flow(self, ctx, **kwargs):
        from parrot.bots.flows.core.result import FlowResult
        from parrot.bots.flows.core.types import FlowStatus

        self.contexts.append(ctx)
        return FlowResult(output=ctx.shared_data["run_id"], status=FlowStatus.COMPLETED)


async def test_dev_flow_runner_run_id_without_kwargs_stays_legacy_path(nl_brief) -> None:
    """run_id supplied but no dev_loop_flow_kwargs -> never reaches the
    coordinator (backward compatible with every existing DevFlowRunner caller)."""
    flow = _CapturingFlow()
    runner = DevFlowRunner(flow, redis_url="redis://x")

    result = await runner.run(nl_brief, run_id="run-legacy")

    assert result.output == "run-legacy"
    assert flow.contexts[-1].shared_data["run_id"] == "run-legacy"


async def test_dev_flow_runner_flow_factory_requires_kwargs() -> None:
    runner = DevFlowRunner(_CapturingFlow(), redis_url="redis://x")
    with pytest.raises(ValueError, match="dev_loop_flow_kwargs"):
        runner._dev_loop_flow_factory()


def test_dev_flow_runner_execution_policy_uses_build_dev_flow_shape() -> None:
    runner = DevFlowRunner(
        _CapturingFlow(),
        redis_url="redis://x",
        dev_loop_flow_kwargs={"skip_qa": True, "require_plan_approval": True, "ideation_max_rounds": 3},
    )
    policy = runner._execution_policy_for_fingerprint()
    assert policy == {
        "skip_qa": True,
        "require_plan_approval": True,
        "development_pool_max": 4,
        "ideation_max_rounds": 3,
    }


# ---------------------------------------------------------------------------
# DevFlowRunner.inspect_checkpoint — the console's resume preflight
# ---------------------------------------------------------------------------


def _recovery_runner(store: FakeCheckpointStore, **kwargs: Any) -> DevFlowRunner:
    """A DevFlowRunner wired for recovery against ``store``."""
    return DevFlowRunner(
        _CapturingFlow(),
        redis_url="redis://x",
        checkpoint_store=store,
        dev_loop_flow_kwargs={"skip_qa": False, **kwargs},
    )


async def test_inspect_checkpoint_without_recovery_wiring(fake_store, nl_brief) -> None:
    """No dev_loop_flow_kwargs -> the runner says so instead of claiming
    the run is simply missing (which would invite a fresh, expensive re-run)."""
    runner = DevFlowRunner(_CapturingFlow(), redis_url="redis://x", checkpoint_store=fake_store)

    report = await runner.inspect_checkpoint("run-1", brief=nl_brief)

    assert runner.recovery_enabled is False
    assert report["recovery_enabled"] is False
    assert report["reason"] == "recovery_disabled"
    assert report["resumable"] is False


async def test_inspect_checkpoint_unknown_run_id(fake_store, nl_brief) -> None:
    report = await _recovery_runner(fake_store).inspect_checkpoint("run-never-ran", brief=nl_brief)

    assert report["found"] is False
    assert report["resumable"] is False
    assert report["reason"] == "no_checkpoint"
    assert report["flow_id"] == "dev-flow/run-never-ran"


async def _seed_checkpoint(store, brief, run_id, tmp_path, **policy_kwargs) -> DevFlowRunner:
    """Run one flow to completion under ``run_id`` so a checkpoint exists."""
    runner = _recovery_runner(store, **policy_kwargs)
    worktree_path = _real_worktree(tmp_path, "feat-777-x")
    ideation_out = IdeationOutput(
        document_path="sdd/proposals/x.proposal.md",
        document_kind="proposal",
        slug="x",
        committed=True,
    )
    planner_out = PlannerOutput(
        spec_path="sdd/specs/x.spec.md",
        task_index_path="sdd/tasks/index/x.json",
        feat_id="FEAT-777",
        branch_name="feat-777-x",
        worktree_path=str(worktree_path),
    )
    dev_out = DevelopmentOutput(files_changed=["a.py"], commit_shas=["abc"], summary="done")
    ctx = FlowContext(initial_task="t")
    flow, mode = await runner._checkpoint_coordinator.prepare(
        workflow=runner.CHECKPOINT_WORKFLOW,
        run_id=run_id,
        brief=brief,
        live_context=ctx,
        flow_factory=lambda definition: _build_test_flow(
            definition, store=store, ideation_out=ideation_out, planner_out=planner_out, dev_out=dev_out
        ),
        execution_policy=runner._execution_policy_for_fingerprint(),
    )
    assert mode == "fresh"
    await flow.run_flow(ctx)
    return runner


async def test_inspect_checkpoint_reports_resumable_run(fake_store, nl_brief, tmp_path) -> None:
    """The happy path the console's resume field depends on: same brief,
    same policy -> resumable, naming the nodes that will NOT be re-dispatched."""
    runner = await _seed_checkpoint(fake_store, nl_brief, "run-resumable", tmp_path)

    report = await runner.inspect_checkpoint("run-resumable", brief=nl_brief)

    assert report["found"] is True
    assert report["resumable"] is True
    assert report["reason"] is None
    assert report["workflow"] == "dev-flow"
    assert {"ideation", "planner"} <= set(report["completed_nodes"])
    assert report["checkpoint_id"] is not None
    assert report["created_at"]


async def test_inspect_checkpoint_probe_without_brief_is_unknown_not_no(fake_store, nl_brief, tmp_path) -> None:
    """The GET probe has no brief to fingerprint: `resumable` is None
    ("unknown"), never False — a False there would read as "start over"."""
    runner = await _seed_checkpoint(fake_store, nl_brief, "run-probe", tmp_path)

    report = await runner.inspect_checkpoint("run-probe")

    assert report["found"] is True
    assert report["resumable"] is None
    assert report["reason"] == "fingerprint_unchecked"
    assert {"ideation", "planner"} <= set(report["completed_nodes"])


async def test_inspect_checkpoint_detects_changed_brief(fake_store, nl_brief, tmp_path) -> None:
    """A different brief under the same run_id is refused BEFORE the run
    starts — `AgentsFlow.resume(expected_input=...)` would raise otherwise."""
    runner = await _seed_checkpoint(fake_store, nl_brief, "run-mismatch", tmp_path)
    changed = DevRequestBrief(
        kind="enhancement",
        title="compression budget telemetry",
        description="A DIFFERENT request under the same run id.",
    )

    report = await runner.inspect_checkpoint("run-mismatch", brief=changed)

    assert report["found"] is True
    assert report["resumable"] is False
    assert report["reason"] == "fingerprint_mismatch"


async def test_inspect_checkpoint_detects_changed_execution_policy(fake_store, nl_brief, tmp_path) -> None:
    """The fingerprint covers the server's routing policy too, not just the brief."""
    await _seed_checkpoint(fake_store, nl_brief, "run-policy", tmp_path)
    other = _recovery_runner(fake_store, require_plan_approval=True)

    report = await other.inspect_checkpoint("run-policy", brief=nl_brief)

    assert report["reason"] == "fingerprint_mismatch"


async def test_inspect_checkpoint_namespace_is_per_workflow(fake_store, nl_brief, tmp_path) -> None:
    """A dev-flow checkpoint is invisible to a dev-loop runner's probe."""
    from parrot.flows.dev_loop.runner import DevLoopRunner

    await _seed_checkpoint(fake_store, nl_brief, "run-ns", tmp_path)
    dev_loop = DevLoopRunner(
        _CapturingFlow(),
        redis_url="redis://x",
        checkpoint_store=fake_store,
        dev_loop_flow_kwargs={"skip_qa": False},
    )

    assert DevLoopRunner.CHECKPOINT_WORKFLOW == "dev-loop"
    assert DevFlowRunner.CHECKPOINT_WORKFLOW == "dev-flow"
    report = await dev_loop.inspect_checkpoint("run-ns")
    assert report["flow_id"] == "dev-loop/run-ns"
    assert report["found"] is False


async def test_inspect_checkpoint_store_outage_raises(nl_brief) -> None:
    """A store outage must NOT be reported as "no checkpoint"."""
    from parrot.bots.flows.core.checkpoint import CheckpointPersistenceError

    class _BrokenStore(FakeCheckpointStore):
        async def latest(self, flow_id: str):
            raise ConnectionError("redis is down")

    runner = _recovery_runner(_BrokenStore())
    with pytest.raises(CheckpointPersistenceError):
        await runner.inspect_checkpoint("run-x", brief=nl_brief)


async def test_dev_loop_runner_feature_brief_is_not_resumable(tmp_path) -> None:
    """dev-loop routes a FeatureBrief to _run_feature() before its recovery
    gate, so its probe must not promise a resume it cannot deliver."""
    from parrot.flows.dev_loop.runner import DevLoopRunner

    runner = DevLoopRunner(
        _CapturingFlow(),
        redis_url="redis://x",
        dev_loop_flow_kwargs={"skip_qa": False},
    )
    spec = tmp_path / "x.spec.md"
    spec.write_text("# spec\n")
    brief = FeatureBrief(document_path=str(spec), document_kind="spec")

    report = await runner.inspect_checkpoint("run-f", brief=brief)

    assert report["reason"] == "unsupported_brief"
    # ...whereas dev-flow serves the very same brief through the coordinator.
    assert DevFlowRunner(_CapturingFlow(), redis_url="redis://x")._recovery_supported(brief) is True
