"""Unit tests for ``parrot.flows.dev_loop.checkpoint.DevCheckpointCoordinator``
(TASK-2625).

Covers: deterministic/mismatching input fingerprints, fresh-vs-resume
selection, live-object-not-restored, shared-state projection round-trip,
recovered-worktree validation failure modes, lease-conflict propagation,
and the structured recovery events (spec §5).
"""
import subprocess
from pathlib import Path
from typing import Any

import pytest
from parrot.bots.flows.core.checkpoint import (
    CheckpointFingerprintMismatchError,
    CheckpointStore,
    FlowCheckpoint,
    FlowLockedError,
    register_checkpoint_type,
)
from parrot.bots.flows.core.context import FlowContext
from parrot.bots.flows.core.fsm import AgentTaskMachine
from parrot.bots.flows.core.node import Node
from parrot.bots.flows.flow.definition import FlowDefinition, NodeDefinition
from parrot.bots.flows.flow.flow import AgentsFlow, register_node
from parrot.flows.dev_loop.checkpoint import (
    DevCheckpointCoordinator,
    RecoveredArtifactError,
    compute_input_fingerprint,
)
from parrot.flows.dev_loop.models import (
    DevelopmentOutput,
    PlannerOutput,
    ResearchOutput,
    WorkBrief,
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
# A trivial explicit-edge graph standing in for the real dev-loop graph
# ---------------------------------------------------------------------------


@register_node("coordinator-test.step")
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


def _build_flow(definition, *, store, shared_data_projector, worktree_path: str = "") -> AgentsFlow:
    """The ``flow_factory`` under test: 'research' -> 'development'."""
    external_definition = FlowDefinition(
        flow="coordinator-test",
        nodes=[
            NodeDefinition(id="research", type="coordinator-test.step"),
            NodeDefinition(id="development", type="coordinator-test.step"),
        ],
        edges=[],
    )
    flow = AgentsFlow(
        name="coordinator-test",
        checkpoint=True,
        checkpoint_store=store,
        checkpoint_required=True,
        checkpoint_definition=external_definition,
        checkpoint_shared_data=shared_data_projector,
    )
    flow.add_node(_StepNode(node_id="research", result=ResearchOutput(
        jira_issue_key="OPS-1",
        spec_path="sdd/specs/x.spec.md",
        feat_id="FEAT-130",
        branch_name="feat-130-x",
        worktree_path=worktree_path,
    )))
    flow.add_node(_StepNode(node_id="development", result=DevelopmentOutput(
        files_changed=["a.py"], commit_shas=["abc123"], summary="did it",
    )))
    flow.add_edge("research", "development", condition="on_success")
    return flow


@pytest.fixture
def fake_store() -> FakeCheckpointStore:
    return FakeCheckpointStore()


@pytest.fixture
def sample_brief() -> WorkBrief:
    return WorkBrief(
        summary="Customer sync drops the last row",
        affected_component="etl/customers/sync.yaml",
        acceptance_criteria=[
            {"kind": "shell", "name": "lint", "command": "ruff check ."},
        ],
        escalation_assignee="acc-1",
        reporter="acc-2",
    )


@pytest.fixture(autouse=True)
def _register_dev_loop_types() -> None:
    """Simulate the module-level registration TASK-2626 will add.

    Registration itself is out of scope for this task (spec Module 4) —
    this fixture exercises the read-side projection/restoration logic
    exactly as it will run once that registration exists.
    """
    register_checkpoint_type(WorkBrief)
    register_checkpoint_type(ResearchOutput)
    register_checkpoint_type(PlannerOutput)
    register_checkpoint_type(DevelopmentOutput)


# ---------------------------------------------------------------------------
# Fingerprint determinism / mismatch
# ---------------------------------------------------------------------------


def test_fingerprint_is_deterministic(sample_brief) -> None:
    policy = {"qa_required": True, "pool_size": 2}
    fp1 = compute_input_fingerprint(workflow="dev-loop", brief=sample_brief, repository="r", execution_policy=policy)
    fp2 = compute_input_fingerprint(
        workflow="dev-loop", brief=sample_brief.model_copy(), repository="r", execution_policy=dict(policy)
    )
    assert fp1 == fp2

    other_brief = sample_brief.model_copy(update={"summary": "A totally different incident summary here"})
    fp3 = compute_input_fingerprint(workflow="dev-loop", brief=other_brief, repository="r", execution_policy=policy)
    assert fp1 != fp3


def test_fingerprint_changes_with_topology_or_policy(sample_brief) -> None:
    base = compute_input_fingerprint(
        workflow="dev-loop", brief=sample_brief, repository="r", execution_policy={"qa_required": True}
    )
    different_policy = compute_input_fingerprint(
        workflow="dev-loop", brief=sample_brief, repository="r", execution_policy={"qa_required": False}
    )
    different_repo = compute_input_fingerprint(
        workflow="dev-loop", brief=sample_brief, repository="other-repo", execution_policy={"qa_required": True}
    )
    assert base != different_policy
    assert base != different_repo


# ---------------------------------------------------------------------------
# prepare(): fresh (cache miss)
# ---------------------------------------------------------------------------


async def test_prepare_cache_miss_builds_fresh_flow(fake_store, sample_brief, caplog) -> None:
    coordinator = DevCheckpointCoordinator(store=fake_store)
    ctx = FlowContext(initial_task="t")

    with caplog.at_level("INFO", logger="parrot.flows.dev_loop.checkpoint"):
        flow, mode = await coordinator.prepare(
            workflow="dev-loop",
            run_id="run-1",
            brief=sample_brief,
            live_context=ctx,
            flow_factory=lambda definition: _build_flow(definition, store=fake_store, shared_data_projector=None),
            execution_policy={},
        )

    assert mode == "fresh"
    assert flow.flow_id == "dev-loop/run-1"
    assert flow._checkpoint_input_arg is not None
    assert flow._checkpoint_input_arg.workflow == "dev-loop"
    assert any("cache_miss" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# prepare(): resume + fingerprint mismatch
# ---------------------------------------------------------------------------


async def _run_to_checkpoint(fake_store, sample_brief, worktree_path: str, flow_id: str = "dev-loop/run-2"):
    """Run the coordinator's fresh path to completion, leaving a checkpoint."""
    coordinator = DevCheckpointCoordinator(store=fake_store)
    ctx = FlowContext(initial_task="t")
    flow, _mode = await coordinator.prepare(
        workflow="dev-loop",
        run_id=flow_id.split("/", 1)[1],
        brief=sample_brief,
        live_context=ctx,
        flow_factory=lambda definition: _build_flow(
            definition, store=fake_store, shared_data_projector=None, worktree_path=worktree_path
        ),
        execution_policy={},
    )
    result = await flow.run_flow(ctx)
    assert result.status.value == "completed"
    return coordinator


async def test_same_run_id_different_input_rejected(fake_store, sample_brief, tmp_path) -> None:
    await _run_to_checkpoint(fake_store, sample_brief, str(tmp_path))

    changed_brief = sample_brief.model_copy(update={"summary": "A completely different incident happened"})
    coordinator2 = DevCheckpointCoordinator(store=fake_store)
    with pytest.raises(CheckpointFingerprintMismatchError):
        await coordinator2.prepare(
            workflow="dev-loop",
            run_id="run-2",
            brief=changed_brief,
            live_context=FlowContext(initial_task="t"),
            flow_factory=lambda definition: _build_flow(definition, store=fake_store, shared_data_projector=None),
            execution_policy={},
        )


async def test_resume_matching_input_restores_shared_state(fake_store, sample_brief, real_worktree) -> None:
    await _run_to_checkpoint(fake_store, sample_brief, real_worktree)

    resumed_ctx = FlowContext(initial_task="fresh-process")
    coordinator2 = DevCheckpointCoordinator(store=fake_store)
    _flow, mode = await coordinator2.prepare(
        workflow="dev-loop",
        run_id="run-2",
        brief=sample_brief,
        live_context=resumed_ctx,
        flow_factory=lambda definition: _build_flow(
            definition, store=fake_store, shared_data_projector=None, worktree_path=real_worktree
        ),
        execution_policy={},
    )

    assert mode == "resumed"
    assert "research_output" in resumed_ctx.shared_data
    assert isinstance(resumed_ctx.shared_data["research_output"], ResearchOutput)
    assert "development_output" in resumed_ctx.shared_data
    assert isinstance(resumed_ctx.shared_data["development_output"], DevelopmentOutput)
    assert {"research", "development"} <= resumed_ctx.completed_tasks


# ---------------------------------------------------------------------------
# Live objects are never overwritten by checkpoint data
# ---------------------------------------------------------------------------


async def test_live_shared_objects_are_not_restored(fake_store, sample_brief, tmp_path) -> None:
    await _run_to_checkpoint(fake_store, sample_brief, str(tmp_path))

    live_session_host = object()
    resumed_ctx = FlowContext(initial_task="fresh-process")
    resumed_ctx.shared_data["session_host"] = live_session_host
    # A live value already present for an allowlisted key must win too.
    live_research_output = object()
    resumed_ctx.shared_data["research_output"] = live_research_output

    coordinator2 = DevCheckpointCoordinator(store=fake_store)
    await coordinator2.prepare(
        workflow="dev-loop",
        run_id="run-2",
        brief=sample_brief,
        live_context=resumed_ctx,
        flow_factory=lambda definition: _build_flow(definition, store=fake_store, shared_data_projector=None),
        execution_policy={},
    )

    assert resumed_ctx.shared_data["session_host"] is live_session_host
    assert resumed_ctx.shared_data["research_output"] is live_research_output


# ---------------------------------------------------------------------------
# Recovered-worktree validation
# ---------------------------------------------------------------------------


def _git(repo, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def real_worktree(tmp_path):
    """A real repo + a real `git worktree add`-registered secondary worktree."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    (repo / "f.txt").write_text("x")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "init")

    worktree_path = tmp_path / "wt"
    _git(repo, "worktree", "add", "-b", "feat-130-x", str(worktree_path))
    # Matches _build_flow()'s hardcoded ResearchOutput.spec_path.
    spec_dir = worktree_path / "sdd" / "specs"
    spec_dir.mkdir(parents=True)
    (spec_dir / "x.spec.md").write_text("# spec\n")
    return str(worktree_path)


async def test_recovered_worktree_requires_expected_branch(fake_store, sample_brief, real_worktree) -> None:
    """A worktree on the WRONG branch fails validation explicitly."""
    from parrot.flows.dev_loop.checkpoint import _verify_recovered_worktree

    # Correct branch passes.
    await _verify_recovered_worktree(real_worktree, "feat-130-x")

    # Wrong branch raises.
    with pytest.raises(RecoveredArtifactError, match="expected"):
        await _verify_recovered_worktree(real_worktree, "some-other-branch")


async def test_recovered_worktree_missing_path_raises(tmp_path) -> None:
    from parrot.flows.dev_loop.checkpoint import _verify_recovered_worktree

    missing = str(tmp_path / "does-not-exist")
    with pytest.raises(RecoveredArtifactError, match="does not exist"):
        await _verify_recovered_worktree(missing, "feat-130-x")


async def test_recovered_worktree_unregistered_path_raises(real_worktree) -> None:
    from parrot.flows.dev_loop.checkpoint import _verify_recovered_worktree

    # A directory that exists and is inside a real repo (so `git worktree
    # list` succeeds) but was never itself `git worktree add`-ed.
    stale = Path(real_worktree).parent / "repo" / "stale_subdir"
    stale.mkdir()
    with pytest.raises(RecoveredArtifactError, match="not a registered"):
        await _verify_recovered_worktree(str(stale), "feat-130-x")


async def test_prepare_fails_on_invalid_recovered_worktree(fake_store, sample_brief, tmp_path, caplog) -> None:
    """End-to-end: a resumed run whose worktree vanished fails prepare()."""
    vanished_path = tmp_path / "vanished"
    vanished_path.mkdir()
    await _run_to_checkpoint(fake_store, sample_brief, str(vanished_path))
    # Simulate the worktree being removed between runs.
    vanished_path.rmdir()

    coordinator2 = DevCheckpointCoordinator(store=fake_store)
    with (
        caplog.at_level("INFO", logger="parrot.flows.dev_loop.checkpoint"),
        pytest.raises(RecoveredArtifactError),
    ):
        await coordinator2.prepare(
            workflow="dev-loop",
            run_id="run-2",
            brief=sample_brief,
            live_context=FlowContext(initial_task="t"),
            flow_factory=lambda definition: _build_flow(
                definition, store=fake_store, shared_data_projector=None
            ),
            execution_policy={},
        )
    assert any("artifact_validation_failure" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Lease conflict
# ---------------------------------------------------------------------------


async def test_lease_conflict_on_concurrent_prepare_raises(fake_store, sample_brief, tmp_path, caplog) -> None:
    await _run_to_checkpoint(fake_store, sample_brief, str(tmp_path))
    # Simulate another process already holding the resume lease.
    await fake_store.acquire_lease("dev-loop/run-2", "other-holder")

    coordinator2 = DevCheckpointCoordinator(store=fake_store)
    with (
        caplog.at_level("INFO", logger="parrot.flows.dev_loop.checkpoint"),
        pytest.raises(FlowLockedError),
    ):
        await coordinator2.prepare(
            workflow="dev-loop",
            run_id="run-2",
            brief=sample_brief,
            live_context=FlowContext(initial_task="t"),
            flow_factory=lambda definition: _build_flow(
                definition, store=fake_store, shared_data_projector=None
            ),
            execution_policy={},
        )
    assert any("lease_conflict" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Structured events (spec §5) — the ones prepare() emits directly
# ---------------------------------------------------------------------------


def test_emit_recovery_event_is_public_and_structured(caplog) -> None:
    coordinator = DevCheckpointCoordinator()
    with caplog.at_level("INFO", logger="parrot.flows.dev_loop.checkpoint"):
        coordinator.emit_recovery_event("checkpoint_committed", flow_id="dev-loop/r1", node_id="research")
        coordinator.emit_recovery_event("node_rerun", flow_id="dev-loop/r1", node_id="development")

    messages = [r.message for r in caplog.records]
    assert any("checkpoint_committed" in m for m in messages)
    assert any("node_rerun" in m for m in messages)
