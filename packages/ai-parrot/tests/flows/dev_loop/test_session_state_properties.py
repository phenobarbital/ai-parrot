"""Hypothesis property suite for the session-state core (FEAT-322 TASK-1850).

Encodes the contract-level invariants the spec relies on (§1 G1, §7 "Host
crash mid-run", §5 acceptance criteria rows 1-3):

* P1 — fold/replay equivalence: replaying the envelope log through the pure
  reducer reproduces the host's live state exactly (the crash-rebuild and
  Svelte-port invariant).
* P2 — reducer totality: ``reduce`` never raises for any (state, action)
  pair, including terminal states and dangling gate/dispatch references.
* P3 — terminal-phase stickiness.
* P4 — gate arbitration: first-writer-wins, validated at the host layer.
* P5 — expiry policies (fail-closed / fail-open).
* P6 — root reducer totality + fold.

Plus two structural gates: transport purity (no aiohttp/redis/jsonrpc
imports) and the JSON-Schema discriminator export used by the future
Svelte codegen hook.
"""

from __future__ import annotations

import ast
import functools
import inspect
from pathlib import Path

import pytest
from hypothesis import given, settings, strategies as st
from pydantic import TypeAdapter

from parrot.flows.dev_loop.session_state import (
    DevLoopAction,
    DevLoopSessionState,
    GateAlreadyResolvedError,
    RootAction,
    RunRegistryState,
    RunSummary,
    SessionHost,
    reduce,
    reduce_root,
    session_channel,
)
from parrot.flows.dev_loop import session_state as session_state_module

RUN_ID = "run-prop0001"

_NODE_IDS = (
    "intent_classifier", "bug_intake", "research", "development",
    "qa", "deployment_handoff", "revision_handoff", "failure_handler",
    "close",
)
_GATE_KINDS = ("manual_criterion", "deployment_approval", "revision_approval",
               "plan_approval")
_GATE_STATUSES = ("pending", "approved", "rejected", "expired")

st_ts = st.floats(min_value=1e9, max_value=2e9, allow_nan=False, allow_infinity=False)
st_node_id = st.sampled_from(_NODE_IDS)
st_gate_id = st.sampled_from(["g1", "g2", "g3"])  # small pool → forces collisions
st_short_text = st.text(max_size=20)


# ---------------------------------------------------------------------------
# Strategies — session-channel actions (arbitrary, including invalid orderings)
# ---------------------------------------------------------------------------


def _run_created():
    return st.builds(
        session_state_module.RunCreated,
        ts=st_ts, run_id=st.just(RUN_ID), revision=st.booleans(),
        work_kind=st.sampled_from(["bug", "enhancement", "new_feature"]),
        summary=st_short_text,
    )


def _run_cancelled():
    return st.builds(session_state_module.RunCancelled, ts=st_ts, requested_by=st_short_text)


def _run_closed():
    return st.builds(
        session_state_module.RunClosed, ts=st_ts,
        outcome=st.sampled_from(["succeeded", "failed"]),
        jira_issue_key=st_short_text, pr_url=st_short_text,
    )


def _node_started():
    return st.builds(session_state_module.NodeStarted, ts=st_ts, node_id=st_node_id)


def _node_completed():
    return st.builds(
        session_state_module.NodeCompleted, ts=st_ts, node_id=st_node_id,
        summary=st.dictionaries(st_short_text, st_short_text, max_size=3),
    )


def _node_failed():
    return st.builds(session_state_module.NodeFailed, ts=st_ts, node_id=st_node_id, error=st_short_text)


def _node_skipped():
    return st.builds(session_state_module.NodeSkipped, ts=st_ts, node_id=st_node_id)


def _dispatch_queued():
    return st.builds(session_state_module.DispatchQueued, ts=st_ts, node_id=st_node_id, dispatcher=st_short_text)


def _dispatch_started():
    return st.builds(session_state_module.DispatchStarted, ts=st_ts, node_id=st_node_id, terminal=st_short_text)


def _dispatch_delta():
    return st.builds(session_state_module.DispatchDelta, ts=st_ts, node_id=st_node_id)


def _dispatch_tool_use():
    return st.builds(session_state_module.DispatchToolUse, ts=st_ts, node_id=st_node_id, tool_name=st_short_text)


def _dispatch_tool_result():
    return st.builds(session_state_module.DispatchToolResult, ts=st_ts, node_id=st_node_id)


def _dispatch_output_invalid():
    return st.builds(session_state_module.DispatchOutputInvalid, ts=st_ts, node_id=st_node_id, error=st_short_text)


def _dispatch_failed():
    return st.builds(session_state_module.DispatchFailed, ts=st_ts, node_id=st_node_id, error=st_short_text)


def _dispatch_completed():
    return st.builds(session_state_module.DispatchCompleted, ts=st_ts, node_id=st_node_id)


def _approval_gate():
    return st.builds(
        session_state_module.ApprovalGate,
        gate_id=st_gate_id, kind=st.sampled_from(_GATE_KINDS), node_id=st_node_id,
        status=st.sampled_from(_GATE_STATUSES),
        on_expiry=st.sampled_from(["fail", "approve"]),
        title=st_short_text, instructions=st_short_text, payload_ref=st_short_text,
        opened_at=st_ts, expires_at=st.one_of(st.none(), st_ts),
        resolved_by=st_short_text,
        resolved_at=st.one_of(st.none(), st_ts),
        comment=st_short_text,
    )


def _gate_opened():
    return st.builds(session_state_module.GateOpened, ts=st_ts, gate=_approval_gate())


def _gate_resolved():
    return st.builds(
        session_state_module.GateResolved, ts=st_ts, gate_id=st_gate_id,
        resolution=st.sampled_from(["approved", "rejected"]), resolved_by=st_short_text,
        comment=st_short_text,
    )


def _gate_expired():
    return st.builds(session_state_module.GateExpired, ts=st_ts, gate_id=st_gate_id)


def _jira_linked():
    return st.builds(session_state_module.JiraLinked, ts=st_ts, issue_key=st_short_text)


def _pr_linked():
    return st.builds(session_state_module.PullRequestLinked, ts=st_ts, pr_url=st_short_text, changeset=st_short_text)


def any_action():
    """Strategy generating any single :data:`DevLoopAction` variant.

    Deliberately includes actions that are invalid against a fresh state
    (e.g. ``gate/resolved`` before any ``gate/opened``, ``node/completed``
    for a node never started) — proving reducer totality requires feeding
    it nonsense, not just well-formed sequences.
    """
    return st.one_of(
        _run_created(), _run_cancelled(), _run_closed(),
        _node_started(), _node_completed(), _node_failed(), _node_skipped(),
        _dispatch_queued(), _dispatch_started(), _dispatch_delta(),
        _dispatch_tool_use(), _dispatch_tool_result(),
        _dispatch_output_invalid(), _dispatch_failed(), _dispatch_completed(),
        _gate_opened(), _gate_resolved(), _gate_expired(),
        _jira_linked(), _pr_linked(),
    )


def action_sequences(min_size: int = 0, max_size: int = 12):
    """Strategy generating arbitrary sequences of :data:`DevLoopAction`."""
    return st.lists(any_action(), min_size=min_size, max_size=max_size)


def _fresh_state() -> DevLoopSessionState:
    return DevLoopSessionState(run_id=RUN_ID, channel=session_channel(RUN_ID))


# ---------------------------------------------------------------------------
# P1 — fold/replay equivalence
# ---------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(actions=action_sequences())
def test_fold_replay_equals_state(actions):
    host = SessionHost(RUN_ID)
    for action in actions:
        host.apply(action)

    replayed_actions = [e.action for e in host.replay_since(0)]
    folded = functools.reduce(reduce, replayed_actions, _fresh_state())
    assert folded == host.state


# ---------------------------------------------------------------------------
# P2 — reducer totality (never raises, incl. terminal / dangling refs)
# ---------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(state=st.builds(_fresh_state), action=any_action())
def test_reducer_total_never_raises(state, action):
    # Must not raise for ANY (state, action) pair — including a fresh state
    # receiving a dangling gate/dispatch reference or a late action.
    result = reduce(state, action)
    assert isinstance(result, DevLoopSessionState)


@settings(max_examples=100, deadline=None)
@given(action=any_action())
def test_reducer_total_against_terminal_states(action):
    for outcome in ("succeeded", "failed", "cancelled"):
        state = _fresh_state().model_copy(update={"phase": outcome})
        result = reduce(state, action)
        assert isinstance(result, DevLoopSessionState)


# ---------------------------------------------------------------------------
# P3 — terminal-phase stickiness
# ---------------------------------------------------------------------------


@settings(max_examples=200, deadline=None)
@given(actions=action_sequences(min_size=1, max_size=8))
def test_terminal_phase_sticky(actions):
    state = _fresh_state()
    for outcome in ("succeeded", "failed", "cancelled"):
        terminal_state = state.model_copy(update={"phase": outcome})
        result = functools.reduce(reduce, actions, terminal_state)
        assert result.phase == outcome


# ---------------------------------------------------------------------------
# P4 — gate arbitration (first-writer-wins, host-validated)
# ---------------------------------------------------------------------------


@settings(max_examples=100, deadline=None)
@given(
    resolutions=st.lists(
        st.tuples(st.sampled_from(["approved", "rejected"]), st_short_text),
        min_size=2, max_size=5,
    )
)
def test_arbitration_first_writer_wins(resolutions):
    host = SessionHost(RUN_ID)
    gate_id, _ = host.open_gate(kind="manual_criterion", node_id="qa", title="x")

    first_resolution, first_resolver = resolutions[0]
    host.resolve_gate(gate_id, first_resolution, resolved_by=first_resolver)

    for resolution, resolver in resolutions[1:]:
        with pytest.raises(GateAlreadyResolvedError):
            host.resolve_gate(gate_id, resolution, resolved_by=resolver)

    resolved_envelopes = [
        e for e in host.replay_since(0) if e.action.type == "gate/resolved"
    ]
    assert len(resolved_envelopes) == 1
    assert host.state.gates[gate_id].resolved_by == first_resolver
    assert host.state.gates[gate_id].status == first_resolution


# ---------------------------------------------------------------------------
# P5 — expiry policies
# ---------------------------------------------------------------------------


@settings(max_examples=50, deadline=None)
@given(kind=st.sampled_from(_GATE_KINDS))
def test_expiry_fail_closed_ends_expired(kind):
    host = SessionHost(RUN_ID)
    gate_id, _ = host.open_gate(
        kind=kind, node_id="qa", title="x", ttl_seconds=10, on_expiry="fail",
    )
    host.expire_due_gates(now=host.state.gates[gate_id].opened_at + 20)
    assert host.state.gates[gate_id].status == "expired"


@settings(max_examples=50, deadline=None)
@given(kind=st.sampled_from(_GATE_KINDS))
def test_expiry_fail_open_ends_approved_by_system(kind):
    host = SessionHost(RUN_ID)
    gate_id, _ = host.open_gate(
        kind=kind, node_id="qa", title="x", ttl_seconds=10, on_expiry="approve",
    )
    host.expire_due_gates(now=host.state.gates[gate_id].opened_at + 20)
    gate = host.state.gates[gate_id]
    assert gate.status == "approved"
    assert gate.resolved_by == "system:ttl-auto-approve"


# ---------------------------------------------------------------------------
# P6 — root reducer totality + fold
# ---------------------------------------------------------------------------


def _run_summary():
    return st.builds(
        RunSummary,
        run_id=st.sampled_from(["run-a", "run-b", "run-c"]),
        phase=st.sampled_from(["created", "running", "awaiting_gate",
                               "succeeded", "failed", "cancelled"]),
        work_kind=st_short_text, summary=st_short_text,
        jira_issue_key=st_short_text, pr_url=st_short_text,
        pending_gate_count=st.integers(min_value=0, max_value=5),
        created_at=st_ts, finished_at=st.one_of(st.none(), st_ts),
    )


def _root_action():
    return st.one_of(
        st.builds(session_state_module.RunAdded, ts=st_ts, summary=_run_summary()),
        st.builds(session_state_module.RunSummaryChanged, ts=st_ts, summary=_run_summary()),
        st.builds(
            session_state_module.RunRemoved, ts=st_ts,
            run_id=st.sampled_from(["run-a", "run-b", "run-c", "run-unknown"]),
        ),
    )


@settings(max_examples=150, deadline=None)
@given(actions=st.lists(_root_action(), max_size=10))
def test_root_reducer_total_never_raises(actions):
    state = RunRegistryState()
    for action in actions:
        state = reduce_root(state, action)
        assert isinstance(state, RunRegistryState)


@settings(max_examples=150, deadline=None)
@given(actions=st.lists(_root_action(), max_size=10))
def test_root_reducer_fold_is_deterministic(actions):
    state1 = functools.reduce(reduce_root, actions, RunRegistryState())
    state2 = functools.reduce(reduce_root, actions, RunRegistryState())
    assert state1 == state2


def test_root_run_removed_of_unknown_run_is_noop():
    state = RunRegistryState()
    result = reduce_root(state, session_state_module.RunRemoved(run_id="ghost"))
    assert result == state


# ---------------------------------------------------------------------------
# Transport purity — no aiohttp / redis / jsonrpc imports
# ---------------------------------------------------------------------------


def test_no_transport_imports():
    """Parse ``session_state.py``'s AST and assert no forbidden imports.

    AST parsing (rather than inspecting ``sys.modules``) is exact: it
    catches every import statement regardless of whether the imported
    name is actually used or re-exported.
    """
    source_path = Path(inspect.getfile(session_state_module))
    tree = ast.parse(source_path.read_text(), filename=str(source_path))
    forbidden = ("aiohttp", "redis", "jsonrpc")

    imported_roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported_roots.add(node.module.split(".")[0])

    for banned in forbidden:
        assert banned not in imported_roots, (
            f"session_state.py must not import {banned!r} — "
            f"found in: {sorted(imported_roots)}"
        )

    # Positive check: only pydantic + stdlib roots are present.
    stdlib_roots = {"__future__", "asyncio", "time", "uuid", "typing"}
    assert imported_roots <= (stdlib_roots | {"pydantic"}), (
        f"unexpected non-stdlib/non-pydantic import roots: "
        f"{imported_roots - stdlib_roots - {'pydantic'}}"
    )


# ---------------------------------------------------------------------------
# Schema export — discriminator mapping for the future Svelte codegen hook
# ---------------------------------------------------------------------------


def test_action_union_schema_has_discriminator():
    schema = TypeAdapter(DevLoopAction).json_schema()
    assert "oneOf" in schema
    assert "discriminator" in schema
    assert schema["discriminator"]["propertyName"] == "type"
    # All 20 documented action types are present in the mapping.
    assert len(schema["discriminator"]["mapping"]) == 20


def test_root_action_union_schema_has_discriminator():
    schema = TypeAdapter(RootAction).json_schema()
    assert "oneOf" in schema
    assert "discriminator" in schema
    assert schema["discriminator"]["propertyName"] == "type"
    assert set(schema["discriminator"]["mapping"]) == {
        "root/runAdded", "root/runSummaryChanged", "root/runRemoved",
    }
