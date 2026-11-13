"""Delegation tests for SessionHost's generic GateHost bridge."""

from __future__ import annotations

from parrot.bots.flows.core.gates import GateHost, GateSpec, is_registered
from parrot.flows.dev_loop.gate_adapter import DevLoopGateAdapter
from parrot.flows.dev_loop.session_state import SessionHost


def test_open_gate_delegates_to_generic_host() -> None:
    """Opening builds a GateSpec and maps the generic record into the legacy action."""
    host = SessionHost("run-delegation-open")
    gate_id, envelope = host.open_gate(
        kind="open_questions",
        node_id="ideation",
        title="Answer questions",
        instructions="Respond before continuing.",
        payload_ref="artifact://questions",
        ttl_seconds=30,
        on_expiry="fail",
        questions=["Which store?"],
    )

    assert isinstance(host._gate_host, GateHost)
    assert host._gate_host.store is host._gate_store
    assert is_registered("open_questions")
    record = host._gate_store.records[gate_id]
    assert record.spec == GateSpec(
        kind="open_questions",
        title="Answer questions",
        instructions="Respond before continuing.",
        questions=["Which store?"],
        ttl_seconds=30,
        on_expiry="fail",
    )
    assert record.owner == "run-delegation-open:ideation"
    assert record.payload_ref == "artifact://questions"
    assert envelope.action.type == "gate/opened"
    assert envelope.action.gate == host.state.gates[gate_id]
    assert DevLoopGateAdapter.from_record(record, node_id="ideation") == envelope.action.gate


def test_resolve_gate_delegates_and_preserves_legacy_action() -> None:
    """Resolving seeds GateHost from state and translates its result to GateResolved."""
    host = SessionHost("run-delegation-resolve")
    gate_id, _ = host.open_gate(kind="manual_criterion", node_id="qa", title="Review")
    envelope = host.resolve_gate(gate_id, "approved", resolved_by="human:alice", comment="Looks good")

    record = host._gate_store.records[gate_id]
    assert record.status == "approved"
    assert record.resolved_by == "human:alice"
    assert record.comment == "Looks good"
    assert envelope.action.type == "gate/resolved"
    assert host.state.gates[gate_id].status == "approved"
    assert host.state.gates[gate_id].resolved_by == "human:alice"
    assert host.state.gates[gate_id].resolved_at == record.resolved_at


def test_expiry_delegates_to_gate_host_recovery() -> None:
    """Expiry uses GateHost recovery for both fail-open and fail-closed policies."""
    host = SessionHost("run-delegation-expiry")
    fail_id, _ = host.open_gate(
        kind="deployment_approval",
        node_id="deployment_handoff",
        title="Deploy",
        ttl_seconds=10,
        on_expiry="fail",
    )
    approve_id, _ = host.open_gate(
        kind="plan_approval",
        node_id="research",
        title="Plan",
        ttl_seconds=10,
        on_expiry="approve",
    )
    expiry_time = (
        max(
            host.state.gates[fail_id].expires_at or 0,
            host.state.gates[approve_id].expires_at or 0,
        )
        + 1
    )
    envelopes = host.expire_due_gates(now=expiry_time)

    assert [envelope.action.type for envelope in envelopes] == ["gate/expired", "gate/resolved"]
    assert host._gate_store.records[fail_id].status == "expired"
    assert host._gate_store.records[approve_id].status == "approved"
    assert host.state.gates[fail_id].status == "expired"
    assert host.state.gates[approve_id].status == "approved"
    assert host.state.gates[approve_id].resolved_by == "system:ttl-auto-approve"
