"""Integration test for dev-loop in-flight gate upgrade (FEAT-890 AC9).

Tests that a recorded legacy envelope (TASK-5616) can be loaded into the
store/session and resolved via the runner.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from parrot.bots.flows.core.gates import GateHost, GateRecord, GateSpec, register_gate_kind
from parrot.flows.dev_loop.gate_adapter import DevLoopGateAdapter, register_devloop_gate_kinds
from parrot.flows.dev_loop.session_state import (
    ActionEnvelope,
    ApprovalGate,
    DevLoopSessionState,
    SessionHost,
    session_channel,
)

FIXTURE = Path(__file__).parent / "fixtures" / "legacy_gate_envelopes.json"


def _load_fixture() -> dict[str, Any]:
    """Load the legacy gate envelopes fixture."""
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _recorded_envelopes() -> list[ActionEnvelope]:
    """Load envelopes from the fixture."""
    data = _load_fixture()
    return [ActionEnvelope.model_validate(env) for env in data["envelopes"]]


def _recorded_gates() -> list[ApprovalGate]:
    """Load gates from the fixture."""
    data = _load_fixture()
    return [
        ApprovalGate.model_validate(env["action"]["gate"])
        for env in data["envelopes"]
        if env["action"]["type"] == "gate/opened"
    ]


class InMemoryGateStore:
    """In-memory gate store for testing."""

    def __init__(self) -> None:
        self.records: dict[str, GateRecord] = {}

    async def put(self, record: GateRecord) -> None:
        self.records[record.gate_id] = record

    async def get(self, gate_id: str) -> GateRecord | None:
        return self.records.get(gate_id)

    async def pending(self, owner: str | None = None) -> list[GateRecord]:
        return [
            record
            for record in self.records.values()
            if record.status == "pending" and (owner is None or record.owner == owner)
        ]


@pytest.fixture(autouse=True)
def _register_kinds() -> None:
    """Ensure dev-loop gate kinds are registered."""
    register_devloop_gate_kinds()


@pytest.fixture
def gate_store() -> InMemoryGateStore:
    """Create an in-memory gate store."""
    return InMemoryGateStore()


@pytest.fixture
def gate_host(gate_store: InMemoryGateStore) -> GateHost:
    """Create a gate host with the in-memory store."""
    return GateHost(gate_store)


@pytest.fixture
def session_host() -> SessionHost:
    """Create a session host for the legacy run."""
    return SessionHost(run_id="legacy-gates-run")


def test_load_legacy_envelopes_into_session_host(session_host: SessionHost) -> None:
    """Load recorded envelopes into a SessionHost and verify state."""
    envelopes = _recorded_envelopes()

    # Apply each envelope to the session host.
    for envelope in envelopes:
        session_host.apply(envelope.action, origin=envelope.origin)

    # Verify the session state contains the gates.
    state = session_host.state
    assert len(state.gates) > 0

    # Verify the gate store is seeded with generic records.
    session_host._seed_gate_store()
    gate_store = session_host._gate_store
    assert len(gate_store.records) > 0


@pytest.mark.asyncio
async def test_resolve_legacy_gate_via_gate_host(session_host: SessionHost, gate_host: GateHost) -> None:
    """Resolve a legacy gate via the generic GateHost."""
    # Seed the session host with envelopes.
    envelopes = _recorded_envelopes()
    for envelope in envelopes:
        session_host.apply(envelope.action, origin=envelope.origin)

    # Seed the gate store from the session host.
    session_host._seed_gate_store()

    # Get a pending gate from the session state.
    pending_gates = [g for g in session_host.state.gates.values() if g.status == "pending"]
    assert len(pending_gates) > 0

    gate = pending_gates[0]

    # Convert to a generic GateRecord and put in the test gate host.
    record = DevLoopGateAdapter.to_record(gate, owner=f"legacy-gates-run:{gate.node_id}")
    await gate_host.store.put(record)

    # Resolve the gate via the generic GateHost.
    resolved = await gate_host.resolve(
        gate.gate_id,
        resolution="approved",
        resolved_by="user:test",
        comment="Resolved via GateHost.",
    )

    assert resolved.status == "approved"
    assert resolved.resolved_by == "user:test"


@pytest.mark.asyncio
async def test_resume_flow_with_legacy_gate_envelopes(session_host: SessionHost, gate_host: GateHost) -> None:
    """Simulate resuming a flow with legacy gate envelopes in-flight."""
    # Load the envelopes into the session host.
    envelopes = _recorded_envelopes()
    for envelope in envelopes:
        session_host.apply(envelope.action, origin=envelope.origin)

    # Seed the gate store.
    session_host._seed_gate_store()

    # Get the pending gates.
    pending_gates = [g for g in session_host.state.gates.values() if g.status == "pending"]
    assert len(pending_gates) > 0

    # Resolve each pending gate.
    for gate in pending_gates:
        # Convert to generic record and add to our gate host.
        record = DevLoopGateAdapter.to_record(gate, owner=f"legacy-gates-run:{gate.node_id}")
        await gate_host.store.put(record)

        # Resolve via the generic gate host.
        resolved = await gate_host.resolve(
            gate.gate_id,
            resolution="approved",
            resolved_by="user:test",
            comment="Approved after upgrade test.",
        )
        assert resolved.status == "approved"

    # Verify no pending gates remain.
    remaining_pending = await gate_host.store.pending()
    assert len(remaining_pending) == 0


def test_gate_adapter_roundtrip_integration() -> None:
    """Verify DevLoopGateAdapter roundtrip works for all recorded gates."""
    gates = _recorded_gates()

    for gate in gates:
        # Convert to generic record.
        record = DevLoopGateAdapter.to_record(gate, owner=f"legacy-gates-run:{gate.node_id}")

        # Verify the record.
        assert record.gate_id == gate.gate_id
        assert record.kind == gate.kind

        # Convert back to ApprovalGate.
        back = DevLoopGateAdapter.from_record(record, node_id=gate.node_id)

        # Verify roundtrip.
        assert back.gate_id == gate.gate_id
        assert back.kind == gate.kind
        assert back.status == gate.status
        assert back.node_id == gate.node_id


def test_session_host_gate_lifecycle() -> None:
    """Test the full gate lifecycle through SessionHost."""
    host = SessionHost(run_id="test-lifecycle")

    # Create a gate via the session host.
    from parrot.flows.dev_loop.session_state import GateOpened

    gate = ApprovalGate(
        gate_id="test-gate-001",
        kind="manual_criterion",
        node_id="qa",
        status="pending",
        on_expiry="fail",
        title="Test gate",
        instructions="Test instructions",
        payload_ref="test://ref",
        opened_at=1000.0,
        expires_at=None,
        resolved_by="",
        resolved_at=None,
        comment="",
        questions=[],
        answers={},
    )

    action = GateOpened(gate=gate)
    host.apply(action)

    # Verify the gate is in the state.
    assert "test-gate-001" in host.state.gates

    # Seed the gate store.
    host._seed_gate_store()

    # Verify the generic record exists.
    assert "test-gate-001" in host._gate_store.records

    # Resolve the gate via the session host.
    from parrot.flows.dev_loop.session_state import GateResolved

    resolve_action = GateResolved(
        gate_id="test-gate-001",
        resolution="approved",
        resolved_by="user:test",
        comment="Approved",
        answers={},
    )
    host.apply(resolve_action)

    # Verify the gate status changed.
    assert host.state.gates["test-gate-001"].status == "approved"
