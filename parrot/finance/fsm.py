"""
Finance FSM — State Machines for Order Lifecycle & Pipeline Phases.

Two StateMachine subclasses using python-statemachine:

    OrderStateMachine:
        Governs the lifecycle of a single TradingOrder.
        Enforces valid transitions and records audit trail via
        TradingOrder.change_status() on every transition.

    PipelineStateMachine:
        Governs the overall trading pipeline (deliberation → execution).
        Provides phase-tracking and halt/resume support.

Helper:
    transition_order(order, event, changed_by, reason):
        Convenience wrapper that creates an OrderStateMachine,
        fires the named event, and records the status change.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from statemachine import State, StateMachine
from navconfig.logging import logging


# ─── Forward import (avoid circular) ────────────────────────────────
# We import TradingOrder and OrderStatus at function level where needed
# to avoid circular dependency with schemas.py.


# =====================================================================
# ORDER STATE MACHINE
# =====================================================================


class OrderStateMachine(StateMachine):
    """FSM for a single TradingOrder lifecycle.

    States mirror OrderStatus enum values:
        pending → validating → executing → filled
                            ↘ constraint_rejected
                                        ↘ partially_filled
                                        ↘ platform_rejected
        pending → expired
        pending / validating / executing → cancelled
    """

    # ── States ───────────────────────────────────────────────────
    pending = State("pending", initial=True)
    validating = State("validating")
    executing = State("executing")
    filled = State("filled", final=True)
    partially_filled = State("partially_filled", final=True)
    constraint_rejected = State("constraint_rejected", final=True)
    platform_rejected = State("platform_rejected", final=True)
    expired = State("expired", final=True)
    cancelled = State("cancelled", final=True)

    # ── Transitions ──────────────────────────────────────────────
    route = pending.to(validating)
    reject = (
        pending.to(constraint_rejected)
        | validating.to(constraint_rejected)
    )
    execute = validating.to(executing)
    fill = executing.to(filled)
    partial_fill = executing.to(partially_filled)
    platform_reject = executing.to(platform_rejected)
    expire = pending.to(expired)
    cancel = (
        pending.to(cancelled)
        | validating.to(cancelled)
        | executing.to(cancelled)
    )

    def __init__(self, order: Any, **kwargs: Any) -> None:
        self.order = order
        self._changed_by: str = ""
        self._reason: str = ""
        self._logger = logging.getLogger("TradingSwarm.OrderFSM")
        super().__init__(**kwargs)

    def fire(self, event: str, changed_by: str, reason: str) -> None:
        """Fire a named transition with audit metadata."""
        self._changed_by = changed_by
        self._reason = reason
        # StateMachine.send() dispatches to the transition method
        self.send(event)

    # ── Callbacks ────────────────────────────────────────────────

    def after_transition(self, source: State, target: State, event: str) -> None:
        """Record every transition in the order's audit trail."""
        from .schemas import OrderStatus

        old_status = OrderStatus(source.id)
        new_status = OrderStatus(target.id)

        self.order.change_status(
            new_status=new_status,
            changed_by=self._changed_by or event,
            reason=self._reason or f"Transition: {event}",
        )
        self._logger.debug(
            "Order %s: %s → %s (%s)",
            self.order.id[:8],
            old_status.value,
            new_status.value,
            event,
        )

    def on_enter_filled(self) -> None:
        self._logger.info(
            "Order %s FILLED: %s %s",
            self.order.id[:8],
            self.order.action,
            self.order.asset,
        )

    def on_enter_constraint_rejected(self) -> None:
        self._logger.warning(
            "Order %s REJECTED: %s",
            self.order.id[:8],
            self._reason,
        )

    def on_enter_platform_rejected(self) -> None:
        self._logger.warning(
            "Order %s PLATFORM_REJECTED: %s",
            self.order.id[:8],
            self._reason,
        )

    def on_enter_expired(self) -> None:
        self._logger.info(
            "Order %s EXPIRED: %s",
            self.order.id[:8],
            self.order.asset,
        )


# =====================================================================
# PIPELINE PHASE ENUM
# =====================================================================


class PipelinePhase(str, Enum):
    """High-level phases of the trading pipeline."""
    IDLE = "idle"
    RESEARCHING = "researching"
    ENRICHING = "enriching"
    DELIBERATING = "deliberating"
    DISPATCHING = "dispatching"
    EXECUTING = "executing"
    MONITORING = "monitoring"
    COMPLETED = "completed"
    HALTED = "halted"
    FAILED = "failed"


# =====================================================================
# PIPELINE STATE MACHINE
# =====================================================================


class PipelineStateMachine(StateMachine):
    """FSM for the overall trading pipeline phases.

    Flow:
        idle → researching → deliberating → dispatching
             → executing → monitoring → completed

    Emergency:
        any (except completed/failed) → halted
        halted → monitoring (resume)
        any → failed
    """

    # ── States ───────────────────────────────────────────────────
    idle = State("idle", initial=True)
    researching = State("researching")
    enriching = State("enriching")
    deliberating = State("deliberating")
    dispatching = State("dispatching")
    executing = State("executing")
    monitoring = State("monitoring")
    completed = State("completed", final=True)
    halted = State("halted")
    failed = State("failed", final=True)

    # ── Transitions ──────────────────────────────────────────────
    start_research = idle.to(researching)
    start_enrichment = researching.to(enriching)
    start_deliberation = (
        idle.to(deliberating)
        | researching.to(deliberating)    # Direct path (no Massive)
        | enriching.to(deliberating)      # Enriched path
    )
    start_dispatch = deliberating.to(dispatching)
    start_execution = dispatching.to(executing)
    start_monitoring = executing.to(monitoring)
    complete = monitoring.to(completed)

    # Emergency transitions
    halt = (
        idle.to(halted)
        | researching.to(halted)
        | enriching.to(halted)
        | deliberating.to(halted)
        | dispatching.to(halted)
        | executing.to(halted)
        | monitoring.to(halted)
    )
    resume = halted.to(monitoring)
    fail = (
        idle.to(failed)
        | researching.to(failed)
        | enriching.to(failed)
        | deliberating.to(failed)
        | dispatching.to(failed)
        | executing.to(failed)
        | monitoring.to(failed)
        | halted.to(failed)
    )

    def __init__(self, pipeline_id: str = "", **kwargs: Any) -> None:
        self.pipeline_id = pipeline_id
        self._logger = logging.getLogger("TradingSwarm.PipelineFSM")
        super().__init__(**kwargs)

    def after_transition(self, source: State, target: State, event: str) -> None:
        self._logger.info(
            "Pipeline %s: %s → %s (%s)",
            self.pipeline_id or "default",
            source.id,
            target.id,
            event,
        )

    def on_enter_halted(self) -> None:
        self._logger.critical(
            "Pipeline %s HALTED", self.pipeline_id or "default"
        )

    def on_enter_completed(self) -> None:
        self._logger.info(
            "Pipeline %s COMPLETED", self.pipeline_id or "default"
        )

    def on_enter_failed(self) -> None:
        self._logger.error(
            "Pipeline %s FAILED", self.pipeline_id or "default"
        )

    @property
    def phase(self) -> PipelinePhase:
        """Current pipeline phase as a PipelinePhase enum."""
        return PipelinePhase(self.current_state.id)


# =====================================================================
# HELPER: transition_order()
# =====================================================================


def transition_order(
    order: Any,
    event: str,
    changed_by: str,
    reason: str,
) -> None:
    """Fire a named transition on an order's FSM.

    If the order doesn't have a cached FSM instance, one is created
    and attached as ``order.fsm_instance``.  Subsequent calls reuse it.

    Args:
        order: A TradingOrder dataclass instance.
        event: FSM event name (route, reject, execute, fill, etc.).
        changed_by: Identifier of who triggered the change.
        reason: Human-readable reason for the transition.

    Raises:
        statemachine.exceptions.TransitionNotAllowed:
            If the transition is invalid from the current state.
    """
    fsm: OrderStateMachine | None = getattr(order, "fsm_instance", None)

    if fsm is None:
        from .schemas import OrderStatus

        fsm = OrderStateMachine(order=order)

        # If the order is not in PENDING (e.g., it was restored from
        # a checkpoint), we need to advance the FSM to the current
        # state without recording duplicate history.
        if order.status != OrderStatus.PENDING:
            _sync_fsm_to_order_state(fsm, order.status)

        order.fsm_instance = fsm  # type: ignore[attr-defined]

    fsm.fire(event, changed_by, reason)


def _sync_fsm_to_order_state(
    fsm: OrderStateMachine,
    target_status: Any,
) -> None:
    """Advance FSM to match an order's current status silently.

    Used when creating an FSM for an order that's already past PENDING
    (e.g., loaded from persistence). We walk the shortest path from
    pending to the target state without recording history entries.
    """
    from .schemas import OrderStatus

    # Map of OrderStatus → state path to reach it from pending
    _STATUS_PATHS: dict[OrderStatus, list[str]] = {
        OrderStatus.PENDING: [],
        OrderStatus.VALIDATING: ["route"],
        OrderStatus.EXECUTING: ["route", "execute"],
        OrderStatus.FILLED: ["route", "execute", "fill"],
        OrderStatus.PARTIALLY_FILLED: ["route", "execute", "partial_fill"],
        OrderStatus.CONSTRAINT_REJECTED: ["reject"],
        OrderStatus.PLATFORM_REJECTED: ["route", "execute", "platform_reject"],
        OrderStatus.EXPIRED: ["expire"],
        OrderStatus.CANCELLED: ["cancel"],
    }

    path = _STATUS_PATHS.get(target_status, [])

    # Temporarily swap the real order for a dummy to avoid
    # recording spurious history entries during sync.
    real_order = fsm.order

    class _DummyOrder:
        """No-op stand-in to absorb change_status calls during sync."""
        id = "sync"
        action = ""
        asset = ""
        def change_status(self, **_kw: Any) -> None:
            pass

    fsm.order = _DummyOrder()  # type: ignore[assignment]
    try:
        for event in path:
            fsm.send(event)
    finally:
        fsm.order = real_order

