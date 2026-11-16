"""Round-trip tests for DevLoopGateAdapter over recorded legacy envelopes (FEAT-890 TASK-5616)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, get_args

import pytest
from parrot.bots.flows.core.gates import GateError, GateErrorCode, GateRecord, GateSpec, kinds, registered_kinds
from parrot.flows.dev_loop.gate_adapter import DevLoopGateAdapter, register_devloop_gate_kinds
from parrot.flows.dev_loop.session_state import ActionEnvelope, ApprovalGate, GateKind

FIXTURE = Path(__file__).parent / "fixtures" / "legacy_gate_envelopes.json"


def _load() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _recorded_gates() -> list[ApprovalGate]:
    """Every gate in the fixture: as opened (pending) and as finally folded."""
    data = _load()
    opened = [
        ApprovalGate.model_validate(env["action"]["gate"])
        for env in data["envelopes"]
        if env["action"]["type"] == "gate/opened"
    ]
    final = [ApprovalGate.model_validate(g) for g in data["final_gates"]]
    return opened + final


@pytest.fixture(autouse=True)
def _registered() -> None:
    register_devloop_gate_kinds()


def test_fixture_covers_every_kind_and_status() -> None:
    gates = _recorded_gates()
    assert {g.kind for g in gates} == set(get_args(GateKind))
    assert {g.status for g in gates} == {"pending", "approved", "rejected", "expired"}
    assert any(g.expires_at is not None for g in gates)
    assert any(g.answers for g in gates)
    assert any(g.questions for g in gates)
    assert any(g.on_expiry == "approve" for g in gates)


def test_recorded_envelopes_still_validate() -> None:
    data = _load()
    types = set()
    for raw in data["envelopes"]:
        env = ActionEnvelope.model_validate(raw)
        types.add(env.action.type)
        assert env.model_dump(mode="json") == raw
    assert types == {"gate/opened", "gate/resolved", "gate/expired"}


@pytest.mark.parametrize("gate", _recorded_gates(), ids=lambda g: f"{g.kind}-{g.status}-{g.gate_id[:6]}")
def test_adapter_roundtrip_recorded_envelopes(gate: ApprovalGate) -> None:
    record = DevLoopGateAdapter.to_record(gate, owner=f"legacy-gates-run:{gate.node_id}")
    assert isinstance(record, GateRecord)
    assert record.gate_id == gate.gate_id
    assert record.kind == gate.kind
    assert record.owner == f"legacy-gates-run:{gate.node_id}"
    back = DevLoopGateAdapter.from_record(record, node_id=gate.node_id)
    assert back == gate
    # Survives the record's own JSON persistence as well.
    restored = GateRecord.model_validate_json(record.model_dump_json())
    assert DevLoopGateAdapter.from_record(restored, node_id=gate.node_id) == gate


def test_ttl_derived_from_expiry() -> None:
    gate = next(g for g in _recorded_gates() if g.kind == "deployment_approval")
    record = DevLoopGateAdapter.to_record(gate, owner="o")
    assert record.spec.ttl_seconds == 3600
    assert record.expires_at == gate.expires_at
    pending = next(g for g in _recorded_gates() if g.kind == "manual_criterion")
    assert DevLoopGateAdapter.to_record(pending, owner="o").spec.ttl_seconds is None


def test_six_kinds_registered_idempotently() -> None:
    register_devloop_gate_kinds()
    kinds_now = registered_kinds()
    assert len(get_args(GateKind)) == 6
    for kind in get_args(GateKind):
        assert kinds_now[kind] == f"dev-loop {kind}"


def test_unregistered_kind_rejected_by_to_record(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(kinds, "_KINDS", {})
    gate = _recorded_gates()[0]
    with pytest.raises(GateError) as exc:
        DevLoopGateAdapter.to_record(gate, owner="o")
    assert exc.value.code is GateErrorCode.UNKNOWN_KIND
    assert gate.gate_id in str(exc.value)


def test_unknown_kind_rejected_by_from_record() -> None:
    record = GateRecord(
        gate_id="gate-xyz",
        kind="not_a_devloop_kind",
        owner="o",
        spec=GateSpec(kind="not_a_devloop_kind", title="t"),
        opened_at=1.0,
    )
    with pytest.raises(GateError) as exc:
        DevLoopGateAdapter.from_record(record, node_id="qa")
    assert exc.value.code is GateErrorCode.UNKNOWN_KIND
    assert "gate-xyz" in str(exc.value)
