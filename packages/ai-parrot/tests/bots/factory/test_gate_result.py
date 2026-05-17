"""Unit tests for the orchestrator's HITL gate-result normalisation."""
from types import SimpleNamespace

import pytest

from parrot.bots.factory.contracts import FactoryStatus
from parrot.bots.factory.orchestrator import _GateResult, _is_approval
from parrot.human.models import InteractionStatus


class TestIsApproval:
    @pytest.mark.parametrize(
        "value",
        [True, "confirm", "approve", "approved", "YES", "y", {"key": "confirm"}],
    )
    def test_truthy_inputs(self, value):
        assert _is_approval(value) is True

    @pytest.mark.parametrize(
        "value", [False, None, "cancel", "no", {"key": "cancel"}, 42]
    )
    def test_falsy_inputs(self, value):
        assert _is_approval(value) is False


class TestGateResult:
    def test_completed_with_confirm_is_approved(self):
        result = SimpleNamespace(
            status=InteractionStatus.COMPLETED, consolidated_value="confirm"
        )
        gate = _GateResult.from_interaction_result(result)
        assert gate.approved is True
        assert gate.status == FactoryStatus.SUCCESS

    def test_completed_with_cancel_is_rejected(self):
        result = SimpleNamespace(
            status=InteractionStatus.COMPLETED, consolidated_value="cancel"
        )
        gate = _GateResult.from_interaction_result(result)
        assert gate.approved is False
        assert gate.status == FactoryStatus.CANCELLED_BY_USER

    def test_timeout_maps_to_factory_timeout(self):
        result = SimpleNamespace(
            status=InteractionStatus.TIMEOUT, consolidated_value=None
        )
        gate = _GateResult.from_interaction_result(result)
        assert gate.approved is False
        assert gate.status == FactoryStatus.TIMEOUT

    def test_cancelled_status_maps_to_cancel(self):
        result = SimpleNamespace(
            status=InteractionStatus.CANCELLED, consolidated_value=None
        )
        gate = _GateResult.from_interaction_result(result)
        assert gate.approved is False
        assert gate.status == FactoryStatus.CANCELLED_BY_USER

    def test_approval_interaction_returns_bool_true(self):
        result = SimpleNamespace(
            status=InteractionStatus.COMPLETED, consolidated_value=True
        )
        gate = _GateResult.from_interaction_result(result)
        assert gate.approved is True
