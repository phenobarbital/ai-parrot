"""FEAT-599 / issue:bd1c792a5afc: suspension attribution reaches `coder_plan` (FEAT-559 AC-12).

The sdd-worker prompt tells the worker to print "excluded model, incident ID, source
task/execution, reason and remaining cooldown" after a suspension; before FEAT-599 no
engine response carried the source task/execution and `render_suspension_history()`
had no production caller.
"""

from __future__ import annotations

from parrot.flows.dev_loop.sdd_coder.engine import SddCoderEngine
from parrot.flows.dev_loop.sdd_coder.models import RosterConfig, RosterSeat


async def test_plan_carries_suspension_summary_after_suspension(git_sandbox_feature, noop_probe) -> None:
    """`coder_plan` and the pool view name the incident, its source task and its execution (AC2)."""
    worktree, _feature_branch, base_path, _index_path = git_sandbox_feature
    roster = RosterConfig(seats=[RosterSeat(label="h", kind="native")])
    engine = SddCoderEngine(roster=roster, probe=noop_probe, worktree_base_path=str(base_path))
    execution_id = "550e0000-0000-0000-0000-000000000599"
    begin_view = await engine.begin_execution("demo", str(worktree), execution_id)
    assert begin_view.suspension_summary == ""

    prep = await engine.prepare_native("demo", str(worktree), "TASK-0001", execution_id)
    receipt = await engine.suspend_model(execution_id, prep.attempt_uid, "timeout", "log:evidence")

    plan = await engine.plan("demo", str(worktree), execution_id=execution_id)
    summary = plan.suspension_summary
    for needle in (receipt.suspension_id, "TASK-0001", execution_id, "timeout", "remaining_cooldown_s="):
        assert needle in summary, needle

    pool_view = engine._executions[execution_id].view()  # noqa: SLF001
    assert pool_view.suspension_summary == summary
    seat = pool_view.seats[0]
    assert seat.suspended is True
    assert seat.suspension_source == "native_report"
    assert seat.source_task_id == "TASK-0001"
    assert seat.source_execution_id == execution_id


async def test_new_execution_inherits_attribution_from_durable_history(git_sandbox_feature, noop_probe) -> None:
    """A later execution on the same worktree (new engine) sees WHO suspended the inherited seat (AC3)."""
    worktree, _feature_branch, base_path, _index_path = git_sandbox_feature
    roster = RosterConfig(seats=[RosterSeat(label="h", kind="native")])
    engine = SddCoderEngine(roster=roster, probe=noop_probe, worktree_base_path=str(base_path))
    exec_a = "550e0000-0000-0000-0000-0000000005a1"
    await engine.begin_execution("demo", str(worktree), exec_a)
    prep = await engine.prepare_native("demo", str(worktree), "TASK-0001", exec_a)
    receipt = await engine.suspend_model(exec_a, prep.attempt_uid, "timeout", "log:evidence")

    # A second engine instance (as after a server restart) on the same worktree: the only
    # thing it shares with the first is the durable suspension ledger under the worktree.
    engine_b = SddCoderEngine(roster=roster, probe=noop_probe, worktree_base_path=str(base_path))
    exec_b = "550e0000-0000-0000-0000-0000000005b2"
    view_b = await engine_b.begin_execution("demo", str(worktree), exec_b)

    # The excluded identity is filtered out BEFORE the probe (FEAT-559 AC-4), so it has no
    # seat view to attribute -- the summary is what tells the worker who suspended it and why.
    for needle in (receipt.suspension_id, "TASK-0001", exec_a, "timeout", "remaining_cooldown_s="):
        assert needle in view_b.suspension_summary, needle
    assert not any(seat.suspended for seat in view_b.seats)
    assert view_b.fallback_required is True and view_b.fallback_reason == "all_seats_exhausted"
