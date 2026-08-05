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

import pytest
from parrot import conf
from parrot.bots.flows.core.result import FlowResult
from parrot.bots.flows.core.types import FlowStatus
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
