"""Flow Primitives — FSM Module.

Provides ``AgentTaskMachine`` (StateMachine subclass) and ``TransitionCondition``
enum for state-based agent lifecycle management.

Extracted from ``parrot.bots.flow.fsm`` to serve as the shared primitive
used by both AgentCrew and AgentsFlow engines.
"""
from __future__ import annotations

from enum import Enum

from navconfig.logging import logging
from statemachine import State, StateMachine


class TransitionCondition(str, Enum):
    """Predefined conditions that can trigger a flow transition.

    Values match the original ``TransitionCondition`` in
    ``parrot.bots.flow.fsm`` for backward compatibility.
    """

    ON_SUCCESS = "on_success"
    """Transition fires when the source node completes without error."""

    ON_ERROR = "on_error"
    """Transition fires when the source node raises an exception."""

    ON_TIMEOUT = "on_timeout"
    """Transition fires when the source node execution times out."""

    ON_CONDITION = "on_condition"
    """Transition fires when a custom ``predicate`` callable returns True."""

    ALWAYS = "always"
    """Unconditional transition — always fires after source node execution."""


class AgentTaskMachine(StateMachine):
    """Finite State Machine describing the lifecycle of a single node execution.

    States:
        idle: Node created but not yet scheduled.
        ready: All dependencies satisfied; node is queued for execution.
        running: Node is currently executing.
        completed: Node finished successfully (final — no further transitions).
        failed: Node execution failed (NOT final — ``retry`` is allowed).
        blocked: Node cannot proceed (missing dependencies or resources).

    Transitions:
        schedule: idle → ready (dependencies met)
        start: ready → running (begin execution)
        succeed: running → completed (successful completion)
        fail: running / ready / idle → failed (error occurred)
        block: idle / ready → blocked (dependencies not met)
        unblock: blocked → ready (dependencies now satisfied)
        retry: failed → ready (retry after failure)

    Example::

        fsm = AgentTaskMachine(agent_name="researcher")
        fsm.schedule()   # idle → ready
        fsm.start()      # ready → running
        fsm.succeed()    # running → completed
    """

    idle = State("idle", initial=True)
    ready = State("ready")
    running = State("running")
    completed = State("completed", final=True)
    failed = State("failed")
    blocked = State("blocked")

    # Transitions
    schedule = idle.to(ready)
    start = ready.to(running)
    succeed = running.to(completed)
    fail = running.to(failed) | ready.to(failed) | idle.to(failed)
    block = idle.to(blocked) | ready.to(blocked)
    unblock = blocked.to(ready)
    retry = failed.to(ready)

    def __init__(self, agent_name: str, **kwargs: object) -> None:
        """Initialise the FSM for a named agent/node.

        Args:
            agent_name: Human-readable name used in log messages.
            **kwargs: Forwarded to ``StateMachine.__init__``.
        """
        self.agent_name = agent_name
        # Per-instance scoped logger so FSM events can be filtered by component.
        self.logger = logging.getLogger(f"parrot.fsm.{agent_name}")
        super().__init__(**kwargs)

    # ── State-entry hooks (logging) ──────────────────────────────────────

    def on_enter_running(self) -> None:
        """Called when entering the ``running`` state."""
        self.logger.debug("Agent %s started execution", self.agent_name)

    def on_enter_completed(self) -> None:
        """Called when entering the ``completed`` state."""
        self.logger.info("Agent %s completed successfully", self.agent_name)

    def on_enter_failed(self) -> None:
        """Called when entering the ``failed`` state."""
        self.logger.error("Agent %s execution failed", self.agent_name)
