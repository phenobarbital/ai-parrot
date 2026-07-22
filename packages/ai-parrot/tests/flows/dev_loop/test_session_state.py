"""Basic unit tests for the session-state core (FEAT-322 TASK-1848/1849).

Covers construction, one ``reduce()`` step per action type, the root
reducer, envelope round-tripping, the ``SessionHost`` (sequencing, gate
arbitration, expiry, ``wait_gate``) and the migration shims. The
hypothesis property suite (fold invariant, totality, arbitration, expiry,
shim mappings) lives in ``test_session_state_properties.py`` (TASK-1850).
"""

from __future__ import annotations

import asyncio

import pytest

from parrot.flows.dev_loop.session_state import (
    ActionEnvelope,
    ActionOrigin,
    ApprovalGate,
    DevLoopSessionState,
    DispatchCompleted,
    DispatchDelta,
    DispatchFailed,
    DispatchOutputInvalid,
    DispatchQueued,
    DispatchStarted,
    DispatchToolResult,
    DispatchToolUse,
    GateAlreadyResolvedError,
    GateExpired,
    GateNotFoundError,
    GateOpened,
    GateResolved,
    JiraLinked,
    NodeCompleted,
    NodeFailed,
    NodeSkipped,
    NodeStarted,
    PullRequestLinked,
    RunAdded,
    RunCancelled,
    RunClosed,
    RunCreated,
    RunRegistryState,
    RunRemoved,
    RunSummary,
    RunSummaryChanged,
    SessionHost,
    Snapshot,
    action_from_dispatch_event,
    action_from_flow_event,
    changeset_channel,
    reduce,
    reduce_root,
    session_channel,
    terminal_channel,
)

RUN_ID = "run-test0001"


def _fresh_state() -> DevLoopSessionState:
    return DevLoopSessionState(run_id=RUN_ID, channel=session_channel(RUN_ID))


# ---------------------------------------------------------------------------
# Channel helpers
# ---------------------------------------------------------------------------


def test_channel_helpers():
    assert session_channel(RUN_ID) == f"parrot-session:/{RUN_ID}"
    assert terminal_channel(RUN_ID, "qa") == f"parrot-terminal:/{RUN_ID}/qa"
    assert changeset_channel(RUN_ID) == f"parrot-changeset:/{RUN_ID}"


# ---------------------------------------------------------------------------
# Run lifecycle
# ---------------------------------------------------------------------------


def test_reduce_run_created_sets_running():
    state = _fresh_state()
    state = reduce(state, RunCreated(run_id=RUN_ID, work_kind="bug", summary="x"))
    assert state.phase == "running"
    assert state.work_kind == "bug"
    assert state.summary == "x"


def test_reduce_run_cancelled_sets_cancelled():
    state = reduce(_fresh_state(), RunCreated(run_id=RUN_ID))
    state = reduce(state, RunCancelled(requested_by="alice"))
    assert state.phase == "cancelled"
    assert state.cancel_requested_by == "alice"


def test_reduce_run_closed_sets_outcome():
    state = reduce(_fresh_state(), RunCreated(run_id=RUN_ID))
    state = reduce(state, RunClosed(outcome="succeeded", jira_issue_key="ABC-1", pr_url="http://pr"))
    assert state.phase == "succeeded"
    assert state.jira_issue_key == "ABC-1"
    assert state.pr_url == "http://pr"


def test_terminal_phase_sticky_after_cancel():
    state = reduce(_fresh_state(), RunCreated(run_id=RUN_ID))
    state = reduce(state, RunCancelled(requested_by="alice"))
    # Further node activity must not change a terminal phase.
    state2 = reduce(state, NodeStarted(node_id="qa"))
    assert state2.phase == "cancelled"
    # A second cancel is also a no-op on phase (still terminal-sticky).
    state3 = reduce(state2, RunCancelled(requested_by="bob"))
    assert state3.phase == "cancelled"
    assert state3.cancel_requested_by == "alice"


# ---------------------------------------------------------------------------
# Node lifecycle
# ---------------------------------------------------------------------------


def test_reduce_node_started_sets_running():
    state = reduce(_fresh_state(), NodeStarted(node_id="qa"))
    assert state.nodes["qa"].status == "running"


def test_reduce_node_completed_sets_summary():
    state = reduce(_fresh_state(), NodeCompleted(node_id="qa", summary={"passed": "true"}))
    assert state.nodes["qa"].status == "completed"
    assert state.nodes["qa"].summary == {"passed": "true"}


def test_reduce_node_failed_sets_error():
    state = reduce(_fresh_state(), NodeFailed(node_id="qa", error="boom"))
    assert state.nodes["qa"].status == "failed"
    assert state.nodes["qa"].error == "boom"
    assert state.error == "boom"


def test_reduce_node_skipped():
    state = reduce(_fresh_state(), NodeSkipped(node_id="bug_intake"))
    assert state.nodes["bug_intake"].status == "skipped"


# ---------------------------------------------------------------------------
# Dispatch lifecycle
# ---------------------------------------------------------------------------


def test_reduce_dispatch_queued_and_started():
    state = reduce(_fresh_state(), DispatchQueued(node_id="development", dispatcher="claude-code"))
    assert state.nodes["development"].dispatch.status == "queued"
    assert state.nodes["development"].dispatch.dispatcher == "claude-code"

    state = reduce(state, DispatchStarted(node_id="development", terminal="parrot-terminal:/x/development"))
    assert state.nodes["development"].dispatch.status == "running"
    assert state.nodes["development"].dispatch.terminal == "parrot-terminal:/x/development"


def test_reduce_dispatch_delta_increments_message_count():
    state = reduce(_fresh_state(), DispatchQueued(node_id="development"))
    state = reduce(state, DispatchDelta(node_id="development"))
    state = reduce(state, DispatchDelta(node_id="development"))
    assert state.nodes["development"].dispatch.message_count == 2


def test_reduce_dispatch_tool_use_increments_tool_use_count():
    state = reduce(_fresh_state(), DispatchQueued(node_id="development"))
    state = reduce(state, DispatchToolUse(node_id="development", tool_name="Read"))
    assert state.nodes["development"].dispatch.tool_use_count == 1


def test_reduce_dispatch_tool_result_is_noop_on_counters():
    state = reduce(_fresh_state(), DispatchQueued(node_id="development"))
    before = state.nodes["development"].dispatch
    state = reduce(state, DispatchToolResult(node_id="development"))
    assert state.nodes["development"].dispatch == before


def test_reduce_dispatch_output_invalid():
    state = reduce(_fresh_state(), DispatchQueued(node_id="qa"))
    state = reduce(state, DispatchOutputInvalid(node_id="qa", error="bad json"))
    assert state.nodes["qa"].dispatch.status == "output_invalid"
    assert state.nodes["qa"].dispatch.last_error == "bad json"


def test_reduce_dispatch_failed():
    state = reduce(_fresh_state(), DispatchQueued(node_id="qa"))
    state = reduce(state, DispatchFailed(node_id="qa", error="crash"))
    assert state.nodes["qa"].dispatch.status == "failed"
    assert state.nodes["qa"].dispatch.last_error == "crash"


def test_reduce_dispatch_completed():
    state = reduce(_fresh_state(), DispatchQueued(node_id="qa"))
    state = reduce(state, DispatchCompleted(node_id="qa"))
    assert state.nodes["qa"].dispatch.status == "completed"


# ---------------------------------------------------------------------------
# Gates (HITL)
# ---------------------------------------------------------------------------


def _open_gate(node_id: str = "qa") -> ApprovalGate:
    return ApprovalGate(gate_id="g1", kind="manual_criterion", node_id=node_id)


def test_reduce_gate_opened_sets_awaiting_gate():
    state = reduce(_fresh_state(), GateOpened(gate=_open_gate()))
    assert state.phase == "awaiting_gate"
    assert "g1" in state.gates
    assert state.gates["g1"].status == "pending"


def test_reduce_gate_resolved_clears_awaiting_gate():
    state = reduce(_fresh_state(), GateOpened(gate=_open_gate()))
    state = reduce(state, GateResolved(gate_id="g1", resolution="approved", resolved_by="alice"))
    assert state.gates["g1"].status == "approved"
    assert state.gates["g1"].resolved_by == "alice"
    assert state.phase == "running"


def test_reduce_conflicting_gate_resolve_is_noop():
    state = reduce(_fresh_state(), GateOpened(gate=_open_gate()))
    state = reduce(state, GateResolved(gate_id="g1", resolution="approved", resolved_by="alice"))
    # A second, conflicting resolve against the same (already-resolved) gate
    # must be a pure no-op in the reducer (host is the layer that rejects it
    # before it ever becomes an action).
    state2 = reduce(state, GateResolved(gate_id="g1", resolution="rejected", resolved_by="bob"))
    assert state2.gates["g1"].status == "approved"
    assert state2.gates["g1"].resolved_by == "alice"


def test_reduce_gate_resolved_unknown_gate_is_noop():
    state = _fresh_state()
    state2 = reduce(state, GateResolved(gate_id="missing", resolution="approved", resolved_by="alice"))
    assert state2 == state


def test_reduce_gate_expired():
    state = reduce(_fresh_state(), GateOpened(gate=_open_gate()))
    state = reduce(state, GateExpired(gate_id="g1"))
    assert state.gates["g1"].status == "expired"
    assert state.phase == "running"


# ---------------------------------------------------------------------------
# Projections
# ---------------------------------------------------------------------------


def test_reduce_jira_linked():
    state = reduce(_fresh_state(), JiraLinked(issue_key="ABC-2"))
    assert state.jira_issue_key == "ABC-2"


def test_reduce_pr_linked():
    state = reduce(_fresh_state(), PullRequestLinked(pr_url="http://pr", changeset="parrot-changeset:/x"))
    assert state.pr_url == "http://pr"


# ---------------------------------------------------------------------------
# Root reducer (run registry)
# ---------------------------------------------------------------------------


def test_root_run_added_and_removed():
    registry = RunRegistryState()
    summary = RunSummary(run_id=RUN_ID, phase="running")
    registry = reduce_root(registry, RunAdded(summary=summary))
    assert RUN_ID in registry.runs
    assert registry.runs[RUN_ID].phase == "running"

    registry = reduce_root(registry, RunRemoved(run_id=RUN_ID))
    assert RUN_ID not in registry.runs


def test_root_run_summary_changed():
    registry = RunRegistryState()
    registry = reduce_root(registry, RunAdded(summary=RunSummary(run_id=RUN_ID, phase="running")))
    registry = reduce_root(
        registry,
        RunSummaryChanged(summary=RunSummary(run_id=RUN_ID, phase="awaiting_gate", pending_gate_count=1)),
    )
    assert registry.runs[RUN_ID].phase == "awaiting_gate"
    assert registry.runs[RUN_ID].pending_gate_count == 1


def test_root_run_removed_unknown_is_noop():
    registry = RunRegistryState()
    registry2 = reduce_root(registry, RunRemoved(run_id="does-not-exist"))
    assert registry2 == registry


def test_root_channel_default():
    registry = RunRegistryState()
    assert registry.channel == "parrot-root://"


# ---------------------------------------------------------------------------
# Envelope / Snapshot
# ---------------------------------------------------------------------------


def test_envelope_origin_rejection_roundtrip():
    action = RunCreated(run_id=RUN_ID)
    origin = ActionOrigin(client_id="ui-1", client_seq=3)
    envelope = ActionEnvelope(
        channel=session_channel(RUN_ID),
        server_seq=1,
        action=action,
        origin=origin,
        rejection_reason="",
    )
    dumped = envelope.model_dump()
    restored = ActionEnvelope.model_validate(dumped)
    assert restored.origin == origin
    assert restored.rejection_reason == ""
    assert restored.action.type == "run/created"


def test_envelope_defaults_origin_none_rejection_empty():
    envelope = ActionEnvelope(
        channel=session_channel(RUN_ID), server_seq=1, action=RunCreated(run_id=RUN_ID)
    )
    assert envelope.origin is None
    assert envelope.rejection_reason == ""


def test_snapshot_round_trip():
    state = _fresh_state()
    snapshot = Snapshot(channel=state.channel, state=state, from_seq=0)
    dumped = snapshot.model_dump()
    restored = Snapshot.model_validate(dumped)
    assert restored.state.run_id == RUN_ID
    assert restored.from_seq == 0


# ---------------------------------------------------------------------------
# SessionHost — sequencing, snapshot/replay (FEAT-322 TASK-1849)
# ---------------------------------------------------------------------------


@pytest.fixture
def host() -> SessionHost:
    return SessionHost(RUN_ID)


def test_host_apply_sequences_monotonic_from_1(host: SessionHost):
    e1 = host.apply(RunCreated(run_id=RUN_ID))
    e2 = host.apply(NodeStarted(node_id="qa"))
    assert e1.server_seq == 1
    assert e2.server_seq == 2
    assert host.state.phase == "running"


def test_host_replay_since_filters_by_seq(host: SessionHost):
    host.apply(RunCreated(run_id=RUN_ID))
    host.apply(NodeStarted(node_id="qa"))
    host.apply(NodeCompleted(node_id="qa"))
    replayed = host.replay_since(1)
    assert [e.server_seq for e in replayed] == [2, 3]
    assert host.replay_since(0)[0].server_seq == 1
    assert host.replay_since(3) == []


def test_host_snapshot_reflects_current_seq(host: SessionHost):
    host.apply(RunCreated(run_id=RUN_ID))
    host.apply(NodeStarted(node_id="qa"))
    snap = host.snapshot()
    assert snap.from_seq == 2
    assert snap.state.nodes["qa"].status == "running"
    assert snap.channel == session_channel(RUN_ID)


def test_host_apply_with_origin_round_trips():
    host = SessionHost(RUN_ID)
    origin = ActionOrigin(client_id="ui-1", client_seq=1)
    envelope = host.apply(RunCreated(run_id=RUN_ID), origin=origin)
    assert envelope.origin == origin


def test_host_on_envelope_sink_invoked():
    seen = []
    host = SessionHost(RUN_ID, on_envelope=seen.append)
    host.apply(RunCreated(run_id=RUN_ID))
    assert len(seen) == 1
    assert seen[0].server_seq == 1


def test_on_envelope_sink_exception_swallowed():
    def boom(_envelope):
        raise RuntimeError("redis is down")

    host = SessionHost(RUN_ID, on_envelope=boom)
    # apply() must not raise even though the sink blows up — the in-memory
    # fold must still succeed (never-break-a-run).
    envelope = host.apply(RunCreated(run_id=RUN_ID))
    assert envelope.server_seq == 1
    assert host.state.phase == "running"


# ---------------------------------------------------------------------------
# SessionHost — gate arbitration (first-writer-wins)
# ---------------------------------------------------------------------------


def test_open_gate_returns_id_and_envelope(host: SessionHost):
    gate_id, envelope = host.open_gate(
        kind="manual_criterion", node_id="qa", title="Review this"
    )
    assert gate_id in host.state.gates
    assert host.state.gates[gate_id].status == "pending"
    assert envelope.action.type == "gate/opened"
    assert host.state.phase == "awaiting_gate"


def test_first_writer_wins_second_raises(host: SessionHost):
    gate_id, _ = host.open_gate(kind="manual_criterion", node_id="qa", title="x")
    host.resolve_gate(gate_id, "approved", resolved_by="alice")
    with pytest.raises(GateAlreadyResolvedError, match="alice"):
        host.resolve_gate(gate_id, "rejected", resolved_by="bob")
    # Exactly one gate/resolved envelope in the log.
    resolved_envelopes = [
        e for e in host.replay_since(0) if e.action.type == "gate/resolved"
    ]
    assert len(resolved_envelopes) == 1
    assert host.state.gates[gate_id].resolved_by == "alice"


def test_resolve_gate_unknown_raises_not_found(host: SessionHost):
    with pytest.raises(GateNotFoundError):
        host.resolve_gate("missing", "approved", resolved_by="alice")


# ---------------------------------------------------------------------------
# SessionHost — expiry sweep
# ---------------------------------------------------------------------------


def test_expiry_fail_closed_emits_gate_expired(host: SessionHost):
    gate_id, _ = host.open_gate(
        kind="deployment_approval", node_id="deployment_handoff", title="x",
        ttl_seconds=10, on_expiry="fail",
    )
    envelopes = host.expire_due_gates(now=host.state.gates[gate_id].opened_at + 20)
    assert len(envelopes) == 1
    assert envelopes[0].action.type == "gate/expired"
    assert host.state.gates[gate_id].status == "expired"


def test_expiry_fail_open_auto_approve_audited(host: SessionHost):
    gate_id, _ = host.open_gate(
        kind="plan_approval", node_id="research", title="x",
        ttl_seconds=10, on_expiry="approve",
    )
    envelopes = host.expire_due_gates(now=host.state.gates[gate_id].opened_at + 20)
    assert len(envelopes) == 1
    assert envelopes[0].action.type == "gate/resolved"
    gate = host.state.gates[gate_id]
    assert gate.status == "approved"
    assert gate.resolved_by == "system:ttl-auto-approve"


def test_expiry_sweep_ignores_gates_without_ttl(host: SessionHost):
    gate_id, _ = host.open_gate(kind="manual_criterion", node_id="qa", title="x")
    envelopes = host.expire_due_gates(now=host.state.gates[gate_id].opened_at + 1_000_000)
    assert envelopes == []
    assert host.state.gates[gate_id].status == "pending"


def test_expiry_sweep_ignores_gates_not_yet_due(host: SessionHost):
    gate_id, _ = host.open_gate(
        kind="manual_criterion", node_id="qa", title="x", ttl_seconds=10_000,
    )
    envelopes = host.expire_due_gates(now=host.state.gates[gate_id].opened_at + 1)
    assert envelopes == []
    assert host.state.gates[gate_id].status == "pending"


# ---------------------------------------------------------------------------
# SessionHost — wait_gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wait_gate_already_resolved_returns_immediately(host: SessionHost):
    gate_id, _ = host.open_gate(kind="manual_criterion", node_id="qa", title="x")
    host.resolve_gate(gate_id, "approved", resolved_by="alice")
    gate = await asyncio.wait_for(host.wait_gate(gate_id), timeout=1)
    assert gate.status == "approved"


@pytest.mark.asyncio
async def test_wait_gate_await_then_resolve(host: SessionHost):
    gate_id, _ = host.open_gate(kind="manual_criterion", node_id="qa", title="x")

    async def resolver():
        await asyncio.sleep(0.01)
        host.resolve_gate(gate_id, "rejected", resolved_by="bob")

    waiter = asyncio.ensure_future(host.wait_gate(gate_id))
    resolve_task = asyncio.ensure_future(resolver())
    gate = await asyncio.wait_for(waiter, timeout=1)
    await resolve_task
    assert gate.status == "rejected"
    assert gate.resolved_by == "bob"


@pytest.mark.asyncio
async def test_wait_gate_resolves_on_expiry(host: SessionHost):
    gate_id, _ = host.open_gate(
        kind="plan_approval", node_id="research", title="x",
        ttl_seconds=10, on_expiry="approve",
    )

    async def expirer():
        await asyncio.sleep(0.01)
        host.expire_due_gates(now=host.state.gates[gate_id].opened_at + 20)

    waiter = asyncio.ensure_future(host.wait_gate(gate_id))
    expire_task = asyncio.ensure_future(expirer())
    gate = await asyncio.wait_for(waiter, timeout=1)
    await expire_task
    assert gate.status == "approved"


@pytest.mark.asyncio
async def test_wait_gate_unknown_raises_not_found(host: SessionHost):
    with pytest.raises(GateNotFoundError):
        await host.wait_gate("missing")


# ---------------------------------------------------------------------------
# Migration shims
# ---------------------------------------------------------------------------


def test_shim_flow_event_mappings():
    assert action_from_flow_event("node_started", "qa", 1.0).type == "node/started"
    assert action_from_flow_event("node_completed", "qa", 1.0).type == "node/completed"
    failed = action_from_flow_event("node_failed", "qa", 1.0, error="boom")
    assert failed.type == "node/failed"
    assert failed.error == "boom"
    assert action_from_flow_event("node_skipped", "qa", 1.0).type == "node/skipped"


def test_shim_flow_event_unknown_returns_none():
    assert action_from_flow_event("something_else", "qa", 1.0) is None


def test_shim_flow_event_error_truncated_to_500_chars():
    long_error = "x" * 1000
    action = action_from_flow_event("node_failed", "qa", 1.0, error=long_error)
    assert len(action.error) == 500


def test_shim_dispatch_event_mappings():
    assert action_from_dispatch_event("dispatch.queued", "development", 1.0,
                                       {"dispatcher": "claude-code"}).dispatcher == "claude-code"
    assert action_from_dispatch_event("dispatch.started", "development", 1.0).type == "dispatch/started"
    assert action_from_dispatch_event("dispatch.message", "development", 1.0).type == "dispatch/delta"
    tool_use = action_from_dispatch_event("dispatch.tool_use", "development", 1.0, {"tool_name": "Read"})
    assert tool_use.tool_name == "Read"
    assert action_from_dispatch_event("dispatch.tool_result", "development", 1.0).type == "dispatch/tool_result"
    invalid = action_from_dispatch_event("dispatch.output_invalid", "qa", 1.0, {"error": "bad"})
    assert invalid.error == "bad"
    failed = action_from_dispatch_event("dispatch.failed", "qa", 1.0, {"error": "crash"})
    assert failed.error == "crash"
    assert action_from_dispatch_event("dispatch.completed", "qa", 1.0).type == "dispatch/completed"


def test_shim_dispatch_event_unknown_returns_none():
    assert action_from_dispatch_event("dispatch.something_else", "qa", 1.0) is None


def test_shim_dispatch_event_error_truncated_to_500_chars():
    action = action_from_dispatch_event(
        "dispatch.failed", "qa", 1.0, {"error": "x" * 1000}
    )
    assert len(action.error) == 500
