"""Tests for the Finance FSM module.

Covers:
    - OrderStateMachine happy paths and rejections
    - Invalid transition enforcement
    - Audit trail via TradingOrder.change_status()
    - PipelineStateMachine lifecycle
    - transition_order() convenience helper
"""

import pytest
from statemachine.exceptions import TransitionNotAllowed

from parrot.finance.schemas import (
    AssetClass,
    ConsensusLevel,
    OrderStatus,
    TradingOrder,
)
from parrot.finance.fsm import (
    OrderStateMachine,
    PipelinePhase,
    PipelineStateMachine,
    transition_order,
)


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

def _make_order(**kwargs) -> TradingOrder:
    """Create a minimal TradingOrder for testing."""
    defaults = dict(
        asset="AAPL",
        asset_class=AssetClass.STOCK,
        action="BUY",
        order_type="limit",
        sizing_pct=2.0,
        consensus_level=ConsensusLevel.UNANIMOUS,
    )
    defaults.update(kwargs)
    return TradingOrder(**defaults)


# ──────────────────────────────────────────────────────────────────────
# TradingOrder.change_status()
# ──────────────────────────────────────────────────────────────────────

class TestChangeStatus:
    """Test the TradingOrder.change_status() audit recording."""

    def test_records_history(self):
        order = _make_order()
        assert order.status == OrderStatus.PENDING
        assert len(order.status_history) == 0

        order.change_status(
            OrderStatus.VALIDATING, changed_by="test", reason="unit test"
        )

        assert order.status == OrderStatus.VALIDATING
        assert len(order.status_history) == 1
        entry = order.status_history[0]
        assert entry.from_status == OrderStatus.PENDING
        assert entry.to_status == OrderStatus.VALIDATING
        assert entry.changed_by == "test"
        assert entry.reason == "unit test"

    def test_multiple_changes_accumulate(self):
        order = _make_order()
        order.change_status(
            OrderStatus.VALIDATING, changed_by="a", reason="r1"
        )
        order.change_status(
            OrderStatus.EXECUTING, changed_by="b", reason="r2"
        )
        assert len(order.status_history) == 2
        assert order.status_history[0].to_status == OrderStatus.VALIDATING
        assert order.status_history[1].to_status == OrderStatus.EXECUTING


# ──────────────────────────────────────────────────────────────────────
# OrderStateMachine
# ──────────────────────────────────────────────────────────────────────

class TestOrderStateMachine:
    """Test the OrderStateMachine transitions."""

    def test_happy_path_filled(self):
        """PENDING → VALIDATING → EXECUTING → FILLED."""
        order = _make_order()
        fsm = OrderStateMachine(order=order)

        fsm.fire("route", changed_by="router", reason="assigned")
        assert order.status == OrderStatus.VALIDATING

        fsm.fire("execute", changed_by="orch", reason="dispatching")
        assert order.status == OrderStatus.EXECUTING

        fsm.fire("fill", changed_by="executor", reason="filled ok")
        assert order.status == OrderStatus.FILLED

        # 3 transitions → 3 history entries
        assert len(order.status_history) == 3

    def test_rejection_from_pending(self):
        """PENDING → CONSTRAINT_REJECTED."""
        order = _make_order()
        fsm = OrderStateMachine(order=order)

        fsm.fire("reject", changed_by="router", reason="no executor")
        assert order.status == OrderStatus.CONSTRAINT_REJECTED
        assert len(order.status_history) == 1

    def test_rejection_from_validating(self):
        """PENDING → VALIDATING → CONSTRAINT_REJECTED."""
        order = _make_order()
        fsm = OrderStateMachine(order=order)

        fsm.fire("route", changed_by="router", reason="assigned")
        fsm.fire("reject", changed_by="orch", reason="constraint violation")

        assert order.status == OrderStatus.CONSTRAINT_REJECTED
        assert len(order.status_history) == 2

    def test_partial_fill(self):
        """PENDING → VALIDATING → EXECUTING → PARTIALLY_FILLED."""
        order = _make_order()
        fsm = OrderStateMachine(order=order)

        fsm.fire("route", changed_by="router", reason="ok")
        fsm.fire("execute", changed_by="orch", reason="dispatch")
        fsm.fire("partial_fill", changed_by="executor", reason="50% filled")

        assert order.status == OrderStatus.PARTIALLY_FILLED

    def test_platform_reject(self):
        """PENDING → VALIDATING → EXECUTING → PLATFORM_REJECTED."""
        order = _make_order()
        fsm = OrderStateMachine(order=order)

        fsm.fire("route", changed_by="router", reason="ok")
        fsm.fire("execute", changed_by="orch", reason="dispatch")
        fsm.fire(
            "platform_reject", changed_by="executor", reason="API error"
        )

        assert order.status == OrderStatus.PLATFORM_REJECTED

    def test_expiry(self):
        """PENDING → EXPIRED."""
        order = _make_order()
        fsm = OrderStateMachine(order=order)

        fsm.fire("expire", changed_by="queue", reason="TTL expired")
        assert order.status == OrderStatus.EXPIRED

    def test_cancel_from_pending(self):
        """PENDING → CANCELLED."""
        order = _make_order()
        fsm = OrderStateMachine(order=order)

        fsm.fire("cancel", changed_by="user", reason="manual cancel")
        assert order.status == OrderStatus.CANCELLED

    def test_cancel_from_validating(self):
        """VALIDATING → CANCELLED."""
        order = _make_order()
        fsm = OrderStateMachine(order=order)

        fsm.fire("route", changed_by="router", reason="ok")
        fsm.fire("cancel", changed_by="user", reason="changed mind")

        assert order.status == OrderStatus.CANCELLED

    def test_cancel_from_executing(self):
        """EXECUTING → CANCELLED."""
        order = _make_order()
        fsm = OrderStateMachine(order=order)

        fsm.fire("route", changed_by="router", reason="ok")
        fsm.fire("execute", changed_by="orch", reason="dispatch")
        fsm.fire("cancel", changed_by="user", reason="emergency")

        assert order.status == OrderStatus.CANCELLED


class TestOrderStateMachineInvalidTransitions:
    """Test that invalid transitions raise TransitionNotAllowed."""

    def test_cannot_fill_from_pending(self):
        """PENDING → FILLED should be invalid (skips validating+executing)."""
        order = _make_order()
        fsm = OrderStateMachine(order=order)

        with pytest.raises(TransitionNotAllowed):
            fsm.fire("fill", changed_by="test", reason="invalid")

    def test_cannot_execute_from_pending(self):
        """PENDING → EXECUTING should be invalid (skips validating)."""
        order = _make_order()
        fsm = OrderStateMachine(order=order)

        with pytest.raises(TransitionNotAllowed):
            fsm.fire("execute", changed_by="test", reason="invalid")

    def test_cannot_route_from_validating(self):
        """VALIDATING → VALIDATING (route again) should be invalid."""
        order = _make_order()
        fsm = OrderStateMachine(order=order)

        fsm.fire("route", changed_by="router", reason="ok")

        with pytest.raises(TransitionNotAllowed):
            fsm.fire("route", changed_by="test", reason="double route")

    def test_cannot_transition_from_final_state(self):
        """FILLED is final; no transitions should be possible."""
        order = _make_order()
        fsm = OrderStateMachine(order=order)

        fsm.fire("route", changed_by="router", reason="ok")
        fsm.fire("execute", changed_by="orch", reason="dispatch")
        fsm.fire("fill", changed_by="executor", reason="done")

        with pytest.raises(TransitionNotAllowed):
            fsm.fire("cancel", changed_by="test", reason="too late")

    def test_cannot_expire_from_executing(self):
        """EXECUTING → EXPIRED should be invalid."""
        order = _make_order()
        fsm = OrderStateMachine(order=order)

        fsm.fire("route", changed_by="router", reason="ok")
        fsm.fire("execute", changed_by="orch", reason="dispatch")

        with pytest.raises(TransitionNotAllowed):
            fsm.fire("expire", changed_by="test", reason="invalid")


# ──────────────────────────────────────────────────────────────────────
# transition_order() helper
# ──────────────────────────────────────────────────────────────────────

class TestTransitionOrder:
    """Test the transition_order() convenience function."""

    def test_creates_fsm_and_transitions(self):
        order = _make_order()
        assert not hasattr(order, "fsm_instance")

        transition_order(order, "route", "router", "assigned to stock")

        assert order.status == OrderStatus.VALIDATING
        assert hasattr(order, "fsm_instance")
        assert len(order.status_history) == 1

    def test_reuses_cached_fsm(self):
        order = _make_order()
        transition_order(order, "route", "router", "assigned")
        fsm_1 = order.fsm_instance

        transition_order(order, "execute", "orch", "dispatch")
        fsm_2 = order.fsm_instance

        assert fsm_1 is fsm_2

    def test_invalid_transition_raises(self):
        order = _make_order()

        with pytest.raises(TransitionNotAllowed):
            transition_order(order, "fill", "test", "invalid")

    def test_full_lifecycle_via_helper(self):
        order = _make_order()
        transition_order(order, "route", "router", "r1")
        transition_order(order, "execute", "orch", "r2")
        transition_order(order, "fill", "exec", "r3")

        assert order.status == OrderStatus.FILLED
        assert len(order.status_history) == 3

        # Verify audit trail details
        assert order.status_history[0].changed_by == "router"
        assert order.status_history[1].changed_by == "orch"
        assert order.status_history[2].changed_by == "exec"

    def test_sync_from_non_pending_state(self):
        """If order starts at VALIDATING, FSM should sync without extra history."""
        order = _make_order()
        # Simulate an order already at VALIDATING (e.g., from persistence)
        order.status = OrderStatus.VALIDATING

        # This should NOT raise — FSM syncs to VALIDATING silently
        transition_order(order, "execute", "orch", "dispatch")

        assert order.status == OrderStatus.EXECUTING
        # Only 1 history entry (the execute transition), not the sync
        assert len(order.status_history) == 1


# ──────────────────────────────────────────────────────────────────────
# PipelineStateMachine
# ──────────────────────────────────────────────────────────────────────

class TestPipelineStateMachine:
    """Test the PipelineStateMachine transitions."""

    def test_happy_path(self):
        """Full pipeline: idle → deliberating → ... → completed."""
        fsm = PipelineStateMachine(pipeline_id="test")

        assert fsm.phase == PipelinePhase.IDLE

        fsm.start_deliberation()
        assert fsm.phase == PipelinePhase.DELIBERATING

        fsm.start_dispatch()
        assert fsm.phase == PipelinePhase.DISPATCHING

        fsm.start_execution()
        assert fsm.phase == PipelinePhase.EXECUTING

        fsm.start_monitoring()
        assert fsm.phase == PipelinePhase.MONITORING

        fsm.complete()
        assert fsm.phase == PipelinePhase.COMPLETED

    def test_with_research_phase(self):
        """idle → researching → deliberating → ... → completed."""
        fsm = PipelineStateMachine()

        fsm.start_research()
        assert fsm.phase == PipelinePhase.RESEARCHING

        fsm.start_deliberation()
        assert fsm.phase == PipelinePhase.DELIBERATING

    def test_halt_and_resume(self):
        """EXECUTING → HALTED → MONITORING → COMPLETED."""
        fsm = PipelineStateMachine()

        fsm.start_deliberation()
        fsm.start_dispatch()
        fsm.start_execution()

        fsm.halt()
        assert fsm.phase == PipelinePhase.HALTED

        fsm.resume()
        assert fsm.phase == PipelinePhase.MONITORING

        fsm.complete()
        assert fsm.phase == PipelinePhase.COMPLETED

    def test_fail_from_any_state(self):
        """Any non-final state → FAILED."""
        for start_events in [
            [],  # idle
            ["start_deliberation"],
            ["start_deliberation", "start_dispatch"],
            ["start_deliberation", "start_dispatch", "start_execution"],
        ]:
            fsm = PipelineStateMachine()
            for ev in start_events:
                fsm.send(ev)

            fsm.fail()
            assert fsm.phase == PipelinePhase.FAILED

    def test_cannot_transition_from_completed(self):
        """COMPLETED is final; no transitions possible."""
        fsm = PipelineStateMachine()
        fsm.start_deliberation()
        fsm.start_dispatch()
        fsm.start_execution()
        fsm.start_monitoring()
        fsm.complete()

        with pytest.raises(TransitionNotAllowed):
            fsm.halt()

    def test_cannot_skip_dispatch(self):
        """DELIBERATING → EXECUTING should be invalid (skips dispatch)."""
        fsm = PipelineStateMachine()
        fsm.start_deliberation()

        with pytest.raises(TransitionNotAllowed):
            fsm.start_execution()


# ──────────────────────────────────────────────────────────────────────
# Audit Trail Completeness
# ──────────────────────────────────────────────────────────────────────

class TestAuditTrail:
    """Verify audit trail completeness for full order lifecycles."""

    def test_rejection_audit_trail(self):
        """Full audit trail for a rejected order."""
        order = _make_order()
        transition_order(order, "route", "order_router", "assigned to stock")
        transition_order(order, "reject", "orchestrator", "constraint fail")

        assert len(order.status_history) == 2
        h0, h1 = order.status_history

        assert h0.from_status == OrderStatus.PENDING
        assert h0.to_status == OrderStatus.VALIDATING
        assert h0.changed_by == "order_router"

        assert h1.from_status == OrderStatus.VALIDATING
        assert h1.to_status == OrderStatus.CONSTRAINT_REJECTED
        assert h1.changed_by == "orchestrator"

    def test_filled_audit_trail(self):
        """Full audit trail for a filled order."""
        order = _make_order()
        transition_order(order, "route", "order_router", "assigned")
        transition_order(order, "execute", "orchestrator", "dispatch")
        transition_order(order, "fill", "stock_executor", "Action: executed")

        assert len(order.status_history) == 3
        statuses = [h.to_status for h in order.status_history]
        assert statuses == [
            OrderStatus.VALIDATING,
            OrderStatus.EXECUTING,
            OrderStatus.FILLED,
        ]

    def test_history_timestamps_are_present(self):
        """Each history entry has a timestamp."""
        order = _make_order()
        transition_order(order, "route", "router", "ok")
        transition_order(order, "execute", "orch", "dispatch")

        for entry in order.status_history:
            assert entry.timestamp is not None
