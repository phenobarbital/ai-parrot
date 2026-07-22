"""Host-lifecycle unit tests for ``DevLoopRunner`` (FEAT-322 TASK-1851).

Exercises the AHP-style host registry, root catalogue, command surface
(``resolve_gate``/``cancel_run``), and sink resilience added on top of the
existing semaphore/run-id machinery — without driving the full dev-loop
node graph (see ``test_runner.py`` for those end-to-end paths).
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock

import pytest

from parrot.bots.flows.core.result import FlowResult
from parrot.bots.flows.core.types import FlowStatus
from parrot.flows.dev_loop import BugBrief, DevLoopRunner, ShellCriterion
from parrot.flows.dev_loop.session_state import GateAlreadyResolvedError


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


class _FakeFlow:
    """Minimal ``run_flow`` stub — no real node graph, no redis.

    ``on_run_flow`` (if given) lets a test observe/mutate ``ctx`` (e.g. to
    simulate a node opening a gate via ``ctx.shared_data["session_host"]``)
    before the fake result is returned.
    """

    def __init__(
        self,
        *,
        status: FlowStatus = FlowStatus.COMPLETED,
        responses: Dict[str, Any] | None = None,
        on_run_flow=None,
    ) -> None:
        self.status = status
        self.responses = responses or {}
        self.on_run_flow = on_run_flow
        self.calls: List[Any] = []

    async def run_flow(self, ctx, **kwargs) -> FlowResult:
        self.calls.append(ctx)
        if self.on_run_flow is not None:
            await self.on_run_flow(ctx)
        return FlowResult(
            output=ctx.shared_data.get("run_id"),
            status=self.status,
            responses=dict(self.responses),
        )


class _BlockingFlow:
    """``run_flow`` stub that blocks until externally released."""

    def __init__(self) -> None:
        self.release = asyncio.Event()
        self.entered: Dict[str, Any] = {}

    async def run_flow(self, ctx, **kwargs) -> FlowResult:
        self.entered[ctx.shared_data["run_id"]] = ctx
        await self.release.wait()
        return FlowResult(output=ctx.shared_data["run_id"], status=FlowStatus.COMPLETED)


# ---------------------------------------------------------------------------
# Host lifecycle: create on start, close + registry update on completion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_creates_and_closes_host(brief):
    flow = _FakeFlow(responses={"deployment_handoff": {"pr_url": "http://pr/1"}})
    runner = DevLoopRunner(flow, max_concurrent_runs=2)  # type: ignore[arg-type]

    result = await runner.run(brief, run_id="run-host1")

    assert result.status == FlowStatus.COMPLETED
    # Host is discarded immediately after terminal handling.
    assert runner.get_host("run-host1") is None
    # But the run passed through shared state during execution.
    ctx = flow.calls[0]
    assert ctx.shared_data["session_host"] is not None
    assert ctx.shared_data["session_host"].state.run_id == "run-host1"


@pytest.mark.asyncio
async def test_run_folds_run_created_and_run_closed(brief):
    captured_host = {}

    async def _observe(ctx):
        captured_host["host"] = ctx.shared_data["session_host"]

    flow = _FakeFlow(on_run_flow=_observe)
    runner = DevLoopRunner(flow, max_concurrent_runs=2)  # type: ignore[arg-type]

    await runner.run(brief, run_id="run-host2")

    host = captured_host["host"]
    # The host is closed by the time run() returns, but we captured the
    # live reference mid-run — its terminal state is still readable.
    assert host.state.phase == "succeeded"
    assert host.state.summary == brief.summary


@pytest.mark.asyncio
async def test_run_failed_status_maps_to_failed_outcome(brief):
    captured_host = {}

    async def _observe(ctx):
        captured_host["host"] = ctx.shared_data["session_host"]

    flow = _FakeFlow(status=FlowStatus.FAILED, on_run_flow=_observe)
    runner = DevLoopRunner(flow, max_concurrent_runs=2)  # type: ignore[arg-type]

    await runner.run(brief, run_id="run-host3")
    assert captured_host["host"].state.phase == "failed"


@pytest.mark.asyncio
async def test_run_partial_status_maps_to_failed_outcome(brief):
    captured_host = {}

    async def _observe(ctx):
        captured_host["host"] = ctx.shared_data["session_host"]

    flow = _FakeFlow(status=FlowStatus.PARTIAL, on_run_flow=_observe)
    runner = DevLoopRunner(flow, max_concurrent_runs=2)  # type: ignore[arg-type]

    await runner.run(brief, run_id="run-host4")
    assert captured_host["host"].state.phase == "failed"


@pytest.mark.asyncio
async def test_run_root_registry_reflects_add_then_remove(brief):
    flow = _FakeFlow()
    runner = DevLoopRunner(flow, max_concurrent_runs=2)  # type: ignore[arg-type]

    # Registry starts empty.
    assert runner.registry_state.runs == {}

    await runner.run(brief, run_id="run-host5")

    # RunAdded then RunRemoved on terminal handling — net effect: empty
    # again (host discarded, root catalogue does not retain finished runs).
    assert runner.registry_state.runs == {}


@pytest.mark.asyncio
async def test_run_root_registry_populated_mid_run(brief):
    flow = _BlockingFlow()
    runner = DevLoopRunner(flow, max_concurrent_runs=2)  # type: ignore[arg-type]
    task = asyncio.create_task(runner.run(brief, run_id="run-host6"))
    await asyncio.sleep(0.02)

    assert "run-host6" in runner.registry_state.runs
    assert runner.registry_state.runs["run-host6"].phase == "running"

    flow.release.set()
    await task
    assert "run-host6" not in runner.registry_state.runs


# ---------------------------------------------------------------------------
# Registry isolation — two concurrent runs, distinct hosts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_registry_isolation_two_concurrent_runs(brief):
    flow = _BlockingFlow()
    runner = DevLoopRunner(flow, max_concurrent_runs=2)  # type: ignore[arg-type]

    t1 = asyncio.create_task(runner.run(brief, run_id="run-a"))
    t2 = asyncio.create_task(runner.run(brief, run_id="run-b"))
    await asyncio.sleep(0.05)

    host_a = runner.get_host("run-a")
    host_b = runner.get_host("run-b")
    assert host_a is not None and host_b is not None
    assert host_a is not host_b
    assert host_a.state.run_id == "run-a"
    assert host_b.state.run_id == "run-b"
    assert host_a.state.channel != host_b.state.channel

    # Registry catalogues both concurrently-running runs.
    assert set(runner.registry_state.runs) == {"run-a", "run-b"}

    flow.release.set()
    await asyncio.gather(t1, t2)

    # Both discarded after terminal handling — no cross-contamination.
    assert runner.get_host("run-a") is None
    assert runner.get_host("run-b") is None


# ---------------------------------------------------------------------------
# Command surface: resolve_gate / cancel_run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_gate_routes_to_host(brief):
    flow = _BlockingFlow()
    runner = DevLoopRunner(flow, max_concurrent_runs=2)  # type: ignore[arg-type]
    task = asyncio.create_task(runner.run(brief, run_id="run-gate"))
    await asyncio.sleep(0.02)

    host = runner.get_host("run-gate")
    gate_id, _ = host.open_gate(kind="manual_criterion", node_id="qa", title="Review")

    envelope = await runner.resolve_gate("run-gate", gate_id, "approved", resolved_by="alice")
    assert envelope.action.type == "gate/resolved"
    assert host.state.gates[gate_id].status == "approved"

    with pytest.raises(GateAlreadyResolvedError):
        await runner.resolve_gate("run-gate", gate_id, "rejected", resolved_by="bob")

    flow.release.set()
    await task


@pytest.mark.asyncio
async def test_resolve_gate_unknown_run_raises_key_error(brief):
    flow = _FakeFlow()
    runner = DevLoopRunner(flow, max_concurrent_runs=2)  # type: ignore[arg-type]

    with pytest.raises(KeyError):
        await runner.resolve_gate("no-such-run", "g1", "approved", resolved_by="alice")


@pytest.mark.asyncio
async def test_cancel_run_terminal_sticky(brief):
    flow = _BlockingFlow()
    runner = DevLoopRunner(flow, max_concurrent_runs=2)  # type: ignore[arg-type]
    task = asyncio.create_task(runner.run(brief, run_id="run-cancel"))
    await asyncio.sleep(0.02)

    host = runner.get_host("run-cancel")
    await runner.cancel_run("run-cancel", requested_by="alice")
    assert host.state.phase == "cancelled"

    # A second cancel is terminal-sticky (reducer no-op on phase/attribution).
    await runner.cancel_run("run-cancel", requested_by="bob")
    assert host.state.phase == "cancelled"
    assert host.state.cancel_requested_by == "alice"

    flow.release.set()
    await task


@pytest.mark.asyncio
async def test_cancel_run_unknown_run_raises_key_error():
    flow = _FakeFlow()
    runner = DevLoopRunner(flow, max_concurrent_runs=2)  # type: ignore[arg-type]

    with pytest.raises(KeyError):
        await runner.cancel_run("no-such-run", requested_by="alice")


# ---------------------------------------------------------------------------
# Envelope sink resilience — fake redis raising on XADD
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sink_failure_swallowed_state_folds(brief):
    flow = _FakeFlow()
    runner = DevLoopRunner(flow, max_concurrent_runs=2, redis_url="redis://fake:6379/0")  # type: ignore[arg-type]

    fake_redis = MagicMock()
    fake_redis.xadd = AsyncMock(side_effect=RuntimeError("redis is down"))
    runner._ensure_actions_redis = AsyncMock(return_value=fake_redis)  # type: ignore[method-assign]

    # Must not raise even though every XADD on the actions stream fails.
    result = await runner.run(brief, run_id="run-sinkfail")
    # Let any background XADD tasks scheduled during the run settle.
    await asyncio.sleep(0)

    assert result.status == FlowStatus.COMPLETED
    # State folded in-memory regardless of the sink failure.
    assert runner.get_host("run-sinkfail") is None  # closed normally


@pytest.mark.asyncio
async def test_sink_noop_when_no_redis_url(brief):
    flow = _FakeFlow()
    runner = DevLoopRunner(flow, max_concurrent_runs=2)  # type: ignore[arg-type]
    assert runner._redis_url is None

    result = await runner.run(brief, run_id="run-noredis")
    assert result.status == FlowStatus.COMPLETED


# ---------------------------------------------------------------------------
# Legacy construction still works (no redis_url, no optional deps)
# ---------------------------------------------------------------------------


def test_legacy_construction_no_redis():
    flow = MagicMock()
    runner = DevLoopRunner(flow)
    assert runner._redis_url is None
    assert runner.get_host("anything") is None
    assert runner.registry_state.runs == {}


# ---------------------------------------------------------------------------
# gate_ttl_for helper
# ---------------------------------------------------------------------------


def test_gate_ttl_for_all_kinds():
    from parrot.flows.dev_loop.runner import gate_ttl_for

    assert gate_ttl_for("deployment_approval") == 86400
    assert gate_ttl_for("manual_criterion") == 259200
    assert gate_ttl_for("revision_approval") == 86400
    assert gate_ttl_for("plan_approval") == 14400


# ---------------------------------------------------------------------------
# Expiry sweep (runner-level) — observable via injected short TTL
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sweep_once_expires_due_gates(brief):
    flow = _BlockingFlow()
    runner = DevLoopRunner(flow, max_concurrent_runs=2)  # type: ignore[arg-type]
    task = asyncio.create_task(runner.run(brief, run_id="run-sweep"))
    await asyncio.sleep(0.02)

    host = runner.get_host("run-sweep")
    gate_id, _ = host.open_gate(
        kind="plan_approval", node_id="research", title="x",
        ttl_seconds=1, on_expiry="approve",
    )
    # Force the gate to already be past its TTL and sweep once directly
    # (bypassing the real 30s cadence — this is what the task's AC means
    # by "observable via injected short TTL").
    host.expire_due_gates(now=host.state.gates[gate_id].opened_at + 10)
    assert host.state.gates[gate_id].status == "approved"
    assert host.state.gates[gate_id].resolved_by == "system:ttl-auto-approve"

    flow.release.set()
    await task
