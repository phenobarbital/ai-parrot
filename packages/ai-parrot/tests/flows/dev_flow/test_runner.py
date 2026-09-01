"""Unit tests for DevFlowRunner (FEAT-412, TASK-2128).

Drives the real ``DevFlowRunner`` (and therefore the inherited
``DevLoopRunner`` hosting machinery: session host, actions sink, semaphore,
gates, park/resume) through **stub flows**, matching
``test_runner_park.py``/``test_runner_host.py``'s harness — the node graph is
orthogonal to what this task changed.

Focus: brief typing, context seeding, single-topology guarantee, and that
gates/park/resume still work through the subclass.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from parrot import conf
from parrot.bots.flows.core.checkpoint import CheckpointStore, FlowCheckpoint
from parrot.bots.flows.core.result import FlowResult
from parrot.bots.flows.core.types import FlowStatus
from parrot.flows.dev_flow.model_plan import DevFlowModelPlan
from parrot.flows.dev_flow.models import DevRequestBrief
from parrot.flows.dev_flow.runner import DevFlowRunner
from parrot.flows.dev_loop.models import FeatureBrief


class _CapturingFlow:
    """Completes immediately, recording the context it was handed."""

    def __init__(self) -> None:
        self.contexts: list[Any] = []
        self._run_id_holder: dict[str, str] = {}

    async def run_flow(self, ctx, **kwargs) -> FlowResult:
        self.contexts.append(ctx)
        return FlowResult(
            output=ctx.shared_data["run_id"], status=FlowStatus.COMPLETED
        )

    @property
    def shared(self) -> dict[str, Any]:
        return self.contexts[-1].shared_data


class _GateOpeningFlow:
    """Opens an `open_questions` gate and blocks on it, like IdeationNode."""

    def __init__(self, *, post_gate_delay: float = 0.05) -> None:
        self._post_gate_delay = post_gate_delay
        self.gate_ids: dict[str, str] = {}

    async def run_flow(self, ctx, **kwargs) -> FlowResult:
        run_id = ctx.shared_data["run_id"]
        host = ctx.shared_data["session_host"]
        gate_id, _ = host.open_gate(
            kind="open_questions", node_id="ideation", title="Open questions",
            questions=["Which store?"], ttl_seconds=None, on_expiry="fail",
        )
        self.gate_ids[run_id] = gate_id
        gate = await host.wait_gate(gate_id)
        if self._post_gate_delay:
            await asyncio.sleep(self._post_gate_delay)
        if gate.status != "approved":
            return FlowResult(output=run_id, status=FlowStatus.FAILED)
        ctx.shared_data["answers_seen"] = dict(gate.answers)
        return FlowResult(output=run_id, status=FlowStatus.COMPLETED)


@pytest.fixture
def nl_brief() -> DevRequestBrief:
    return DevRequestBrief(
        kind="enhancement",
        title="compression budget telemetry",
        description="Add per-tool telemetry to the compression budget.",
    )


@pytest.fixture
def doc_brief(tmp_path) -> FeatureBrief:
    doc = tmp_path / "idea.proposal.md"
    doc.write_text("# Proposal", encoding="utf-8")
    return FeatureBrief(document_path=str(doc), document_kind="proposal")


def _runner(flow, **kwargs) -> DevFlowRunner:
    return DevFlowRunner(flow, redis_url="redis://x", **kwargs)


# ---------------------------------------------------------------------------
# Brief typing + seeding
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_accepts_dev_request_brief(nl_brief):
    flow = _CapturingFlow()
    result = await _runner(flow).run(nl_brief)

    assert result.status == FlowStatus.COMPLETED
    shared = flow.shared
    assert shared["dev_brief"] is nl_brief
    assert shared["run_id"].startswith("run-")
    assert shared["session_host"] is not None
    # A natural-language run must NOT pre-seed feature_brief — IdeationNode
    # produces it.
    assert "feature_brief" not in shared


@pytest.mark.asyncio
async def test_run_accepts_feature_brief_seeds_feature_key(doc_brief):
    flow = _CapturingFlow()
    await _runner(flow).run(doc_brief)

    shared = flow.shared
    assert shared["dev_brief"] is doc_brief
    assert shared["feature_brief"] is doc_brief


@pytest.mark.asyncio
async def test_never_seeds_bug_mode_keys(nl_brief, doc_brief):
    for brief in (nl_brief, doc_brief):
        flow = _CapturingFlow()
        await _runner(flow).run(brief)
        assert "bug_brief" not in flow.shared
        assert "work_brief" not in flow.shared


@pytest.mark.asyncio
async def test_rejects_non_dev_flow_brief():
    from parrot.flows.dev_loop.models import ShellCriterion, WorkBrief

    flow = _CapturingFlow()
    work = WorkBrief(
        summary="Customer sync drops the last row",
        affected_component="etl/customers/sync.yaml",
        log_sources=[],
        acceptance_criteria=[ShellCriterion(name="lint", command="ruff check .")],
        escalation_assignee="557058:abc",
        reporter="557058:def",
    )
    with pytest.raises(TypeError, match="DevRequestBrief or FeatureBrief"):
        await _runner(flow).run(work)
    # Nothing was executed.
    assert flow.contexts == []


# ---------------------------------------------------------------------------
# run_id / initial_task / extra_shared
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_explicit_run_id_is_used(nl_brief):
    flow = _CapturingFlow()
    await _runner(flow).run(nl_brief, run_id="run-explicit")
    assert flow.shared["run_id"] == "run-explicit"
    # The flow's event-publisher holder is pointed at this run.
    assert flow._run_id_holder["run_id"] == "run-explicit"


@pytest.mark.asyncio
async def test_initial_task_defaults_per_kind(nl_brief, doc_brief):
    flow = _CapturingFlow()
    await _runner(flow).run(nl_brief)
    assert flow.contexts[-1].initial_task == "compression budget telemetry"

    flow2 = _CapturingFlow()
    await _runner(flow2).run(doc_brief)
    assert flow2.contexts[-1].initial_task.startswith("Feature: ")


@pytest.mark.asyncio
async def test_initial_task_passthrough(nl_brief):
    flow = _CapturingFlow()
    await _runner(flow).run(nl_brief, initial_task="custom line")
    assert flow.contexts[-1].initial_task == "custom line"


@pytest.mark.asyncio
async def test_extra_shared_passthrough(nl_brief):
    """The server's per-run knobs must reach shared state."""
    flow = _CapturingFlow()
    await _runner(flow).run(
        nl_brief,
        extra_shared={"require_plan_approval": True, "skip_qa": True},
    )
    assert flow.shared["require_plan_approval"] is True
    assert flow.shared["skip_qa"] is True


@pytest.mark.asyncio
async def test_extra_shared_cannot_be_used_to_drop_core_keys(nl_brief):
    """extra_shared merges last, but the core keys are still present."""
    flow = _CapturingFlow()
    await _runner(flow).run(nl_brief, extra_shared={"unrelated": 1})
    for key in ("dev_brief", "run_id", "session_host"):
        assert key in flow.shared


# ---------------------------------------------------------------------------
# Single topology
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_never_calls_run_feature(doc_brief, monkeypatch):
    """A FeatureBrief runs the DEV-FLOW graph, not FEAT-378 feature-mode."""
    flow = _CapturingFlow()
    runner = _runner(flow)

    async def _boom(*args, **kwargs):
        raise AssertionError("_run_feature must never be called by DevFlowRunner")

    monkeypatch.setattr(runner, "_run_feature", _boom)

    await runner.run(doc_brief)

    assert len(flow.contexts) == 1
    # The base class's feature-flow cache stays untouched/unused.
    assert runner._feature_flow is None


@pytest.mark.asyncio
async def test_both_kinds_use_the_same_flow_object(nl_brief, doc_brief):
    flow = _CapturingFlow()
    runner = _runner(flow)
    await runner.run(nl_brief)
    await runner.run(doc_brief)
    assert len(flow.contexts) == 2
    assert runner._rev_flow is None
    assert runner._feature_flow is None


# ---------------------------------------------------------------------------
# Inherited session-state / registry behavior
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_created_work_kind_maps_per_brief(nl_brief, doc_brief):
    flow = _CapturingFlow()
    runner = _runner(flow)

    await runner.run(nl_brief, run_id="run-nl")
    # The host is discarded at close, so read the projected registry instead.
    assert runner.registry_state.runs["run-nl"].work_kind == "enhancement"

    new_feature = nl_brief.model_copy(update={"kind": "new_feature"})
    await runner.run(new_feature, run_id="run-nf")
    assert runner.registry_state.runs["run-nf"].work_kind == "new_feature"

    # A document brief uses the "bug" structural placeholder (work_kind is a
    # closed Literal that deliberately has no "feature" member).
    await runner.run(doc_brief, run_id="run-doc")
    assert runner.registry_state.runs["run-doc"].work_kind == "bug"


@pytest.mark.asyncio
async def test_run_registered_in_root_registry(nl_brief):
    flow = _CapturingFlow()
    runner = _runner(flow)
    await runner.run(nl_brief, run_id="run-reg")

    summary = runner.registry_state.runs["run-reg"]
    assert summary.run_id == "run-reg"
    assert summary.summary == "compression budget telemetry"


@pytest.mark.asyncio
async def test_session_host_seeded_and_closed(nl_brief):
    flow = _CapturingFlow()
    runner = _runner(flow)
    await runner.run(nl_brief, run_id="run-host")

    # Seeded during the run...
    assert flow.shared["session_host"] is not None
    # ...and discarded afterwards (inherited _close_host behavior).
    assert runner.get_host("run-host") is None


@pytest.mark.asyncio
async def test_slot_released_after_run(nl_brief):
    flow = _CapturingFlow()
    runner = _runner(flow, max_concurrent_runs=1)
    await runner.run(nl_brief)
    assert runner.active_runs == set()
    # A second run still fits.
    await runner.run(nl_brief)
    assert runner.active_runs == set()


@pytest.mark.asyncio
async def test_slot_released_when_flow_raises(nl_brief):
    class _BoomFlow:
        def __init__(self) -> None:
            self._run_id_holder: dict[str, str] = {}

        async def run_flow(self, ctx, **kwargs):
            raise RuntimeError("node exploded")

    runner = _runner(_BoomFlow(), max_concurrent_runs=1)
    with pytest.raises(RuntimeError, match="node exploded"):
        await runner.run(nl_brief)
    assert runner.active_runs == set()


# ---------------------------------------------------------------------------
# Gates + park/resume through the subclass
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_open_questions_gate_resolves_via_inherited_api(nl_brief):
    flow = _GateOpeningFlow()
    runner = _runner(flow)

    async def _answer():
        await asyncio.sleep(0.02)
        gate_id = flow.gate_ids["run-gate"]
        await runner.resolve_gate(
            "run-gate", gate_id, "approved", "alice", "",
            None, answers={"Which store?": "pgvector"},
        )

    answerer = asyncio.ensure_future(_answer())
    result = await runner.run(nl_brief, run_id="run-gate")
    await answerer

    assert result.status == FlowStatus.COMPLETED


@pytest.mark.asyncio
async def test_parked_run_frees_its_slot(nl_brief, monkeypatch):
    """An ideation gate can park for hours — the slot must be released."""
    monkeypatch.setattr(conf, "DEV_LOOP_GATE_PARK", True, raising=False)
    gate_flow = _GateOpeningFlow()
    runner = _runner(gate_flow, max_concurrent_runs=1)

    parked = asyncio.ensure_future(runner.run(nl_brief, run_id="run-parked"))
    # Let the gate open and the park happen.
    for _ in range(50):
        await asyncio.sleep(0.01)
        if "run-parked" in runner.parked_runs:
            break

    assert "run-parked" in runner.parked_runs
    assert runner.active_runs == set()  # slot genuinely free

    gate_id = gate_flow.gate_ids["run-parked"]
    await runner.resolve_gate(
        "run-parked", gate_id, "approved", "alice", "", None,
        answers={"Which store?": "pgvector"},
    )
    result = await parked
    assert result.status == FlowStatus.COMPLETED


@pytest.mark.asyncio
async def test_rejected_gate_fails_the_run(nl_brief):
    flow = _GateOpeningFlow()
    runner = _runner(flow)

    async def _reject():
        await asyncio.sleep(0.02)
        gate_id = flow.gate_ids["run-rej"]
        await runner.resolve_gate(
            "run-rej", gate_id, "rejected", "bob", "aborting", None,
        )

    rejecter = asyncio.ensure_future(_reject())
    result = await runner.run(nl_brief, run_id="run-rej")
    await rejecter

    assert result.status == FlowStatus.FAILED


# ---------------------------------------------------------------------------
# FEAT-490 TASK-2686: per-run model_plan on DevFlowRunner.run
# ---------------------------------------------------------------------------


class _FakeCheckpointStore(CheckpointStore):
    """Minimal in-memory ``CheckpointStore`` — always a cache miss for a
    run_id it has never seen (which every run below uses fresh)."""

    def __init__(self) -> None:
        self._by_flow: dict[str, list[FlowCheckpoint]] = {}
        self._leases: dict[str, str] = {}

    async def put(self, checkpoint: FlowCheckpoint) -> None:
        self._by_flow.setdefault(checkpoint.flow_id, []).append(checkpoint)

    async def latest(self, flow_id: str):
        history = self._by_flow.get(flow_id, [])
        return history[-1] if history else None

    async def get(self, flow_id: str, checkpoint_id: int):
        return None

    async def history(self, flow_id: str, limit: int = 10):
        return []

    async def list_flows(self, status=None):
        return []

    async def delete_flow(self, flow_id: str) -> None:
        self._by_flow.pop(flow_id, None)

    async def acquire_lease(self, flow_id: str, holder: str, ttl: int = 60) -> bool:
        return True

    async def renew_lease(self, flow_id: str, holder: str, ttl: int = 60) -> bool:
        return True

    async def release_lease(self, flow_id: str, holder: str) -> None:
        pass

    async def close(self) -> None:
        pass


def _plan(**kwargs) -> DevFlowModelPlan:
    kwargs.setdefault("research_primary", "zai.glm-5")
    return DevFlowModelPlan(**kwargs)


def _patched_build_dev_flow(captured: list[dict]):
    """A drop-in replacement for ``build_dev_flow`` that records its kwargs
    and returns a stub flow completing immediately."""

    def _fake(**kwargs):
        captured.append(kwargs)
        return _CapturingFlow()

    return _fake


def _recovery_runner(**dev_loop_flow_kwargs) -> DevFlowRunner:
    return DevFlowRunner(
        _CapturingFlow(),
        redis_url="redis://x",
        checkpoint_store=_FakeCheckpointStore(),
        dev_loop_flow_kwargs={"dispatcher": MagicMock(), "redis_url": "redis://x", **dev_loop_flow_kwargs},
    )


@pytest.mark.asyncio
async def test_run_without_plan_is_byte_identical(nl_brief):
    """No ``model_plan`` -> ``build_dev_flow`` receives exactly today's kwargs."""
    captured: list[dict] = []
    target_globals = DevFlowRunner._dev_loop_flow_factory.__globals__
    original = target_globals["build_dev_flow"]
    target_globals["build_dev_flow"] = _patched_build_dev_flow(captured)
    try:
        runner = _recovery_runner()
        result = await runner.run(nl_brief, run_id="run-no-plan")
    finally:
        target_globals["build_dev_flow"] = original

    assert result.status == FlowStatus.COMPLETED
    assert len(captured) == 1
    assert "model_plan" not in captured[0]
    assert result.metadata["model_plan_requested"] is None


@pytest.mark.asyncio
async def test_per_run_plan_reaches_build_dev_flow(nl_brief):
    """A submitted plan appears in the factory's ``model_plan`` kwarg."""
    captured: list[dict] = []
    plan = _plan()
    target_globals = DevFlowRunner._dev_loop_flow_factory.__globals__
    original = target_globals["build_dev_flow"]
    target_globals["build_dev_flow"] = _patched_build_dev_flow(captured)
    try:
        runner = _recovery_runner()
        result = await runner.run(nl_brief, run_id="run-with-plan", model_plan=plan)
    finally:
        target_globals["build_dev_flow"] = original

    assert len(captured) == 1
    assert captured[0]["model_plan"] is plan
    assert result.metadata["model_plan_requested"] == plan.model_dump(mode="json")


@pytest.mark.asyncio
async def test_plan_is_not_stored_on_the_instance(nl_brief):
    """Inspect the runner after a run: no per-run plan left behind on ``self``."""
    plan = _plan()
    target_globals = DevFlowRunner._dev_loop_flow_factory.__globals__
    original = target_globals["build_dev_flow"]
    target_globals["build_dev_flow"] = _patched_build_dev_flow([])
    try:
        runner = _recovery_runner()
        await runner.run(nl_brief, run_id="run-plan-not-stored", model_plan=plan)
    finally:
        target_globals["build_dev_flow"] = original

    assert "model_plan" not in runner._dev_loop_flow_kwargs
    assert not hasattr(runner, "_model_plan")
    assert not hasattr(runner, "_current_model_plan")


def test_concurrent_runs_do_not_leak_seats():
    """Two closures built back-to-back with different plans each build with
    their own — the per-call closure is what makes concurrent runs safe."""
    captured: list[dict] = []
    plan_a = _plan(research_primary="zai.glm-5")
    plan_b = _plan(research_primary="qwen.qwen3-coder-480b-a35b-v1:0")
    target_globals = DevFlowRunner._dev_loop_flow_factory.__globals__
    original = target_globals["build_dev_flow"]
    target_globals["build_dev_flow"] = _patched_build_dev_flow(captured)
    try:
        runner = _recovery_runner()
        factory_a = runner._dev_loop_flow_factory({"model_plan": plan_a})
        factory_b = runner._dev_loop_flow_factory({"model_plan": plan_b})
        factory_a(None)
        factory_b(None)
    finally:
        target_globals["build_dev_flow"] = original

    assert captured[0]["model_plan"] is plan_a
    assert captured[1]["model_plan"] is plan_b


# ---------------------------------------------------------------------------
# FEAT-490 TASK-2687: a resumed run keeps the seats it was created with
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resumed_run_keeps_original_seats(nl_brief):
    """On ``mode == "resumed"``, DevCheckpointCoordinator.prepare() returns
    the ALREADY-RESUMED flow directly — the newly submitted plan is never
    threaded into a rebuild (there is no rebuild on this branch)."""
    resumed_flow = _CapturingFlow()
    plan = _plan()
    runner = _recovery_runner()
    runner._checkpoint_coordinator.prepare = AsyncMock(return_value=(resumed_flow, "resumed"))

    result = await runner.run(nl_brief, run_id="run-resumed", model_plan=plan)

    assert result.status == FlowStatus.COMPLETED
    # The coordinator's own returned flow object ran — not a fresh one.
    assert resumed_flow.contexts


@pytest.mark.asyncio
async def test_resumed_run_reports_the_plan_as_not_applied(nl_brief):
    """A resumed run reports the submitted plan as requested-but-not-applied,
    never silently swapped in (spec §8 Q1)."""
    resumed_flow = _CapturingFlow()
    plan = _plan()
    runner = _recovery_runner()
    runner._checkpoint_coordinator.prepare = AsyncMock(return_value=(resumed_flow, "resumed"))

    result = await runner.run(nl_brief, run_id="run-resumed-report", model_plan=plan)

    assert result.metadata["run_mode"] == "resumed"
    assert result.metadata["model_plan_requested"] == plan.model_dump(mode="json")
    assert result.metadata["model_plan_effective"] is None


@pytest.mark.asyncio
async def test_fresh_run_reports_the_plan_as_applied(nl_brief):
    """Symmetric control: a fresh run's effective plan IS the requested one."""
    captured: list[dict] = []
    plan = _plan()
    target_globals = DevFlowRunner._dev_loop_flow_factory.__globals__
    original = target_globals["build_dev_flow"]
    target_globals["build_dev_flow"] = _patched_build_dev_flow(captured)
    try:
        runner = _recovery_runner()
        result = await runner.run(nl_brief, run_id="run-fresh-report", model_plan=plan)
    finally:
        target_globals["build_dev_flow"] = original

    assert result.metadata["run_mode"] == "fresh"
    assert result.metadata["model_plan_effective"] == plan.model_dump(mode="json")


@pytest.mark.asyncio
async def test_per_run_plan_does_not_move_the_fingerprint(nl_brief):
    """Accepted limitation (spec §7), asserted rather than assumed: the
    checkpoint fingerprint's execution_policy is identical across two runs
    with DIFFERENT per-run plans — it derives solely from construction-time
    ``self._dev_loop_flow_kwargs``, never from a per-run call argument."""
    captured_policies: list[dict] = []

    class _RecordingCoordinator:
        async def prepare(self, *, execution_policy, **kwargs):
            captured_policies.append(execution_policy)
            return _CapturingFlow(), "fresh"

    runner = _recovery_runner()
    runner._checkpoint_coordinator = _RecordingCoordinator()

    await runner.run(nl_brief, run_id="run-fp-a", model_plan=_plan(research_primary="zai.glm-5"))
    await runner.run(
        nl_brief,
        run_id="run-fp-b",
        model_plan=_plan(research_primary="qwen.qwen3-coder-480b-a35b-v1:0"),
    )

    assert len(captured_policies) == 2
    assert captured_policies[0] == captured_policies[1]
    # Construction time never supplied a model_plan either, so the key is
    # absent entirely — pinning that a PER-RUN plan cannot introduce it.
    assert "model_plan" not in captured_policies[0]


def test_execution_policy_for_fingerprint_is_unmodified_by_this_feature():
    """Structural guard: `_execution_policy_for_fingerprint` still takes no
    per-run argument at all (spec §8 Q2' — left alone on purpose)."""
    import inspect

    sig = inspect.signature(DevFlowRunner._execution_policy_for_fingerprint)
    assert list(sig.parameters) == ["self"]


# ---------------------------------------------------------------------------
# FEAT-490 post-review fix: overrides must NOT reach a RESUMED run's rebuild
# ---------------------------------------------------------------------------
#
# CRITICAL bug found by adversarial review: `AgentsFlow.resume()`
# (bots/flows/flow/flow.py:1556) calls `flow_factory(checkpoint.definition)`
# — the SAME closure `_dev_loop_flow_factory()` returns, and never `None` —
# to rebuild a RESUMED run's topology. The original implementation merged
# `overrides` (e.g. a per-run `model_plan`) into `kwargs` before returning
# the closure, so it silently reached a resumed run's rebuild too — every
# `test_resumed_run_*` test above mocks `_checkpoint_coordinator.prepare()`
# directly and therefore never invoked the real closure with a non-None
# definition, so none of them could have caught this. Fixed by gating the
# merge on `_definition is None` INSIDE the closure. These tests drive the
# closure with both call shapes directly — the same signal the real
# coordinator/`AgentsFlow.resume()` use.


def test_overrides_apply_on_the_fresh_definition_none_call() -> None:
    """`factory(None)` — the cache-miss/fresh signal — still applies
    overrides (regression guard: the fix must not disable the fresh path)."""
    captured: list[dict] = []
    plan = _plan()
    target_globals = DevFlowRunner._dev_loop_flow_factory.__globals__
    original = target_globals["build_dev_flow"]
    target_globals["build_dev_flow"] = _patched_build_dev_flow(captured)
    try:
        runner = _recovery_runner()
        factory = runner._dev_loop_flow_factory({"model_plan": plan})
        factory(None)
    finally:
        target_globals["build_dev_flow"] = original

    assert captured[0]["model_plan"] is plan


def test_overrides_do_not_reach_a_resumed_rebuild() -> None:
    """`factory(<a real definition, i.e. what AgentsFlow.resume() passes>)`
    — the exact call shape `AgentsFlow.resume()` uses
    (`flow_factory(checkpoint.definition)`) — must build with ONLY the
    construction-time kwargs, never the per-run override. This is the
    precise regression guard: before the fix, this assertion failed."""
    captured: list[dict] = []
    plan = _plan()
    target_globals = DevFlowRunner._dev_loop_flow_factory.__globals__
    original = target_globals["build_dev_flow"]
    target_globals["build_dev_flow"] = _patched_build_dev_flow(captured)
    try:
        runner = _recovery_runner()
        factory = runner._dev_loop_flow_factory({"model_plan": plan})
        # A stand-in for `checkpoint.definition` — any non-None object is
        # the correct signal; AgentsFlow.resume() never passes None here.
        sentinel_definition = object()
        factory(sentinel_definition)
    finally:
        target_globals["build_dev_flow"] = original

    assert "model_plan" not in captured[0]


def test_same_closure_applies_the_plan_only_to_its_fresh_call() -> None:
    """A single closure instance, called first fresh then as-if-resuming —
    mirrors `prepare()` calling the SAME closure it built once per `run()`
    invocation. Only the `_definition is None` call sees the plan."""
    captured: list[dict] = []
    plan = _plan()
    target_globals = DevFlowRunner._dev_loop_flow_factory.__globals__
    original = target_globals["build_dev_flow"]
    target_globals["build_dev_flow"] = _patched_build_dev_flow(captured)
    try:
        runner = _recovery_runner()
        factory = runner._dev_loop_flow_factory({"model_plan": plan})
        factory(None)
        factory(object())
    finally:
        target_globals["build_dev_flow"] = original

    assert captured[0]["model_plan"] is plan
    assert "model_plan" not in captured[1]
