"""Unit tests for generic gate models and the kind registry."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from parrot.bots.flows.core.gates import (
    GateError,
    GateErrorCode,
    GateEvent,
    GateRecord,
    GateSpec,
    GateStore,
    PreReviewVerdict,
    is_registered,
    register_gate_kind,
    registered_kinds,
)


def test_gate_models_forbid_extra_fields_and_are_frozen() -> None:
    """Gate models reject unknown data and require explicit copies for changes."""
    with pytest.raises(ValidationError):
        GateSpec(kind="review", title="Review", unexpected="value")

    spec = GateSpec(kind="review", title="Review")
    with pytest.raises(ValidationError):
        spec.title = "Changed"

    verdict = PreReviewVerdict(expert="reviewer", recommendation="approve", summary="Looks good")
    record = GateRecord(gate_id="gate-1", kind="review", owner="owner", spec=spec, opened_at=1.0, pre_review=verdict)
    event = GateEvent(type="opened", record=record)

    assert event.record.pre_review == verdict
    assert isinstance(GateStore, type)


def test_register_gate_kind_is_idempotent_and_returns_a_copy() -> None:
    """Repeated matching registrations preserve one registry entry."""
    kind = "task-5612-idempotent"
    register_gate_kind(kind, description="A test gate")
    register_gate_kind(kind, description="A test gate")

    kinds = registered_kinds()
    kinds[kind] = "modified only in copy"

    assert is_registered(kind)
    assert registered_kinds()[kind] == "A test gate"


def test_register_gate_kind_rejects_empty_and_conflicting_kinds() -> None:
    """Empty kinds fail validation and differing registrations fail with a typed error."""
    with pytest.raises(ValueError):
        register_gate_kind("   ")

    kind = "task-5612-conflict"
    register_gate_kind(kind, description="First description")

    with pytest.raises(GateError) as error:
        register_gate_kind(kind, description="Second description")

    assert error.value.code is GateErrorCode.GATE_KIND_CONFLICT
    assert not is_registered("task-5612-unknown")
