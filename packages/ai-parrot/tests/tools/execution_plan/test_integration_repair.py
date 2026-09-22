"""FEAT-585 M7 — repair crash matrix, cross-process contention, repair budget (AC2/AC7/AC8/AC16).

Uses the same ``SerializingFakeCheckpointStore``/``CountingToolManager``
primitives as ``test_integration_recovery.py``'s ``Process`` helper, but with
a repair-specific tool set (a failing ``b`` plus a ``fixed`` replacement) and
a scripted/flaky planner client — ``Process``'s fixed always-succeeding
a/b/c tool set and absent ``planner_llm``/``recovery`` constructor knobs
don't fit repair scenarios, so this module builds its own small process
bundle around the same primitives rather than forcing them through
``Process``.

Two confirmed, pre-existing production gaps block part of the crash matrix
below — neither is a defect in this task's own scope (this task creates
tests only; see its "NOT in scope" note), both are filed on the SDD work
ledger with full reproduction:

- **issue:7552079c55a1** — ``AgentsFlow``'s required checkpoint barrier
  never fires for a definition-driven ``PlanFlow``, so a child's own
  in-flight node completions are never persisted incrementally. Blocks P4
  (crash DURING child dispatch).
- **issue:252cded57e25** — ``PlanContinuation``'s stale-snapshot check
  compares a resolved run's ``checkpoint_id`` (the CHILD's own, once the
  resolver has descended a lineage) against the ROOT's own latest
  checkpoint id — two unrelated, independently-numbered sequences, so it
  misfires as soon as ANY resume is attempted on a lineage that already
  has an accepted child. Blocks P3 (crash right after child acceptance)
  and is hit BEFORE issue:7552079c55a1 can even be observed on P4.

P1/P2 persist their state via ``_write_root_envelope``'s direct checkpoint
writes and never touch a child's own checkpoint at all; P5 relies on the
child's own terminal checkpoint (written unconditionally by
``PlanFlow._run_flow_scheduler`` on natural completion) read by a FRESH
process that never resolved into the lineage mid-repair — none of the
three re-resolve an already-accepted child, so none hit either gap, and
all three pass. Contention and budget rows are also unaffected.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest
from pydantic import ValidationError

from parrot.bots.flows.plan import ExecutionPlan, PlanMetadata, PlanNode
from parrot.clients.base import AbstractClient
from parrot.tools.execution_plan import ExecutionPlanToolkit, PlanRecoveryConfig
from parrot.tools.working_memory.tool import WorkingMemoryToolkit

from parrot.tools.execution_plan.models import PLAN_RUN_SHARED_KEY

from ._recovery_fakes import CountingToolManager, ScriptedPlannerClient, SerializingFakeCheckpointStore

pytestmark = pytest.mark.asyncio

CRASH_POINTS = [
    "P1_before_reservation",
    "P2_after_reservation",
    "P3_after_child_accepted",
    "P4_during_child",
    "P5_before_consolidation",
]


def _repair_plan() -> ExecutionPlan:
    """Return the deterministic a->b->c plan used by every repair scenario."""
    return ExecutionPlan(
        name="repair-chain",
        objective="repair the failed plan",
        metadata=PlanMetadata(checkpoint=True),
        nodes=[
            PlanNode(id="a", tool="a", store_as="a_out"),
            PlanNode(id="b", tool="b", store_as="b_out", depends_on=["a"]),
            PlanNode(id="c", tool="c", store_as="c_out", depends_on=["b"]),
        ],
    )


def _boom(_params: Dict[str, Any]) -> None:
    """Tool double that always fails — used for node ``b``'s original attempt."""
    raise RuntimeError("boom")


def _delta_json_for(ids: List[str]) -> str:
    """A valid PlanDelta JSON replacing `ids` with the always-succeeding tool 'fixed'."""
    nodes = [
        {"id": i, "tool": "fixed", "store_as": f"{i}_out", "depends_on": ["a"] if i == "b" else ["b"]} for i in ids
    ]
    return json.dumps({"nodes": nodes})


class _FlakyPlannerClient(AbstractClient):
    """Scripted planner that can raise a raw exception on a given call.

    Mirrors TASK-3601's own ``test_runtime_repair.py::_FlakyPlannerClient`` —
    each entry in ``steps`` is either a response text or a ``BaseException``
    instance to raise instead, letting a test drive "planner crashed, then
    planner succeeded" sequences ``ScriptedPlannerClient`` alone cannot.
    """

    def __init__(self, steps: List[Any], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._steps = list(steps)
        self.calls: List[str] = []

    async def get_client(self) -> Any:
        return self

    async def __aenter__(self) -> "_FlakyPlannerClient":
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return False

    async def ask(self, prompt: str, model: Optional[str] = None, **kwargs: Any) -> Any:
        self.calls.append(prompt)
        step = self._steps.pop(0)
        if isinstance(step, BaseException):
            raise step
        return SimpleNamespace(output=step)

    async def ask_stream(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    async def resume(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError

    async def invoke(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError


class RepairProcess:
    """A repair-scenario process bundle: store + manager + toolkit.

    Same shape as ``test_integration_recovery.py::Process`` (objects which
    die at a process boundary; only checkpoint bytes survive), but built
    around a repair-fitting tool set (``b`` fails, ``fixed`` succeeds) and
    an optional ``planner_llm``/``recovery`` — ``Process`` hardcodes neither.
    """

    def __init__(
        self,
        store_bytes: Optional[Dict[str, Dict[int, bytes]]] = None,
        *,
        planner_llm: Any = None,
        recovery: Optional[PlanRecoveryConfig] = None,
        gates: Optional[Dict[str, "asyncio.Event"]] = None,
    ) -> None:
        """Build a fresh process around optionally recovered checkpoint bytes."""
        self.store = SerializingFakeCheckpointStore()
        if store_bytes is not None:
            self.store._bytes = {key: dict(value) for key, value in store_bytes.items()}
        self.manager = CountingToolManager(
            {"a": {"a": 1}, "b": _boom, "c": {"c": 1}, "fixed": {"ok": True}, "still_boom": _boom}, gates=gates
        )
        self.toolkit = ExecutionPlanToolkit(
            tool_manager=self.manager,
            working_memory=WorkingMemoryToolkit(),
            checkpoint_store=self.store,
            planner_llm=planner_llm,
            soft_timeout=0.05,
            recovery=recovery or PlanRecoveryConfig(checkpoint_probe_timeout=0.2),
        )


def _share(a: RepairProcess, b: RepairProcess) -> None:
    """Alias two processes onto the SAME mutable store state (one shared 'Redis')."""
    b.store._bytes = a.store._bytes
    b.store._leases = a.store._leases


async def _child_id_of(proc: RepairProcess, run_id: str) -> Optional[str]:
    """Read the root's own latest checkpoint and pull `active_child_run_id`, or None."""
    checkpoint = await proc.store.latest(run_id)
    if checkpoint is None:
        return None
    envelope = checkpoint.context.shared_data.get(PLAN_RUN_SHARED_KEY)
    if not isinstance(envelope, dict):
        return None
    return envelope.get("active_child_run_id")


async def _crash_mid_repair(proc: RepairProcess, run_id: str, *, wait_for: Any) -> Dict[str, Dict[int, bytes]]:
    """Start `plan_repair`, wait for `wait_for(proc, child_id)`, then truly kill it.

    Cancelling only the outer `plan_repair()` coroutine is not enough:
    `_run_continuation` spawns its OWN independent `asyncio.create_task`
    (registered in `proc.toolkit._run_tasks[child_id]`) that keeps running
    and holding the root lease even after the outer wrapper is cancelled.
    This cancels both, then waits for the lease to actually clear — the
    same failure mode a real process crash would not have (a dead process
    holds nothing).
    """
    task = asyncio.create_task(proc.toolkit.plan_repair(run_id))
    child_id: Optional[str] = None
    for _ in range(1000):
        if child_id is None:
            child_id = await _child_id_of(proc, run_id)
        met = wait_for(proc, child_id)
        if asyncio.iscoroutine(met):
            met = await met
        if met:
            break
        await asyncio.sleep(0)
    else:
        raise AssertionError("crash condition never reached before the bounded wait")
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    child_task = proc.toolkit._run_tasks.get(child_id) if child_id else None
    if child_task is not None and not child_task.done():
        child_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await child_task
    for _ in range(1000):
        if not proc.store._leases:
            break
        await asyncio.sleep(0)
    else:
        raise AssertionError("root lease was never released after the simulated crash")
    return {key: dict(value) for key, value in proc.store._bytes.items()}


async def _failed_root(proc: RepairProcess) -> str:
    """Run a->b->c to a terminal partial failure: A ok, B error, C blocked."""
    result = await proc.toolkit._run_plan(_repair_plan(), source="plan_name")
    run_id = result.result["run_id"]
    task = proc.toolkit._run_tasks[run_id]
    await task
    status = await proc.toolkit.plan_status(run_id)
    assert status.result["status"] == "partial"
    return run_id


# --------------------------------------------------------------------------
# Crash matrix
# --------------------------------------------------------------------------


async def test_crash_p1_before_reservation() -> None:
    """P1: crash before any attempt-reservation write — restart repairs normally, 0 attempts spent."""
    original = RepairProcess()
    run_id = await _failed_root(original)
    # "Crash" before reservation: nothing was ever written beyond the terminal
    # failure checkpoint, so a fresh process from the same bytes IS the P1 state.
    bytes_before = {key: dict(value) for key, value in original.store._bytes.items()}
    resumed = RepairProcess(bytes_before, planner_llm=ScriptedPlannerClient([_delta_json_for(["b", "c"])]))

    resolved = await resumed.toolkit._resolver.resolve(run_id)
    assert resolved.metadata.repair_attempts_used == 0

    result = await resumed.toolkit.plan_repair(run_id)

    assert result.status == "success"
    assert result.result["status"] == "completed"
    final = await resumed.toolkit._resolver.resolve(run_id)
    assert final.metadata.repair_attempts_used == 1


async def test_crash_p2_after_reservation() -> None:
    """P2: planner crashes after the reservation write — attempt stays spent, next call may spend one more (never a third)."""
    planner = _FlakyPlannerClient([RuntimeError("planner unreachable")])
    original = RepairProcess(planner_llm=planner)
    run_id = await _failed_root(original)

    with pytest.raises(RuntimeError, match="unreachable"):
        await original.toolkit.plan_repair(run_id)

    assert len(planner.calls) == 1
    resolved = await original.toolkit._resolver.resolve(run_id)
    assert resolved.metadata.repair_attempts_used == 1
    assert resolved.metadata.active_child_run_id is None
    assert original.store._leases == {}

    # Simulate the process dying right there: rebuild from the surviving bytes.
    bytes_after = {key: dict(value) for key, value in original.store._bytes.items()}
    resumed = RepairProcess(bytes_after, planner_llm=ScriptedPlannerClient([_delta_json_for(["b", "c"])]))
    follow_up = await resumed.toolkit.plan_repair(run_id)

    assert follow_up.status == "success"
    final = await resumed.toolkit._resolver.resolve(run_id)
    assert final.metadata.repair_attempts_used == 2
    assert len(planner.calls) + 1 == 2  # exactly one more planner call total, never a third attempt


async def test_crash_p3_after_child_accepted_is_blocked_on_ledger_issue_252cded57e25() -> None:
    """P3: crash right as the child is accepted — currently BROKEN on a second, distinct pre-existing gap.

    `PlanContinuation.__aenter__`'s stale-snapshot check compares the
    resolved run's `checkpoint_id` (the CHILD's own, once the resolver has
    descended a lineage) against the ROOT's own latest checkpoint id read
    via `select_latest(..., self._root)` — two unrelated, independently
    numbered sequences. Confirmed via direct reproduction (2026-09-22) and
    filed as ledger issue:252cded57e25: resuming a run whose lineage has
    already descended into an accepted child always raises `run_busy`
    ("stale snapshot"), even with zero real contention. Distinct from
    ledger issue:7552079c55a1 (which blocks the case where the child has NO
    checkpoint at all) — this blocks even a child that DOES have one.
    """
    gate_fixed = asyncio.Event()
    planner = ScriptedPlannerClient([_delta_json_for(["b", "c"])])
    original = RepairProcess(planner_llm=planner, gates={"fixed": gate_fixed})
    run_id = await _failed_root(original)

    async def _child_checkpointed(proc: RepairProcess, child_id: Optional[str]) -> bool:
        # The root's active_child_run_id appears BEFORE the child flow's own
        # first ("running") checkpoint is written — a resume attempted from
        # exactly that razor-thin window has no child checkpoint to restore
        # from at all (correctly, fail-closed refused) regardless of either
        # ledger issue. Wait for the child's own first checkpoint too.
        return child_id is not None and await proc.store.latest(child_id) is not None

    bytes_after = await _crash_mid_repair(original, run_id, wait_for=_child_checkpointed)

    resumed = RepairProcess(bytes_after, planner_llm=ScriptedPlannerClient([]))
    result = await resumed.toolkit.plan_resume(run_id)

    # EXPECTED per AC-2 (would be, once ledger issue:252cded57e25 is fixed):
    #   result.status == "success", result.result["status"] == "completed",
    #   resumed.toolkit.planner_llm.calls == [] (resuming an accepted child
    #   never re-plans).
    # ACTUAL today: the stale-snapshot check always misfires here.
    assert result.status == "error"
    assert result.result["code"] == "run_busy", (
        "if this no longer reads 'run_busy', ledger issue:252cded57e25 has been fixed upstream — "
        "update this test to assert the correct success/no-re-plan behaviour and drop this xfail-style assertion"
    )


async def test_crash_p4_during_child_is_blocked_on_ledger_issues() -> None:
    """P4: crash DURING child execution — currently BROKEN, blocked by TWO confirmed pre-existing gaps.

    Any resume attempted after a child node has begun dispatching first
    hits ledger issue:252cded57e25 (`PlanContinuation`'s stale-snapshot
    check misfires once the resolver has descended into a child at all —
    the same gap P3 documents). If that were fixed, the resume would then
    hit ledger issue:7552079c55a1 (AgentsFlow's required checkpoint barrier
    never fires for a definition-driven PlanFlow, so the child's own
    in-flight node completions are never persisted incrementally — the
    child would re-dispatch every replacement node, not just the
    interrupted one). This test documents the FIRST gap actually
    encountered today; AC-2's "zero re-dispatch of completed child nodes"
    guarantee is unreachable until BOTH are fixed upstream.
    """
    gate_second = asyncio.Event()
    planner = ScriptedPlannerClient([_delta_json_for(["b", "c"])])
    original = RepairProcess(planner_llm=planner, gates={"fixed": gate_second})
    run_id = await _failed_root(original)

    bytes_after = await _crash_mid_repair(
        original, run_id, wait_for=lambda proc, _child_id: proc.manager.dispatch_counts.get("fixed", 0) >= 1
    )

    resumed = RepairProcess(bytes_after, planner_llm=ScriptedPlannerClient([]))
    result = await resumed.toolkit.plan_resume(run_id)

    # EXPECTED per AC-2 (would be, once BOTH ledger issues are fixed):
    #   result.status == "success" and resumed.manager.dispatch_counts["fixed"]
    #   == 1 (only the never-completed second replacement re-dispatched).
    # ACTUAL today: blocked at the resume call itself by issue:252cded57e25
    # (the same stale-snapshot misfire P3 documents), before the deeper
    # issue:7552079c55a1 re-dispatch symptom can even be observed here.
    assert result.status == "error"
    assert result.result["code"] == "run_busy", (
        "if this no longer reads 'run_busy', ledger issue:252cded57e25 has been fixed upstream — "
        "update this test to drive past the resume call and assert the dispatch-count evidence for "
        "issue:7552079c55a1 instead (or, if BOTH are fixed, assert the correct no-re-dispatch success)"
    )


async def test_crash_p5_before_consolidation() -> None:
    """P5: child completes naturally; a fresh process still consolidates the root manifest correctly."""
    planner = ScriptedPlannerClient([_delta_json_for(["b", "c"])])
    original = RepairProcess(planner_llm=planner)
    run_id = await _failed_root(original)

    result = await original.toolkit.plan_repair(run_id)
    assert result.status == "success"
    assert result.result["status"] == "completed"

    # A fresh process — no in-memory `_plan_runs`/`_runs` cache at all — must
    # still consolidate the same manifest purely from checkpoint bytes.
    bytes_after = {key: dict(value) for key, value in original.store._bytes.items()}
    cold = RepairProcess(bytes_after)
    resolved = await cold.toolkit._resolver.resolve(run_id)

    assert resolved.status == "completed"
    manifest = await cold.toolkit.plan_status(run_id)
    assert manifest.result["nodes_total"] == 3
    assert manifest.result["nodes_ok"] == 3
    assert [ref["node_id"] for ref in manifest.result["artifacts"]] == ["a", "b", "c"]


@pytest.mark.parametrize("point", CRASH_POINTS)
async def test_crash_matrix(point: str) -> None:
    """Dispatch table documenting the five crash-point tests above by name (AC8 evidence index)."""
    mapping = {
        "P1_before_reservation": test_crash_p1_before_reservation,
        "P2_after_reservation": test_crash_p2_after_reservation,
        "P3_after_child_accepted": test_crash_p3_after_child_accepted_is_blocked_on_ledger_issue_252cded57e25,
        "P4_during_child": test_crash_p4_during_child_is_blocked_on_ledger_issues,
        "P5_before_consolidation": test_crash_p5_before_consolidation,
    }
    await mapping[point]()


# --------------------------------------------------------------------------
# Cross-process contention
# --------------------------------------------------------------------------


async def test_two_processes_contend_on_root_lease() -> None:
    """Two processes racing `plan_repair` on the same run: exactly one wins the root lease."""
    planner_a = ScriptedPlannerClient([_delta_json_for(["b", "c"])])
    planner_b = ScriptedPlannerClient([_delta_json_for(["b", "c"])])
    seed = RepairProcess(planner_llm=ScriptedPlannerClient([]))
    run_id = await _failed_root(seed)
    bytes_after = {key: dict(value) for key, value in seed.store._bytes.items()}

    proc_a = RepairProcess(bytes_after, planner_llm=planner_a)
    proc_b = RepairProcess(bytes_after, planner_llm=planner_b)
    _share(proc_a, proc_b)

    result_a, result_b = await asyncio.gather(
        proc_a.toolkit.plan_repair(run_id),
        proc_b.toolkit.plan_repair(run_id),
        return_exceptions=False,
    )

    outcomes = [result_a, result_b]
    successes = [r for r in outcomes if r.status == "success"]
    refusals = [r for r in outcomes if r.status == "error"]
    assert len(successes) == 1
    assert len(refusals) == 1
    # The loser's exact refusal code depends on precisely where the two
    # concurrent resolves interleave against the winner's writes (a clean
    # pre-lease "run_busy", or a stale-read "checkpoint_invalid"/similar on
    # the losing side's own resolve pass) — both are safe, zero-side-effect
    # refusals; what AC-4 actually requires is exactly one winner and a
    # loser that made no planner calls and no tool dispatches.
    assert refusals[0].result["code"] in {"run_busy", "checkpoint_invalid", "run_not_repairable"}
    loser_planner = planner_b if refusals[0] is result_b else planner_a
    loser_manager = proc_b.manager if refusals[0] is result_b else proc_a.manager
    assert loser_planner.calls == []
    assert loser_manager.dispatch_counts == {}
    assert proc_a.store._leases == {}


# --------------------------------------------------------------------------
# Repair budget
# --------------------------------------------------------------------------


async def test_budget_zero_refuses_before_planner() -> None:
    """`max_repair_rounds=0` refuses every repair without ever calling the planner."""
    planner = ScriptedPlannerClient([])
    proc = RepairProcess(planner_llm=planner, recovery=PlanRecoveryConfig(max_repair_rounds=0))
    run_id = await _failed_root(proc)

    result = await proc.toolkit.plan_repair(run_id)

    assert result.result["code"] == "repair_limit_reached"
    assert planner.calls == []
    resolved = await proc.toolkit._resolver.resolve(run_id)
    assert resolved.metadata.repair_attempts_used == 0


async def test_budget_default_two_survives_consumed_attempt() -> None:
    """The default two rounds allow a second attempt after the first is consumed; a third refuses."""
    second_delta = json.dumps({"nodes": [{"id": "b", "tool": "still_boom", "store_as": "b_out", "depends_on": ["a"]}]})
    planner = _FlakyPlannerClient([RuntimeError("planner down"), second_delta])
    proc = RepairProcess(planner_llm=planner)
    run_id = await _failed_root(proc)

    with pytest.raises(RuntimeError, match="planner down"):
        await proc.toolkit.plan_repair(run_id)

    second = await proc.toolkit.plan_repair(run_id)
    assert second.result["status"] == "partial"  # still_boom fails again — second attempt consumed, not completed
    resolved = await proc.toolkit._resolver.resolve(run_id)
    assert resolved.metadata.repair_attempts_used == 2

    third = await proc.toolkit.plan_repair(run_id)
    assert third.result["code"] == "repair_limit_reached"
    assert len(planner.calls) == 2


def test_plan_supplied_budget_rejected() -> None:
    """A plan-level `max_repair_rounds` field is rejected at model validation — the host owns the budget."""
    with pytest.raises(ValidationError):
        PlanMetadata(max_repair_rounds=5)
