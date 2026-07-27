"""Gate park/resume unit tests for DevLoopRunner (FEAT-377 TASK-1917).

Drives real ``DevLoopRunner`` + ``SessionHost`` gate machinery through a
stub flow (``_FakeFlow``/``_BlockingFlow``-style, matching
``test_runner_host.py``'s harness) — no real dev_loop node graph needed;
parking is a runner/session-state concern, orthogonal to the node graph.
"""

from __future__ import annotations

import asyncio
from typing import Dict

import pytest

from parrot import conf
from parrot.bots.flows.core.result import FlowResult
from parrot.bots.flows.core.types import FlowStatus
from parrot.flows.dev_loop import BugBrief, DevLoopRunner, ShellCriterion


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


class _GateOpeningFlow:
    """``run_flow`` stub that opens a gate (simulating a node) and blocks on
    it before returning, exactly like a real gate-opening node would.

    ``post_gate_delay`` simulates a real node doing more work (e.g.
    dispatching QA/close) after the gate resolves — without it, a stub
    flow that returns IMMEDIATELY on gate resolution races the automatic
    sink-triggered resume against any concurrent explicit ``resume_run()``
    caller for the single already-completing run's bookkeeping, which is
    a timing artifact of an unrealistically instantaneous stub, not a
    real correctness gap (both paths are individually race-safe — see
    ``resume_run``'s ``fut.done()`` re-check).
    """

    def __init__(
        self, *, kind: str = "deployment_approval", post_gate_delay: float = 0.0,
    ) -> None:
        self._kind = kind
        self._post_gate_delay = post_gate_delay
        self.gate_ids: Dict[str, str] = {}

    async def run_flow(self, ctx, **kwargs) -> FlowResult:
        run_id = ctx.shared_data["run_id"]
        host = ctx.shared_data["session_host"]
        gate_id, _ = host.open_gate(
            kind=self._kind, node_id="development", title="approve?",
            instructions="", ttl_seconds=None, on_expiry="fail",
        )
        self.gate_ids[run_id] = gate_id
        gate = await host.wait_gate(gate_id)
        if self._post_gate_delay:
            await asyncio.sleep(self._post_gate_delay)
        if gate.status != "approved":
            return FlowResult(output=run_id, status=FlowStatus.FAILED)
        return FlowResult(output=run_id, status=FlowStatus.COMPLETED)


class _InstantFlow:
    """``run_flow`` stub that completes immediately — the queued run used
    to prove a parked run's slot is genuinely free."""

    async def run_flow(self, ctx, **kwargs) -> FlowResult:
        return FlowResult(
            output=ctx.shared_data["run_id"], status=FlowStatus.COMPLETED,
        )


@pytest.mark.asyncio
async def test_parked_run_releases_slot(brief, monkeypatch):
    """With parking on and a single slot: run 1 opens a gate (parks), and
    a SECOND run acquires the now-free slot before run 1 resolves."""
    monkeypatch.setattr(conf, "DEV_LOOP_GATE_PARK", True)
    flow = _GateOpeningFlow()
    runner = DevLoopRunner(flow, max_concurrent_runs=1)  # type: ignore[arg-type]

    task1 = asyncio.ensure_future(runner.run(brief, run_id="run-park-1"))
    # Give run 1 a chance to open its gate and park.
    for _ in range(50):
        if runner.is_parked("run-park-1"):
            break
        await asyncio.sleep(0.01)
    assert runner.is_parked("run-park-1")
    assert not runner.is_active("run-park-1")

    # A single-slot runner would deadlock here if run 1 still held its slot.
    instant_flow = _InstantFlow()
    runner.flow = instant_flow  # swap so run 2 completes immediately
    result2 = await asyncio.wait_for(
        runner.run(brief, run_id="run-park-2"), timeout=1.0
    )
    assert result2.status == FlowStatus.COMPLETED

    # Clean up run 1.
    host = runner.get_host("run-park-1")
    gate_id = flow.gate_ids["run-park-1"]
    host.resolve_gate(gate_id, "approved", resolved_by="alice")
    result1 = await task1
    assert result1.status == FlowStatus.COMPLETED


@pytest.mark.asyncio
async def test_resume_run_after_gate(brief, monkeypatch):
    """Resolving a parked run's gate lets it resume and complete; the
    root catalogue reflects parked=True then parked=False."""
    monkeypatch.setattr(conf, "DEV_LOOP_GATE_PARK", True)
    flow = _GateOpeningFlow()
    runner = DevLoopRunner(flow, max_concurrent_runs=1)  # type: ignore[arg-type]

    task = asyncio.ensure_future(runner.run(brief, run_id="run-resume-1"))
    for _ in range(50):
        if runner.is_parked("run-resume-1"):
            break
        await asyncio.sleep(0.01)
    assert runner.is_parked("run-resume-1")
    assert runner.registry_state.runs["run-resume-1"].parked is True

    host = runner.get_host("run-resume-1")
    gate_id = flow.gate_ids["run-resume-1"]
    host.resolve_gate(gate_id, "approved", resolved_by="alice")

    result = await asyncio.wait_for(task, timeout=1.0)
    assert result.status == FlowStatus.COMPLETED
    assert not runner.is_parked("run-resume-1")
    assert not runner.is_active("run-resume-1")


@pytest.mark.asyncio
async def test_resume_run_public_api(brief, monkeypatch):
    """``resume_run`` re-acquires the slot and returns the eventual result
    — callable directly, not just via the automatic gate-resolution hook."""
    monkeypatch.setattr(conf, "DEV_LOOP_GATE_PARK", True)
    # A small post-gate delay simulates a real node doing more work after
    # the gate resolves (dispatching QA/close, etc). Without it, this stub
    # flow returns IMMEDIATELY on gate resolution, which races the sink's
    # automatic resume (also triggered by `resolve_gate` below) against
    # this test's own explicit `resume_run()` call for the SAME already-
    # finishing run — both would legitimately observe "already cleaned
    # up" nondeterministically. That race is an artifact of an
    # unrealistically instantaneous stub, not a correctness gap in
    # `resume_run` (see its `fut.done()` re-check for the real safety net).
    flow = _GateOpeningFlow(post_gate_delay=0.05)
    runner = DevLoopRunner(flow, max_concurrent_runs=1)  # type: ignore[arg-type]

    task = asyncio.ensure_future(runner.run(brief, run_id="run-manual-resume"))
    for _ in range(50):
        if runner.is_parked("run-manual-resume"):
            break
        await asyncio.sleep(0.01)
    assert runner.is_parked("run-manual-resume")

    host = runner.get_host("run-manual-resume")
    gate_id = flow.gate_ids["run-manual-resume"]
    host.resolve_gate(gate_id, "approved", resolved_by="alice")

    result = await asyncio.wait_for(runner.resume_run("run-manual-resume"), timeout=1.0)
    assert result.status == FlowStatus.COMPLETED
    await task  # the original run() call returns the same result


@pytest.mark.asyncio
async def test_park_disabled_holds_slot(brief, monkeypatch):
    """Flag off: byte-identical to pre-TASK-1917 behavior — a run awaiting
    a gate holds its slot; a second run cannot even START its own flow
    (never mind resolve a gate) until the first releases the slot."""
    monkeypatch.setattr(conf, "DEV_LOOP_GATE_PARK", False)
    flow = _GateOpeningFlow()
    runner = DevLoopRunner(flow, max_concurrent_runs=1)  # type: ignore[arg-type]

    task1 = asyncio.ensure_future(runner.run(brief, run_id="run-nopark-1"))
    for _ in range(50):
        if "run-nopark-1" in runner.active_runs:
            break
        await asyncio.sleep(0.01)
    assert runner.is_active("run-nopark-1")
    assert not runner.is_parked("run-nopark-1")

    # A second run can't even acquire the semaphore to start its own
    # run_flow() — proving the slot is genuinely still held (unlike the
    # parked case, where a second run proceeds immediately).
    task2 = asyncio.ensure_future(runner.run(brief, run_id="run-nopark-2"))
    await asyncio.sleep(0.03)
    assert not task2.done()
    assert "run-nopark-2" not in flow.gate_ids  # run_flow() never even started

    host = runner.get_host("run-nopark-1")
    gate_id = flow.gate_ids["run-nopark-1"]
    host.resolve_gate(gate_id, "approved", resolved_by="alice")
    result1 = await asyncio.wait_for(task1, timeout=1.0)
    assert result1.status == FlowStatus.COMPLETED

    # Now the slot is free — task2 can proceed to open ITS OWN gate.
    for _ in range(50):
        if "run-nopark-2" in flow.gate_ids:
            break
        await asyncio.sleep(0.01)
    assert "run-nopark-2" in flow.gate_ids
    host2 = runner.get_host("run-nopark-2")
    host2.resolve_gate(flow.gate_ids["run-nopark-2"], "approved", resolved_by="alice")
    result2 = await asyncio.wait_for(task2, timeout=1.0)
    assert result2.status == FlowStatus.COMPLETED


@pytest.mark.asyncio
async def test_expiry_approve_resumes(brief, monkeypatch):
    """An expired plan_approval-style (on_expiry='approve') gate resumes
    a parked run identically to explicit approval, via the runner's
    periodic sweep hook."""
    monkeypatch.setattr(conf, "DEV_LOOP_GATE_PARK", True)

    class _FailOpenGateFlow:
        gate_ids: Dict[str, str] = {}

        async def run_flow(self, ctx, **kwargs) -> FlowResult:
            run_id = ctx.shared_data["run_id"]
            host = ctx.shared_data["session_host"]
            gate_id, _ = host.open_gate(
                kind="plan_approval", node_id="development", title="approve?",
                instructions="", ttl_seconds=0.01, on_expiry="approve",
            )
            self.gate_ids[run_id] = gate_id
            gate = await host.wait_gate(gate_id)
            status = FlowStatus.COMPLETED if gate.status == "approved" else FlowStatus.FAILED
            return FlowResult(output=run_id, status=status)

    flow = _FailOpenGateFlow()
    runner = DevLoopRunner(flow, max_concurrent_runs=1)  # type: ignore[arg-type]

    task = asyncio.ensure_future(runner.run(brief, run_id="run-expire-1"))
    for _ in range(50):
        if runner.is_parked("run-expire-1"):
            break
        await asyncio.sleep(0.01)
    assert runner.is_parked("run-expire-1")

    # Drive the fail-open expiry path directly (the same sweep the
    # runner's periodic loop calls).
    host = runner.get_host("run-expire-1")
    gate_id = flow.gate_ids["run-expire-1"]
    gate = host.state.gates[gate_id]
    host.expire_due_gates(now=(gate.expires_at or 0) + 1)

    result = await asyncio.wait_for(task, timeout=1.0)
    assert result.status == FlowStatus.COMPLETED
    assert not runner.is_parked("run-expire-1")


@pytest.mark.asyncio
async def test_no_double_release_on_rejection(brief, monkeypatch):
    """A rejected gate resumes the run (to let it finish/fail out) exactly
    once — no double-release, no leaked slot."""
    monkeypatch.setattr(conf, "DEV_LOOP_GATE_PARK", True)
    flow = _GateOpeningFlow()
    runner = DevLoopRunner(flow, max_concurrent_runs=1)  # type: ignore[arg-type]

    task = asyncio.ensure_future(runner.run(brief, run_id="run-reject-1"))
    for _ in range(50):
        if runner.is_parked("run-reject-1"):
            break
        await asyncio.sleep(0.01)
    assert runner.is_parked("run-reject-1")

    host = runner.get_host("run-reject-1")
    gate_id = flow.gate_ids["run-reject-1"]
    host.resolve_gate(gate_id, "rejected", resolved_by="bob")

    result = await asyncio.wait_for(task, timeout=1.0)
    assert result.status == FlowStatus.FAILED
    assert not runner.is_parked("run-reject-1")
    assert not runner.is_active("run-reject-1")
    # The slot is available for exactly one more run (not zero, not two).
    assert runner._semaphore._value == 1  # noqa: SLF001 - internal invariant check


@pytest.mark.asyncio
async def test_multiple_concurrent_gates_park_and_resume_once_each(brief, monkeypatch):
    """A run with TWO concurrently-pending gates parks once (0->1) and
    resumes once (1->0) — not once per gate."""
    monkeypatch.setattr(conf, "DEV_LOOP_GATE_PARK", True)

    class _TwoGateFlow:
        async def run_flow(self, ctx, **kwargs) -> FlowResult:
            run_id = ctx.shared_data["run_id"]
            host = ctx.shared_data["session_host"]
            gate_id_1, _ = host.open_gate(
                kind="manual_criterion", node_id="development", title="g1",
                ttl_seconds=None, on_expiry="fail",
            )
            gate_id_2, _ = host.open_gate(
                kind="manual_criterion", node_id="development", title="g2",
                ttl_seconds=None, on_expiry="fail",
            )
            g1, g2 = await asyncio.gather(
                host.wait_gate(gate_id_1), host.wait_gate(gate_id_2),
            )
            ok = g1.status == "approved" and g2.status == "approved"
            return FlowResult(
                output=run_id,
                status=FlowStatus.COMPLETED if ok else FlowStatus.FAILED,
            )

    flow = _TwoGateFlow()
    runner = DevLoopRunner(flow, max_concurrent_runs=1)  # type: ignore[arg-type]

    task = asyncio.ensure_future(runner.run(brief, run_id="run-multi-gate"))
    for _ in range(50):
        if runner.is_parked("run-multi-gate"):
            break
        await asyncio.sleep(0.01)
    assert runner.is_parked("run-multi-gate")

    host = runner.get_host("run-multi-gate")
    gates = list(host.state.gates.keys())
    assert len(gates) == 2

    # Resolve the FIRST gate — the run must stay parked (one gate still pending).
    host.resolve_gate(gates[0], "approved", resolved_by="alice")
    await asyncio.sleep(0.02)
    assert runner.is_parked("run-multi-gate")

    # Resolve the SECOND (last) gate — now it resumes.
    host.resolve_gate(gates[1], "approved", resolved_by="alice")
    result = await asyncio.wait_for(task, timeout=1.0)
    assert result.status == FlowStatus.COMPLETED
    assert not runner.is_parked("run-multi-gate")
